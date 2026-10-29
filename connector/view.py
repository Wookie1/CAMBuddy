"""TASK_VIEW3D: build view.bin/view.json - the display data for the panel's
3D viewer (part heightfield, final judged stock, program paths, markers).

DISPLAY ONLY: nothing written here is read by engine planning, and posted
programs (*.nc) are untouched. Data comes from files the run already has
(the run's part heightfield, the zmap --stock-out of the last program and
the posted programs themselves).

view.bin (little endian, deterministic bytes):
    part grid   uint16 ny*nx   z = z.offset + q*z.scale
    stock grid  uint16 ny*nx
    per program float32 xyz * n_points, then uint8 flags * n_points (1=feed)
    markers     float32 xyz * n_markers (order matches view.json "markers")

view.json carries the header: version, grid (x0/y0/cell/nx/ny), z
offset/scale, per-program point counts / decimation tolerance / cap / byte
offsets, marker codes and the offsets into view.bin. Units: mm.

Conservative downsampling to TARGET_CELL: the part keeps the cell MAX, the
stock the cell MIN, so the stock-left (stock - part) the viewer shows never
overstays what the judged 0.1/0.5 mm grids left. Paths are decimated with
Douglas-Peucker: every dropped point lies within the recorded tolerance of
the kept polyline; when a program still exceeds POINT_CAP the tolerance is
doubled until it fits and the tolerance USED is recorded per program.
"""
import json
import math
import os
import sys

import numpy as np

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from verify import zmap  # noqa: E402  (display data only; no judging here)

TARGET_CELL = 0.5          # mm, both heightfields are stored at this grid
SCALE = 0.01               # mm per uint16 step (spec: <= 0.01)
MAX_BYTES = 8 * 1024 * 1024  # view.bin + view.json target
POINT_CAP = 200000         # kept points per program
DEFAULT_TOL = 0.05         # mm, decimation tolerance (raised only to fit)


def downsample(a, k, mode):
    """Block-reduce a (ny, nx) grid by an integer factor k: 'max' or 'min'.
    Edges are padded by repeating the border (keeps the rule conservative
    for every complete source cell)."""
    if k <= 1:
        return a
    ny, nx = a.shape
    py, px = (-ny) % k, (-nx) % k
    if py or px:
        a = np.pad(a, ((0, py), (0, px)), mode="edge")
    h, w = a.shape[0] // k, a.shape[1] // k
    b = a.reshape(h, k, w, k)
    return b.max(axis=(1, 3)) if mode == "max" else b.min(axis=(1, 3))


NODATA = 65535             # uint16 code for a non-finite cell (no stock / outside the grid)
BELOW_TOL = 0.01           # mm: "below part" (red) only below this, the judge's gouge tolerance


def block_nanmin(a, k):
    """Per-block minimum of the FINITE values of a (ny, nx) grid; a block
    with no finite value is nan (-> nodata). Edges padded with nan."""
    if k <= 1:
        return np.where(np.isfinite(a), a, np.nan)
    ny, nx = a.shape
    a = np.where(np.isfinite(a), a, np.nan)
    py, px = (-ny) % k, (-nx) % k
    if py or px:
        a = np.pad(a, ((0, py), (0, px)), constant_values=np.nan)
    b = a.reshape(a.shape[0] // k, k, a.shape[1] // k, k)
    with np.errstate(all="ignore"):
        allnan = np.all(np.isnan(b), axis=(1, 3))
        m = np.nanmin(np.where(np.isnan(b), np.inf, b), axis=(1, 3))
    return np.where(allnan, np.nan, m)


def quantize(a, zoff, scale):
    fin = np.isfinite(a)
    q = np.clip(np.rint((np.where(fin, a, zoff) - zoff) / scale), 0, NODATA - 1)
    return np.where(fin, q, NODATA).astype("<u2")


def program_path(nc_path, cell=TARGET_CELL):
    """Densely sample a posted program: (points (n,3) float64, flags uint8)
    with flag 0 = rapid (G0), 1 = feed (G1/G2/G3). Arc resolution is
    verify.zmap's own (_move_samples: arcs interpolated in their plane)."""
    with open(nc_path) as fh:
        text = fh.read()
    moves = zmap.resolve_moves(zmap.parse_gcode(text))
    z0 = next((mv["z"] for mv in moves if mv.get("z") is not None), 0.0)
    cur = (0.0, 0.0, z0)
    pts, flags = [], []
    for mv in moves:
        samples, _ = zmap._move_samples(mv, cur, cell)
        pts.extend(samples)
        flags.extend([0 if mv["motion"] == "G0" else 1] * len(samples))
        cur = (mv["x"], mv["y"], mv["z"])
    if not pts:
        return np.zeros((0, 3)), np.zeros(0, dtype=np.uint8)
    return np.asarray(pts, dtype=np.float64), np.asarray(flags, dtype=np.uint8)


def _rdp_keep(pts, tol):
    """Douglas-Peucker: boolean mask of kept points (endpoints always)."""
    n = len(pts)
    keep = np.zeros(n, dtype=bool)
    if n == 0:
        return keep
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = pts[b] - pts[a]
        ll = float(seg @ seg)
        d = pts[a:b + 1] - pts[a]
        if ll > 0.0:
            t = np.clip((d @ seg) / ll, 0.0, 1.0)
            dist = np.linalg.norm(d - t[:, None] * seg, axis=1)
        else:
            dist = np.linalg.norm(d, axis=1)
        i = int(np.argmax(dist))
        if dist[i] > tol:
            keep[a + i] = True
            stack.append((a, a + i))
            stack.append((a + i, b))
    return keep


def decimate(points, tol, flags):
    """Indices kept at tolerance tol. Flag changes (rapid <-> feed) are
    mandatory anchors, so the feed/rapid split stays exact."""
    n = len(points)
    if n <= 2:
        return np.arange(n)
    anchors = [0]
    chg = np.flatnonzero(flags[1:] != flags[:-1]) + 1
    anchors.extend(int(i) for i in chg)
    anchors.append(n - 1)
    keep = np.zeros(n, dtype=bool)
    for a, b in zip(anchors[:-1], anchors[1:]):
        keep[a:b + 1] |= _rdp_keep(points[a:b + 1], tol)
    return np.flatnonzero(keep)


def path_error(points, kept):
    """Max distance from any point of `points` to the polyline `kept`."""
    if len(points) == 0 or len(kept) == 0:
        return 0.0
    best = np.full(len(points), np.inf)
    for a, b in zip(kept[:-1], kept[1:]):
        seg = b - a
        ll = float(seg @ seg)
        d = points - a
        if ll > 0.0:
            t = np.clip((d @ seg) / ll, 0.0, 1.0)
            dist = np.linalg.norm(d - t[:, None] * seg, axis=1)
        else:
            dist = np.linalg.norm(d, axis=1)
        np.minimum(best, dist, out=best)
    return float(best.max())


def markers_from_checks(checks):
    """Attention-style gate entries (count > 0 with a worst_xy) become view
    markers {code, x, y, z}. `checks` maps program name -> its check.json."""
    out = []
    for name in sorted(checks):
        chk = checks[name] or {}
        for gate in ("gouges", "rapid_collisions", "over_flute",
                     "holder_hits", "axial_plunges"):
            d = chk.get(gate)
            if not isinstance(d, dict) or not (d.get("count") or 0) > 0:
                continue
            xy = d.get("worst_xy")
            if (isinstance(xy, (list, tuple)) and len(xy) >= 2
                    and all(isinstance(v, (int, float)) and
                            math.isfinite(v) for v in xy[:2])):
                z = d.get("worst_z")
                out.append({"code": "%s.%s" % (name, gate),
                            "x": float(xy[0]), "y": float(xy[1]),
                            "z": float(z) if isinstance(z, (int, float))
                            and math.isfinite(z) else None})
    return out


def build_view(out_bin, out_json, part_npy, stock_npy, programs, checks,
               point_cap=POINT_CAP, tol=DEFAULT_TOL):
    """Write view.bin + view.json next to each other; return the header.
    part_npy: the run's part heightfield (.npy + sidecar); stock_npy: the
    final judged stock (same grid). programs: [(name, nc_path)]."""
    part, cell, x0, y0 = zmap.load_part(part_npy)
    part = np.asarray(part, dtype=np.float64)
    stock = np.asarray(np.load(stock_npy), dtype=np.float64)
    if stock.shape != part.shape:
        raise ValueError("view: stock grid %r != part grid %r"
                         % (stock.shape, part.shape))
    k = max(1, int(round(TARGET_CELL / cell)))
    pgrid = downsample(part, k, "max")
    sgrid = downsample(stock, k, "min")
    ny, nx = pgrid.shape
    fin = np.concatenate([pgrid[np.isfinite(pgrid)], sgrid[np.isfinite(sgrid)]])
    zmin = float(fin.min()) if fin.size else 0.0     # real stocks carry -inf
    zmax = float(fin.max()) if fin.size else 0.0     # cells outside the box
    zoff = math.floor(zmin * 1000.0) / 1000.0
    scale = SCALE
    if zmax - zoff > (NODATA - 1) * scale:   # > 655 mm tall: stay representable
        scale = (zmax - zoff) / 65534.0
    body = quantize(pgrid, zoff, scale).tobytes()
    offsets = {"part": 0, "stock": len(body)}
    body += quantize(sgrid, zoff, scale).tobytes()
    # v2 "left": per-block MIN of the FINE (stock - part) at the source cell
    # (block max of part vs block min of stock invents wall-height "below
    # part" at every steep wall; the fine difference does not)
    with np.errstate(invalid="ignore"):
        lgrid = block_nanmin(stock - part, k)
    lfin = lgrid[np.isfinite(lgrid)]
    loff = math.floor(float(lfin.min()) * 1000.0) / 1000.0 if lfin.size else 0.0
    lmax = float(lfin.max()) if lfin.size else 0.0
    lscale = SCALE if lmax - loff <= (NODATA - 1) * SCALE \
        else (lmax - loff) / 65534.0
    offsets["left"] = len(body)
    body += quantize(lgrid, loff, lscale).tobytes()
    progs = []
    for name, path in programs:
        pts, flags = program_path(path)
        used = tol
        keep = decimate(pts, used, flags) if len(pts) else keep0
        while len(keep) > point_cap and used <= 512.0:
            used *= 2.0
            keep = decimate(pts, used, flags)
        kp = pts[keep]
        kf = flags[keep]
        idx = len(progs)
        xyz_off = len(body)
        body += kp.astype("<f4").tobytes()
        flags_off = len(body)
        body += kf.astype(np.uint8).tobytes()
        offsets["p%d.xyz" % idx] = xyz_off
        offsets["p%d.flags" % idx] = flags_off
        progs.append({"name": name, "points": int(len(kp)),
                      "tolerance_mm": used, "cap": int(point_cap),
                      "xyz_offset": xyz_off, "flags_offset": flags_off})
    markers = markers_from_checks(checks)
    offsets["markers"] = len(body)
    for m in markers:
        body += np.asarray([m["x"], m["y"], m["z"] or 0.0],
                           dtype="<f4").tobytes()
    if len(body) > MAX_BYTES:
        raise ValueError("view: view.bin would be %d bytes > cap %d"
                         % (len(body), MAX_BYTES))
    with open(out_bin, "wb") as fh:
        fh.write(body)
    hdr = {"format": "stevecam-view", "version": 2, "units": "mm",
           "grid": {"x0": float(x0), "y0": float(y0),
                    "cell": float(cell * k), "nx": int(nx), "ny": int(ny)},
           "z": {"offset": float(zoff), "scale": float(scale),
                 "nodata": NODATA, "left_offset": float(loff),
                 "left_scale": float(lscale)},
           "below_tol_mm": BELOW_TOL,
           "programs": progs, "markers": markers,
           "offsets": offsets, "bytes": len(body)}
    with open(out_json, "w") as fh:
        fh.write(json.dumps(hdr, sort_keys=True))
    return hdr


keep0 = np.zeros(0, dtype=np.int64)
