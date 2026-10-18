"""Slope-split finishing (action: slope_split_finish) from OpenCAMLib CL
points only (task S1, track B).

Why not VibeCAD's SteepShallow: its steep contours interpolate iso-crossings
linearly on a CL heightfield, so next to slots narrower than the ball the
tool is placed inside CL step discontinuities, up to ~10 mm below the
gouge-free CL (spike/DIAG_steepshallow.md). This module never interpolates
the CL surface: every cutter position is a true ocl drop-cutter or
AdaptiveWaterline point (waterline points are additionally validated against
drop-cutter and lifted to CL where ocl's level solve lands slightly below it,
near tangencies), and simplification drops a CL point only when the chord
between its kept neighbours stays within 0.005 mm of the drop-cutter CL,
checked on samples along the curve AND - where the curve bows off the chord -
along the chord line itself (a cutter position is gouge-free iff its tip z is
>= CL at its own xy, which near convex corners is only true on the chord).

Shallow: drop-cutter raster (BatchDropCutter, ball 6 default) along X at
`stepover` (default 0.3 mm), sampled at `sampling` (0.1 mm). Slope per CL
point from the CL-surface gradient of that grid; keep slope < threshold
(default 40 deg); rows serpentine (alternate direction) so consecutive rows
connect with a short stepover link - never a full-width re-traversal of an
already-cut row (S2c). The transition band into the steep zone is covered by
the steep pass (segments with slope >= threshold - overlap_deg at every
level), not by duplicated shallow rows.
Steep (task S2 PLAN B, replaces OCL waterline): ONE batched drop-cutter CL
grid at `sampling` pitch over the steep-region mask dilated by the ball
radius, computed once per run; per Z level (stepdown default 0.3 mm, levels
within 0.05 mm of a flat-face Z shifted up) marching squares extracts the
contour CL = Z with {CL >= Z} as material side; every contour point is
refined by batched bisection on its grid edge against the true drop-cutter
CL until the bracket's XY width <= 0.002 mm, emitting the low-side endpoint
(CL <= Z + 0.005 mm: at CL jumps this is the jump line at offset r, the
correct waterline next to a vertical wall); a one-sided net (CL - z <=
CHORD_TOL) removes any remaining violator and splits runs there. Points are
never lowered.
Links: stay down only if drop-cutter along the link stays below the link;
otherwise, where drop-cutter along the swept XY path (sampled <= 0.25 mm)
verifies max CL + margin (default 1 mm) + roughing-stock allowance (1 mm)
fits under the retract height, retract to that minimum verified-clear height,
G0 across, plunge at ramp feed (S3 item 1); else retract to local max CL +
1 mm and traverse at feed. With --stock-from (post-roughing stock heightfield,
S3b) the required height additionally includes the stock top within the tool
radius along the swept path.

moves are the neutral dicts of engine/gcode.py: {g:0|1, x, y, z, f}.
"""
import json
import math
import multiprocessing as mp
import os
import time

import numpy as np
from opencamlib import ocl

CHORD_TOL = 0.005     # mm, one-sided gouge-safe chord tolerance
NET_TOL = 0.004       # mm, internal check tol: leaves margin under
                      # CHORD_TOL for between-sample CL bulge (kappa*L^2/8)
LINK_LIFT = 1.0       # mm above local max CL when a link is blocked
RAPID_MARGIN = 1.0    # mm, safety margin above max CL along a link path for
                      # a G0 rapid traverse (S3: verified-clear rapid links)
RAPID_STOCK_ALLOW = 1.0  # mm, extra clearance over the part for the roughing
                         # leftover stock above it (allowance + steps bound);
                         # drop-cutter CL is computed on the PART, so a rapid
                         # must sit above part + allowance + steps unless a
                         # stock model is checked directly (S3 item 1)
RAPID_LINK_SS = 0.25  # mm, max drop-cutter sample spacing along a rapid link
NO_CONTACT = -1e30    # ocl keeps the initial Z when nothing is touched
DROP_CHUNK = 250_000  # CLPoints per BatchDropCutter call
BALL_HEIGHT = 50.0

_DROP_CALLS = 0       # BatchDropCutter.setSTL calls (re-indexes the STL)


def reset_drop_calls():
    global _DROP_CALLS
    _DROP_CALLS = 0


def drop_calls():
    """Number of BatchDropCutter.setSTL calls so far in this process."""
    return _DROP_CALLS


def worker_cap():
    """ENGINE_WORKERS env cap on pool size (default 4)."""
    try:
        return max(1, int(os.environ.get("ENGINE_WORKERS", "4")))
    except ValueError:
        return 4


def resolve_workers(workers):
    """workers None/True -> cpu-2; result capped by worker_cap()."""
    if workers is None or workers is True:
        workers = max(1, (os.cpu_count() or 2) - 2)
    return max(1, min(int(workers), worker_cap()))


def surf_bounds(surf):
    """(xmin, xmax, ymin, ymax, zmin, zmax); ocl getBounds() is a plain list."""
    return tuple(float(v) for v in surf.getBounds())


def make_cutter(kind, dia, corner=0.0):
    if kind == "ball":
        return ocl.BallCutter(dia, BALL_HEIGHT)
    if kind == "bull":
        return ocl.BullCutter(dia, corner, BALL_HEIGHT)
    if kind == "flat":
        return ocl.CylCutter(dia, BALL_HEIGHT)
    raise ValueError("unknown tool kind %r" % kind)


def batch_drop(surf, cutter, xy, threads=None):
    """Drop-cutter a sequence of (x, y). Returns np.array of tip Z (nan =
    no contact). Order-preserving, chunked to bound memory; each chunk is
    one BatchDropCutter.setSTL (counted in drop_calls())."""
    global _DROP_CALLS
    n = len(xy)
    z = np.full(n, np.nan)
    for i0 in range(0, n, DROP_CHUNK):
        _DROP_CALLS += 1
        i1 = min(n, i0 + DROP_CHUNK)
        bd = ocl.BatchDropCutter()
        bd.setSTL(surf)
        bd.setCutter(cutter)
        if threads:
            bd.setThreads(threads)
        for x, y in xy[i0:i1]:
            bd.appendPoint(ocl.CLPoint(float(x), float(y), NO_CONTACT))
        bd.run()
        for k, p in enumerate(bd.getCLPoints()):
            v = float(p.z)
            z[i0 + k] = np.nan if v <= NO_CONTACT / 2.0 else v
    return z


# ---------------------------------------------------------------------------
# Shallow: drop-cutter raster + slope filter
# ---------------------------------------------------------------------------

def _raster_worker(ci):
    """Drop-cutter a contiguous block of raster rows in a fork-pool worker.
    Workers load the STL once and cache it in _POOL (rough.py pattern)."""
    global _DROP_CALLS
    _DROP_CALLS = 0  # count locally, report back to the parent
    g = _POOL
    surf = g.get("surf")
    if surf is None:
        surf = ocl.STLSurf()
        ocl.STLReader(g["stl"], surf)
        g["surf"] = surf
    j0, j1 = g["chunks"][ci]
    z = np.full((j1 - j0, len(g["xrow"])), np.nan)
    for jb in range(j0, j1, g["row_batch"]):
        jj = g["ys"][jb:min(j1, jb + g["row_batch"])]
        xy = [(x, float(y)) for y in jj for x in g["xrow"]]
        zz = batch_drop(surf, make_cutter(*g["tool"]), xy, threads=g["threads"])
        z[jb - j0:jb - j0 + len(jj)] = zz.reshape(len(jj), -1)
    return j0, z, _DROP_CALLS


def raster_cl(surf, cutter, bounds, stepover=0.3, sampling=0.1,
              threads=None, row_batch=64, stl_path=None, workers=None,
              tool=None):
    """CL grid: rows along X spaced `stepover` in Y, sampled at `sampling`.
    Returns (xs, ys, Z) with Z (ny, nx), nan where the cutter touches
    nothing. workers>1 with stl_path: rows split across a fork pool in
    contiguous ordered blocks (deterministic output)."""
    global _DROP_CALLS
    xmin, xmax, ymin, ymax = bounds[:4]
    xs = np.arange(xmin, xmax + 0.5 * sampling, sampling)
    ys = np.arange(ymin, ymax + 0.5 * stepover, stepover)
    Z = np.full((len(ys), len(xs)), np.nan)
    xrow = [float(x) for x in xs]
    if workers and workers > 1 and stl_path and tool is not None:
        nch = min(int(workers), len(ys))
        edges = np.linspace(0, len(ys), nch + 1).astype(int)
        _POOL.update(stl=stl_path, tool=tool, ys=list(map(float, ys)),
                     xrow=xrow, row_batch=row_batch,
                     threads=max(1, (threads or 8) // nch),
                     chunks=[(int(a), int(b)) for a, b in zip(edges[:-1],
                                                              edges[1:])])
        ctx = mp.get_context("fork")
        with ctx.Pool(nch) as pool:
            for j0, zblk, ncalls in pool.map(_raster_worker, range(nch)):
                Z[j0:j0 + zblk.shape[0]] = zblk
                _DROP_CALLS += ncalls  # account worker-local setSTL calls
        return xs, ys, Z
    for j0 in range(0, len(ys), row_batch):
        jj = ys[j0:j0 + row_batch]
        xy = [(x, float(y)) for y in jj for x in xrow]
        z = batch_drop(surf, cutter, xy, threads=threads)
        Z[j0:j0 + len(jj), :] = z.reshape(len(jj), len(xs))
    return xs, ys, Z


def slope_deg(Z, dx, dy):
    """CL-surface slope per grid node in degrees (nan where undefined)."""
    with np.errstate(invalid="ignore"):
        gy, gx = np.gradient(Z, dy, dx)
        return np.degrees(np.arctan(np.hypot(gx, gy)))


def dilate(mask, sx, sy):
    """Binary dilation by sx columns and sy rows (unit = grid spacing)."""
    m = mask.copy()
    for _ in range(sx):
        m[:, 1:] |= m[:, :-1]
        m[:, :-1] |= m[:, 1:]
    for _ in range(sy):
        m[1:, :] |= m[:-1, :]
        m[:-1, :] |= m[1:, :]
    return m


def _runs_of_mask(mask):
    """Maximal True index runs [i0, i1) of a 1-D boolean array."""
    if not mask.any():
        return []
    d = np.diff(mask.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if mask[0]:
        starts = [0] + starts
    if mask[-1]:
        ends = ends + [len(mask)]
    return list(zip(starts, ends))


def shallow_runs(xs, ys, Z, slope, threshold=40.0, overlap_mm=1.0,
                 sampling=0.1, stepover=0.3, max_dz=0.08):
    """Contiguous (x, y, z) runs of shallow CL points per raster row:
    slope < threshold. (S2c: the former overlap_mm dilation band into the
    steep zone is gone - it re-cut the same surface strips as the level
    contours, duplicating shallow rows. The steep pass covers the
    transition: it keeps segments with slope >= threshold - overlap_deg
    at every level.)
    Points adjacent to an along-row CL step > max_dz are dropped and the row
    split there: a 0.1 mm chord spanning such a step bulges below the curved
    CL surface (the offset surface's radius of curvature can drop to ~r/2 at
    contact-branch transitions), and collinear row segments are never
    chord-line-checked. Those flanks belong to the steep pass anyway.
    Returns list of (row_index, i0, i1)."""
    valid = np.isfinite(Z)
    keep = valid & (slope < threshold)
    dzf = np.abs(np.diff(Z, axis=1)) > max_dz  # nan steps -> False
    if dzf.any():
        bad = np.zeros_like(keep)
        bad[:, 1:] |= dzf
        bad[:, :-1] |= dzf
        keep &= ~bad
    runs = []
    for j in range(keep.shape[0]):
        for i0, i1 in _runs_of_mask(keep[j]):
            if i1 - i0 < 2:
                continue
            runs.append((j, i0, i1))
    return runs


# ---------------------------------------------------------------------------
# Steep: AdaptiveWaterline levels + slope filter
# ---------------------------------------------------------------------------

_POOL = {}


def _wl_worker(idx):
    """AdaptiveWaterline for one Z level in a fork-pool worker."""
    g = _POOL
    surf = g.get("surf")
    if surf is None:
        surf = ocl.STLSurf()
        ocl.STLReader(g["stl"], surf)
        g["surf"] = surf
    return _waterline_at(surf, g["levels"][idx], make_cutter(*g["tool"]),
                         g["wl_sampling"], g["wl_min_sampling"])


def _waterline_at(surf, z, cutter, sampling, min_sampling):
    wl = ocl.AdaptiveWaterline()
    wl.setSTL(surf)
    wl.setCutter(cutter)
    wl.setZ(z)
    wl.setSampling(sampling)
    wl.setMinSampling(min_sampling)
    t0 = time.time()
    wl.run()
    loops = [[(float(p.x), float(p.y)) for p in loop]
             for loop in wl.getLoops() if len(loop) >= 2]
    return z, loops, time.time() - t0


def waterline_levels(surf, zs, tool, wl_sampling=0.1, wl_min_sampling=0.05,
                    stl_path=None, workers=None, threads=8):
    """Waterline loops per level: ([(z, [loop[(x, y)], ...]), ...], t_wl)."""
    zs = list(zs)
    if workers and workers > 1 and stl_path:
        _POOL.update(stl=stl_path, levels=zs, tool=tool,
                     wl_sampling=wl_sampling, wl_min_sampling=wl_min_sampling)
        ctx = mp.get_context("fork")
        with ctx.Pool(workers) as pool:
            out = pool.map(_wl_worker, range(len(zs)))
        return [(z, loops) for (z, loops, _) in out], sum(r[2] for r in out)
    cutter = make_cutter(*tool)
    res, t_wl = [], 0.0
    for z in zs:
        z, loops, dt = _waterline_at(surf, z, cutter, wl_sampling,
                                      wl_min_sampling)
        res.append((z, loops))
        t_wl += dt
    return res, t_wl


def steep_slopes(surf, cutter, level_loops, d, threads=None,
                 chunk_pts=20_000):
    """CL-surface slope (deg) at every waterline loop point, from a
    drop-cutter stencil (+-d along x and y). All loops are stencilled in
    batched drop-cutter calls (one per ~chunk_pts loop points, not one per
    loop). Points where the stencil falls off an edge (nan) or the
    waterline sits below the resting CL by > tol are at a CL step
    discontinuity -> treated as steep (kept)."""
    flat = []  # (level_index, z, P) per loop
    for li, (z, loops) in enumerate(level_loops):
        for loop in loops:
            flat.append((li, z, np.asarray(loop, dtype=float)))
    sl_of = [None] * len(flat)
    i = 0
    while i < len(flat):
        j = i
        npts = 0
        while j < len(flat) and npts + len(flat[j][2]) <= chunk_pts:
            npts += len(flat[j][2])
            j += 1
        all_xy = []
        spans = []
        for k in range(i, j):
            _, _, P = flat[k]
            s0 = len(all_xy)
            for x, y in P:
                all_xy += [(x, y), (x + d, y), (x - d, y),
                           (x, y + d), (x, y - d)]
            spans.append((k, s0, len(all_xy)))
        zc_all = batch_drop(surf, cutter, all_xy, threads=threads)
        for (k, s0, s1) in spans:
            _, z, P = flat[k]
            zc = zc_all[s0:s1].reshape(-1, 5)
            z0, zp_x, zn_x, zp_y, zn_y = zc[:, 0], zc[:, 1], zc[:, 2], \
                zc[:, 3], zc[:, 4]
            with np.errstate(invalid="ignore"):
                gx = (zp_x - zn_x) / (2.0 * d)
                gy = (zp_y - zn_y) / (2.0 * d)
            sl = np.degrees(np.arctan(np.hypot(gx, gy)))
            # step discontinuity: resting CL above the waterline level, or
            # the stencil losing contact (edge/overhang) -> steep
            disc = (z0 > z + CHORD_TOL) | ~np.isfinite(sl)
            sl = np.where(disc, 89.9, sl)
            sl_of[k] = (P, sl)
        i = j
    out = []
    for li, (z, loops) in enumerate(level_loops):
        lslopes = [sl_of[k] for k in range(len(flat)) if flat[k][0] == li]
        out.append((z, lslopes))
    return out


def steep_runs(level_slopes, threshold=40.0, overlap_deg=5.0, min_len=0.3):
    """Open (x, y, z) polylines from waterline loops: keep only segments
    whose CL slope >= threshold - overlap_deg. The loop is cyclic in contour
    order, so head+tail kept runs are joined across the seam."""
    lim = threshold - overlap_deg
    out = []
    for z, loop_data in level_slopes:
        for P, sl in loop_data:
            keep = sl >= lim
            if not keep.any():
                continue
            if keep.all():
                runs = [P]  # closed contour: emit as one open polyline
            else:
                # rotate so the sequence starts just after a dropped point:
                # cyclic runs become plain linear runs
                f = int(np.where(~keep)[0][0])
                rot_P = np.roll(P, -f, axis=0)
                rot_k = np.roll(keep, -f)
                runs = [rot_P[i0:i1] for i0, i1 in _runs_of_mask(rot_k)]
            for run in runs:
                if len(run) < 2:
                    continue
                per = float(np.sum(np.hypot(np.diff(run[:, 0]),
                                             np.diff(run[:, 1]))))
                if per < min_len:
                    continue
                out.append((z, run))
    return out


# ---------------------------------------------------------------------------
# PLAN B (task S2): steep passes from a drop-cutter CL grid.
#
# OCL waterlines trace where the ball touches the mesh from ANY side, so raw
# loops sit up to ~r below the drop-cutter CL at overhangs / narrow features
# (S1d items 7-8). Instead: ONE batched drop-cutter CL grid over the steep
# region (dilated by the ball radius), computed once per run; per Z level the
# contour CL(x,y) = Z is extracted by marching squares with {CL >= Z} as the
# material side; every contour point is refined by batched bisection on its
# grid edge (true drop-cutter) until the bracket's XY width <= REFINE_W, and
# the LOW-side endpoint (CL <= Z + KEEP_TOL) is emitted - at CL jumps (real
# walls) that is the jump line at offset r, gouge-safe and touching the wall;
# then a one-sided safety net removes any remaining point below CL - CHORD_TOL
# and splits runs there. Gaps are rejoined only through link_plan (verified
# clear or retract).
# ---------------------------------------------------------------------------

REFINE_W = 0.002      # mm, bisection converges on the bracket's XY width
KEEP_TOL = 0.005      # mm, one-sided keep rule: emit the LOW-side endpoint of
                      # a bracket (CL <= Z + KEEP_TOL). At CL jumps (vertical
                      # walls) the level has no |CL - Z| solution; the jump
                      # line at offset r IS the correct waterline for every
                      # level between floor and top - r, so converging onto the
                      # jump and emitting its safe (air/floor) side is both
                      # gouge-safe and touching the wall. Reject only when no
                      # sign change can be bracketed on the crossing's edge.
FLAT_GAP = 0.05       # mm, min distance of a level from a flat-face Z
FLAT_NZ = 0.995       # normal-z threshold for horizontal (flat) triangles
JUMP_SPAN = 0.1       # mm, CL gap across a converged bracket = discontinuity
JUMP_MARGIN = 0.005   # mm, outward nudge of jump-line points so chords and
                      # check samples between neighbours stay clear side


def flat_face_zs(surf):
    """Z values of upward horizontal triangles (flat faces); levels within
    FLAT_GAP of one are shifted up so no waterline is coplanar with a flat."""
    zs = set()
    for t in surf.getTriangles():
        p = t.getPoints()
        ux, uy, uz = p[1].x - p[0].x, p[1].y - p[0].y, p[1].z - p[0].z
        vx, vy, vz = p[2].x - p[0].x, p[2].y - p[0].y, p[2].z - p[0].z
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        L = math.sqrt(nx * nx + ny * ny + nz * nz)
        if L < 1e-12 or nz / L < FLAT_NZ:
            continue
        z0 = (p[0].z + p[1].z + p[2].z) / 3.0
        zs.add(round(z0, 4))
    return sorted(zs)


def shift_levels(zs, flat_zs, gap=FLAT_GAP):
    """Levels within `gap` of a flat-face Z move up to flat_z + gap;
    duplicates removed, order top-down preserved."""
    fz = np.asarray(flat_zs, dtype=float)
    out = []
    for z in zs:
        zz = float(z)
        if len(fz):
            k = int(np.searchsorted(fz, zz))
            for j in (k - 1, k):
                if 0 <= j < len(fz) and abs(zz - fz[j]) < gap:
                    zz = float(fz[j]) + gap
        out.append(zz)
    return sorted(set(round(z, 6) for z in out), reverse=True)


def grid_sample(A, x0, y0, sp, X, Y):
    """Bilinear sample of grid A (ny, nx) at physical points (X, Y); nan
    where out of range or any contributing corner is nan."""
    fx = (np.asarray(X, dtype=float) - x0) / sp
    fy = (np.asarray(Y, dtype=float) - y0) / sp
    ny, nx = A.shape
    i = np.floor(fx).astype(int)
    j = np.floor(fy).astype(int)
    ok = (i >= 0) & (i < nx - 1) & (j >= 0) & (j < ny - 1)
    i = np.clip(i, 0, nx - 2)
    j = np.clip(j, 0, ny - 2)
    tx = fx - i
    ty = fy - j
    a00 = A[j, i]
    a10 = A[j, i + 1]
    a01 = A[j + 1, i]
    a11 = A[j + 1, i + 1]
    v = (a00 * (1 - tx) + a10 * tx) * (1 - ty) \
        + (a01 * (1 - tx) + a11 * tx) * ty
    return np.where(ok, v, np.nan)


def cl_grid(surf, cutter, xs, ys, mask, threads=None):
    """Drop-cutter CL (tip Z) at every masked node of the square grid
    xs x ys; nan outside the mask or with no contact."""
    Zg = np.full((len(ys), len(xs)), np.nan)
    idx = np.argwhere(mask)
    if len(idx) == 0:
        return Zg
    xy = [(float(xs[i]), float(ys[j])) for j, i in idx]
    Zg[idx[:, 0], idx[:, 1]] = batch_drop(surf, cutter, xy, threads=threads)
    return Zg


def march_level(Zg, xs, ys, z, comp=None):
    """Marching-squares iso-contour of Zg at level z; material side is
    {CL >= z}. Computed-but-no-contact nodes (nan in Zg) count as -inf: air
    is below every level, so contours exist at CL jumps into air (outer
    walls, slot edges) - the jump line at offset r, which is the correct
    waterline for every level between floor and top - r. Nodes not in comp
    (not computed) make their cells invalid. Returns list of (P(n, 2),
    closed); closed loops repeat no endpoint (cyclic in contour order)."""
    ninf = -1e30
    Zc = np.where(np.isfinite(Zg), Zg, ninf)
    if comp is None:
        comp = np.isfinite(Zg)
    v00 = Zc[:-1, :-1]
    v10 = Zc[:-1, 1:]   # bottom-right
    v01 = Zc[1:, :-1]    # top-left
    v11 = Zc[1:, 1:]
    valid = comp[:-1, :-1] & comp[:-1, 1:] & comp[1:, :-1] & comp[1:, 1:]
    case = ((v00 >= z).astype(np.int8) + (v10 >= z).astype(np.int8) * 2
            + (v01 >= z).astype(np.int8) * 4 + (v11 >= z).astype(np.int8) * 8)
    cells = np.argwhere(valid & (case > 0) & (case < 15))
    if len(cells) == 0:
        return []
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    segs = []           # [keyA, keyB, pAx, pAy, pBx, pBy]
    adj = {}
    for jc, ic in cells:
        j, i = int(jc), int(ic)
        b00, b10, b01, b11 = float(v00[j, i]), float(v10[j, i]), \
            float(v01[j, i]), float(v11[j, i])
        cr = []  # crossings in order B, R, T, L: (key, x, y)
        d = b10 - b00
        if (b00 >= z) != (b10 >= z) and abs(d) > 1e-12:
            t = (z - b00) / d
            cr.append((('h', i, j), xs[i] + t * dx, ys[j]))
        d = b11 - b10
        if (b10 >= z) != (b11 >= z) and abs(d) > 1e-12:
            t = (z - b10) / d
            cr.append((('v', i + 1, j), xs[i + 1], ys[j] + t * dy))
        d = b11 - b01
        if (b01 >= z) != (b11 >= z) and abs(d) > 1e-12:
            t = (z - b01) / d
            cr.append((('h', i, j + 1), xs[i] + t * dx, ys[j + 1]))
        d = b01 - b00
        if (b00 >= z) != (b01 >= z) and abs(d) > 1e-12:
            t = (z - b00) / d
            cr.append((('v', i, j), xs[i], ys[j] + t * dy))
        if len(cr) == 2:
            pairs = [(0, 1)]
        elif len(cr) == 4:
            pairs = [(0, 3), (1, 2)]  # fixed saddle resolution
        else:
            continue
        for (a, b) in pairs:
            ka, xa, ya = cr[a]
            kb, xb, yb = cr[b]
            si = len(segs)
            segs.append((ka, kb, xa, ya, xb, yb))
            adj.setdefault(ka, []).append((si, 0))
            adj.setdefault(kb, []).append((si, 1))
    n = len(segs)
    seen = [False] * n
    out = []
    for si in range(n):
        if seen[si]:
            continue
        seen[si] = True
        ka, kb, xa, ya, xb, yb = segs[si]
        back = []
        k = ka
        while True:
            cand = [(s, e) for (s, e) in adj[k] if not seen[s]]
            if not cand:
                break
            s, e = cand[0]
            seen[s] = True
            if e == 0:
                back.append((segs[s][0], segs[s][2], segs[s][3]))
                k = segs[s][1]
            else:
                back.append((segs[s][1], segs[s][4], segs[s][5]))
                k = segs[s][0]
        fwd = []
        k = kb
        while True:
            cand = [(s, e) for (s, e) in adj[k] if not seen[s]]
            if not cand:
                break
            s, e = cand[0]
            seen[s] = True
            if e == 0:
                fwd.append((segs[s][0], segs[s][2], segs[s][3]))
                k = segs[s][1]
            else:
                fwd.append((segs[s][1], segs[s][4], segs[s][5]))
                k = segs[s][0]
        pts = back[::-1] + [(ka, xa, ya), (kb, xb, yb)] + fwd
        K = [p[0] for p in pts]
        P = np.asarray([(p[1], p[2]) for p in pts], dtype=float)
        closed = len(P) > 2 and float(np.hypot(*(P[0] - P[-1]))) < 1e-9
        if closed:
            P = P[:-1]
            K = K[:-1]
        out.append((P, closed, K))
    return out


def refine_contours(surf, cutter, loops, Zg, x0, y0, sp,
                    width_tol=REFINE_W, rounds=8, threads=None):
    """Refine every contour point by batched bisection on its marching-
    squares grid edge (loops = [(z, P(n,2), keys(n), closed)], keys are the
    march_level crossing edge ids): the two nodes bracketing the crossing
    (one CL >= Z,
    the other < Z) form a bracket; each round halves it with ONE batch_drop
    over all still-active points of all levels, moving the material-side
    endpoint to the midpoint when CL(mid) >= Z and the low-side endpoint
    otherwise. Convergence is on the bracket's XY WIDTH <= width_tol, NOT on
    |CL - Z|: at a CL jump (vertical wall) the level has no |CL - Z|
    solution, yet bisection converges onto the jump line at offset r, which
    is the correct waterline for every level between floor and top - r. The
    LOW-side endpoint is emitted (its CL <= Z + KEEP_TOL): gouge-safe and
    touching the wall. A point is rejected (ok == False) only when no sign
    change can be bracketed on its edge (both nodes >= Z, or contact lost).
    Returns [(z, pos(n,2), cl(n), ok(n), closed)]; cl is the true
    drop-cutter CL at pos for every emitted point.
    """
    if not loops:
        return []
    Zall = np.concatenate([np.full(len(P), z) for (z, P, _K, _) in loops])
    XY = np.concatenate([P for (z, P, _K, _) in loops])
    KEYS = [k for (_z, _P, K, _c) in loops for k in K]
    n = len(XY)
    # each crossing's grid edge key gives its two node indices directly:
    # ('h', i, j) = horizontal edge between nodes (j, i) and (j, i + 1);
    # ('v', i, j) = vertical edge between nodes (j, i) and (j + 1, i).
    typ = np.array([k[0] for k in KEYS])
    i = np.array([k[1] for k in KEYS], dtype=int)
    j = np.array([k[2] for k in KEYS], dtype=int)
    horiz = typ == 'h'
    i2 = np.where(horiz, i + 1, i)
    j2 = np.where(horiz, j, j + 1)
    # nodes of valid crossing cells are computed; nan there = air (-inf)
    Zf = np.where(np.isfinite(Zg), Zg, -1e30)
    va = Zf[j, i]
    vb = Zf[j2, i2]
    axy = np.stack([x0 + i * sp + np.zeros(n),
                   y0 + j * sp + np.zeros(n)], axis=1)
    bxy = np.stack([x0 + i2 * sp + np.zeros(n),
                   y0 + j2 * sp + np.zeros(n)], axis=1)
    # lo = air/floor-side endpoint (CL < Z), hi = material-side (CL >= Z)
    a_low = va < Zall                      # b is the low side when va >= Z
    lo = np.where(a_low[:, None], axy, bxy)
    hi = np.where(a_low[:, None], bxy, axy)
    lo_cl = np.where(a_low, va, vb)
    hi_ok = np.where(a_low, vb, va)   # material-side node value (may be nan)
    fin_hi = np.isfinite(hi_ok)
    # lo_cl may be -inf (no contact = air: nothing to gouge, never >= Z)
    bracketed = fin_hi & (hi_ok >= Zall) & (lo_cl < Zall)
    # unbracketed: keep the crossing position; the one-sided ok test below
    # removes it unless its own CL is already safe (both nodes < Z case)
    cl = np.where(np.isfinite(lo_cl), lo_cl, np.nan)  # -inf (air) -> nan
    active = bracketed & (np.hypot(hi[:, 0] - lo[:, 0],
                                   hi[:, 1] - lo[:, 1]) > width_tol)
    for r in range(rounds):
        ai = np.where(active)[0]
        if len(ai) == 0:
            break
        mid = 0.5 * (lo[ai] + hi[ai])
        zc = batch_drop(surf, cutter, [tuple(p) for p in mid],
                        threads=threads)
        up = np.isfinite(zc) & (zc >= Zall[ai])   # midpoint on material side
        hi[ai[up]] = mid[up]
        lo[ai[~up]] = mid[~up]                    # air/floor side (nan -> air)
        lo_cl[ai[~up]] = zc[~up]
        w = np.hypot(hi[ai, 0] - lo[ai, 0], hi[ai, 1] - lo[ai, 1])
        active[ai[w <= width_tol]] = False
    # jump detection: after convergence the bracket is <= width_tol wide; a
    # CL difference > JUMP_SPAN across it means a CL discontinuity (wall).
    # Nudge such points outward (air/floor side) by JUMP_MARGIN so chords and
    # check samples between neighbours cannot dip across the jump into CL > Z.
    bi = np.where(bracketed)[0]
    if len(bi):
        zh = batch_drop(surf, cutter, [tuple(p) for p in hi[bi]],
                        threads=threads)
        jump = (np.isfinite(zh) & (zh - lo_cl[bi] > JUMP_SPAN)) \
            | ~np.isfinite(lo_cl[bi])
        sel = bi[jump]
        if len(sel):
            dxu = lo[sel, 0] - hi[sel, 0]
            dyu = lo[sel, 1] - hi[sel, 1]
            Lw = np.hypot(dxu, dyu)
            Lw[Lw < 1e-9] = 1.0
            lo[sel, 0] += dxu / Lw * JUMP_MARGIN
            lo[sel, 1] += dyu / Lw * JUMP_MARGIN
    pos = np.where(bracketed[:, None], lo, XY)  # emit low-side endpoint
    cl = np.where(bracketed, lo_cl, cl)
    # nan cl = no contact = air: nothing to gouge at any Z
    ok = ~np.isfinite(cl) | (cl <= Zall + KEEP_TOL)
    out = []
    off = 0
    for (z, P, _K, closed) in loops:
        m = len(P)
        out.append((z, pos[off:off + m].copy(), cl[off:off + m],
                    ok[off:off + m], closed))
        off += m
    return out


def steep_runs_grid(refined, slopeA, x0, y0, sp, threshold=40.0,
                    overlap_deg=5.0, min_len=0.3):
    """Open (z, run(n,2)) polylines from refined contours: drop violators
    (ok == False) and split runs there, keep segments whose CL slope from the
    grid >= threshold - overlap_deg (nan slope = CL step -> steep). Closed
    loops join kept runs across the seam. Returns (runs, n_removed)."""
    lim = threshold - overlap_deg
    out = []
    n_removed = 0
    for (z, P, cl, ok, closed) in refined:
        n_removed += int((~ok).sum())
        sl = grid_sample(slopeA, x0, y0, sp, P[:, 0], P[:, 1])
        steep = (sl >= lim) | ~np.isfinite(sl)
        keep = ok & steep
        if not keep.any():
            continue
        if keep.all():
            runs = [P]
        elif closed:
            f = int(np.where(~keep)[0][0])
            rot = np.roll(keep, -f)
            runs = [np.roll(P, -f, axis=0)[i0:i1]
                    for i0, i1 in _runs_of_mask(rot)]
        else:
            runs = [P[i0:i1] for i0, i1 in _runs_of_mask(keep)]
        for run in runs:
            if len(run) < 2:
                continue
            per = float(np.sum(np.hypot(np.diff(run[:, 0]),
                                         np.diff(run[:, 1]))))
            if per < min_len:
                continue
            out.append((z, run))
    return out, n_removed


def segment_net(surf, cutter, runs, ss=0.1, tol=CHORD_TOL, threads=None):
    """Final safety net: one-sided check of every segment's interior samples
    (CL - z <= tol) of the emitted steep runs, all samples in one batched
    drop-cutter call. A violating segment SPLITS the run there (never
    bridged at cutting depth; the pieces are rejoined only through the
    verified link logic). Returns (runs, n_splits)."""
    if not runs:
        return runs, 0
    xy = []
    spans = []  # per run: list of (s0, s1) sample spans per segment
    for (z, P) in runs:
        seg = []
        for k in range(len(P) - 1):
            L = math.hypot(P[k + 1, 0] - P[k, 0], P[k + 1, 1] - P[k, 1])
            m = int(math.ceil(L / ss))
            # even m -> the k/(m+1) grid includes t = 0.5: the worst chord
            # point against a ball-corner tangent circle is the midpoint, and
            # micron-scale tangent slivers must not depend on sample phase
            if m % 2:
                m += 1
            s0 = len(xy)
            if m > 0:
                t = np.arange(1, m + 1) / (m + 1)
                xy.extend(zip(P[k, 0] + (P[k + 1, 0] - P[k, 0]) * t,
                             P[k, 1] + (P[k + 1, 1] - P[k, 1]) * t))
            seg.append((s0, len(xy)))
        spans.append(seg)
    zc = batch_drop(surf, cutter, xy, threads=threads) if xy \
        else np.zeros(0)
    out = []
    n_splits = 0
    for (z, P), seg in zip(runs, spans):
        bad = np.zeros(max(0, len(P) - 1), dtype=bool)
        for k, (s0, s1) in enumerate(seg):
            if s1 <= s0:
                continue
            m = s1 - s0
            t = np.arange(1, m + 1) / (m + 1)
            lz = np.full(m, z)  # steep segments lie at the level Z
            cz = zc[s0:s1]
            fin = np.isfinite(cz)
            if fin.any() and float(np.max(cz[fin] - lz[fin])) > tol:
                bad[k] = True
        n_splits += int(bad.sum())
        for i0, i1 in _runs_of_mask(~bad):  # runs of ok segments
            if i1 <= i0:
                continue
            out.append((z, P[i0:i1 + 1]))
    return out, n_splits


# ---------------------------------------------------------------------------
# Gouge-safe simplification + links
# ---------------------------------------------------------------------------

class Chords:
    """One-sided gouge-safe chord checks for one polyline.

    A vertex is dropped only if the straight chord between its kept
    neighbours stays >= CL - tol at every sample under the chord, where the
    samples are (a) the polyline vertices and interior extras every `ss` mm
    along the curve, and (b) - when the curve deviates from the chord by >
    1e-6 (convex corners: the chord cuts across where CL rises) -
    drop-cutter points every `line_ss` mm along the chord line ITSELF.
    (b) matters because gouge-freeness of a cutter position depends on CL
    at the chord's own xy, which near corners is far above CL on the
    sampled curve. Chords are capped at `max_chord` mm; chords between
    adjacent original vertices are never line-checked (their deviation is
    second order in the sampling, << tol). Simplification runs in
    verify-and-split rounds over many polylines: see simplify_rounds.
    """

    def __init__(self, P, ss=0.05, line_ss=0.1):
        self.P = np.asarray(P, dtype=float)          # (n, 3) on the CL
        self.line_ss = line_ss
        if len(self.P) > 1 and ss > 0:
            ex, seg = [], []
            d = np.diff(self.P[:, :2], axis=0)
            L = np.hypot(d[:, 0], d[:, 1])
            m = np.maximum(1, np.ceil(L / ss).astype(int))
            for i in range(len(self.P) - 1):
                if m[i] > 1:
                    t = np.arange(1, m[i]) / m[i]
                    ex.append(np.stack([self.P[i, 0] + d[i, 0] * t,
                                        self.P[i, 1] + d[i, 1] * t], axis=1))
                    seg.append(np.full(len(t), i, dtype=int))
            if ex:
                self.ex_y = np.concatenate(ex, axis=0)
                self.ex_seg = np.concatenate(seg)
            else:
                self.ex_y = np.zeros((0, 2))
                self.ex_seg = np.zeros(0, dtype=int)
        else:
            self.ex_y = np.zeros((0, 2))
            self.ex_seg = np.zeros(0, dtype=int)
        self.ex_z = None

    def line_samples(self, a, b):
        """((x, y) samples every line_ss strictly between P[a] and P[b],
        their t along the chord) for the chord-line check, or None when the
        curve is collinear with the chord (straight raster rows: the vertex
        CL samples already sit on the chord) or the chord is too short."""
        P = self.P
        dx = P[b, 0] - P[a, 0]
        dy = P[b, 1] - P[a, 1]
        L = math.hypot(dx, dy)
        if L <= self.line_ss:
            return None
        ux, uy = dx / L, dy / L
        Q = P[a + 1:b, :2]
        dev = float(np.max(np.abs((Q[:, 0] - P[a, 0]) * uy
                                  - (Q[:, 1] - P[a, 1]) * ux)))
        if len(self.ex_y):
            msk = (self.ex_seg >= a) & (self.ex_seg < b)
            if msk.any():
                E = self.ex_y[msk]
                dev = max(dev, float(np.max(
                    np.abs((E[:, 0] - P[a, 0]) * uy
                           - (E[:, 1] - P[a, 1]) * ux))))
        if dev <= 1e-6:
            return None
        m = int(math.ceil(L / self.line_ss)) + 1
        # odd m -> interior samples j/(m-1) include t = 0.5 (worst point of
        # a chord against a ball-corner tangent circle; see segment_net)
        if m % 2 == 0:
            m += 1
        tl = np.linspace(0.0, 1.0, m)[1:-1]
        return [(P[a, 0] + dx * s, P[a, 1] + dy * s) for s in tl], tl

    def propose(self, tol=CHORD_TOL, max_chord=5.0):
        """Cheap pass (NO drop-cutter): greedy from the start, checks only
        the vertex and curve samples against the chord. Returns
        (keep_idx, chords) where chords = [(a, b), ...] pairs of
        consecutive kept indices that skip >= 1 vertex (those need the
        batched chord-line check of simplify_rounds)."""
        P = self.P
        n = len(P)
        if n <= 2:
            return list(range(n)), []
        keep_idx = [0]
        a = 0
        while a < n - 1:
            last_ok = None
            b = a + 2
            while b < n:
                dx = P[b, 0] - P[a, 0]
                dy = P[b, 1] - P[a, 1]
                L2 = dx * dx + dy * dy
                if math.sqrt(L2) > max_chord or L2 <= 1e-12:
                    break  # too long, or zero-length chord (duplicate xy)
                # samples strictly between a and b: vertices a+1..b-1
                ok = True
                if b > a + 1:
                    zc = P[a, 2] + (P[b, 2] - P[a, 2]) * \
                        ((P[a + 1:b, 0] - P[a, 0]) * dx +
                         (P[a + 1:b, 1] - P[a, 1]) * dy) / L2
                    if float(np.max(np.abs(zc - P[a + 1:b, 2]))) > tol:
                        ok = False
                if ok and self.ex_z is not None and len(self.ex_z):
                    msk = (self.ex_seg >= a) & (self.ex_seg < b)
                    if msk.any():
                        sx = self.ex_y[msk, 0] - P[a, 0]
                        sy = self.ex_y[msk, 1] - P[a, 1]
                        t = (sx * dx + sy * dy) / L2
                        zc = P[a, 2] + (P[b, 2] - P[a, 2]) * t
                        dz = zc - self.ex_z[msk]
                        if np.isfinite(dz).any():
                            bad = float(np.nanmax(np.abs(dz)))
                            if bad > tol:
                                ok = False
                        # all-air samples (nan CL): nothing to cut, no constraint
                if not ok:
                    break
                last_ok = b
                b += 1
            keep_idx.append(last_ok if last_ok is not None else a + 1)
            a = keep_idx[-1]
        chords = [(keep_idx[i], keep_idx[i + 1])
                  for i in range(len(keep_idx) - 1)
                  if keep_idx[i + 1] > keep_idx[i] + 1]
        return keep_idx, chords


def simplify_rounds(chords_list, surf, cutter, threads=None, tol=CHORD_TOL,
                    max_chord=5.0, max_rounds=16):
    """Gouge-safe simplification of many polylines in verify-and-split
    rounds (O(rounds) batched drop-cutter calls, not O(chords)): each
    Chords.propose suggests kept vertices cheaply, then ALL proposed
    chords' chord-line samples are checked in ONE batch_drop call per
    round; a failing chord is split by re-inserting the skipped vertex
    nearest the worst sample, and only the resulting halves are re-checked
    in the next single call. If the round cap is hit with failures still
    open, those chords keep every original vertex (safe: the remaining
    chords are between adjacent vertices and never line-checked). Returns
    (kept per polyline as [(x, y, z), ...] in input order, n_rounds,
    n_chords_checked)."""
    inserted = [set() for _ in chords_list]
    keep_idxs = []
    active = []  # [ci, a, b, (samples_xy, ts)]
    for ci, c in enumerate(chords_list):
        keep_idx, chs = c.propose(tol=tol, max_chord=max_chord)
        keep_idxs.append(keep_idx)
        for (a, b) in chs:
            ls = c.line_samples(a, b)
            if ls is not None:
                active.append([ci, a, b, ls])
    n_chords = len(active)
    n_rounds = 0
    while active and n_rounds < max_rounds:
        n_rounds += 1
        xy = []
        spans = []
        for _, _, _, (s, _) in active:
            s0 = len(xy)
            xy.extend(s)
            spans.append((s0, len(xy)))
        z = batch_drop(surf, cutter, xy, threads=threads) if xy \
            else np.zeros(0)
        nxt = []
        for (ci, a, b, (s, ts)), (s0, s1) in zip(active, spans):
            P = chords_list[ci].P
            dx = P[b, 0] - P[a, 0]
            dy = P[b, 1] - P[a, 1]
            cz = z[s0:s1]
            zc = P[a, 2] + (P[b, 2] - P[a, 2]) * ts
            fin = np.isfinite(cz)
            if not (fin.any() and float(np.max(
                    np.abs(cz[fin] - zc[fin]))) > tol):
                continue  # chord verified gouge-safe
            dev = np.where(fin, np.abs(cz - zc), 0.0)
            jw = int(np.argmax(dev))
            wx = P[a, 0] + dx * ts[jw]
            wy = P[a, 1] + dy * ts[jw]
            idx = np.arange(a + 1, b)
            d2 = (P[idx, 0] - wx) ** 2 + (P[idx, 1] - wy) ** 2
            m = int(idx[int(np.argmin(d2))])
            inserted[ci].add(m)
            c = chords_list[ci]
            for (na, nb) in ((a, m), (m, b)):
                if nb > na + 1:
                    ls2 = c.line_samples(na, nb)
                    if ls2 is not None:
                        nxt.append([ci, na, nb, ls2])
        active = nxt
    if active:  # round cap with failures open -> keep all original vertices
        for ci, a, b, _ in active:
            inserted[ci].update(range(a + 1, b))
    out = []
    for ci, c in enumerate(chords_list):
        ki = sorted(set(keep_idxs[ci]) | inserted[ci])
        out.append([(float(c.P[i, 0]), float(c.P[i, 1]), float(c.P[i, 2]))
                    for i in ki])
    return out, n_rounds, n_chords


def vertex_net(surf, cutter, paths, tol=NET_TOL, threads=None):
    """Final safety net on the emitted vertices themselves: check every
    path vertex at its ROUNDED (4-decimal) position - the coordinate that
    actually goes to the machine. CL can jump by millimetres across a
    ball-catch boundary (distance = r from a convex vertical corner edge),
    and quantisation may flip a just-safe point to the unsafe side, so the
    check must run after rounding, not before. One batched drop-cutter call;
    violators are removed and paths split there (never lowered, never
    bridged - the pieces rejoin only through the verified link logic).
    Returns (rounded paths, src index of the input path each output came
    from - splits keep input order, n_removed)."""
    if not paths:
        return [], [], 0
    rpth = [[tuple(round(float(v), 4) for v in p) for p in pth]
            for pth in paths if len(pth) >= 2]
    src_in = [i for i, pth in enumerate(paths) if len(pth) >= 2]
    if not rpth:
        return [], [], 0
    xy = [(p[0], p[1]) for pth in rpth for p in pth]
    cl = batch_drop(surf, cutter, xy, threads=threads)
    out = []
    src = []
    n = 0
    off = 0
    for si, pth in enumerate(rpth):
        m = len(pth)
        c = cl[off:off + m]
        off += m
        zarr = np.array([p[2] for p in pth])
        ok = ~np.isfinite(c) | (c - zarr <= tol)
        n += int((~ok).sum())
        for i0, i1 in _runs_of_mask(ok):
            if i1 - i0 >= 2:
                out.append(pth[i0:i1])
                src.append(src_in[si])
    return out, src, n


def box_max(A, k):
    """Max filter over a (2k+1) square window per axis (nan = -inf);
    conservative superset of a ball-radius footprint max."""
    m = np.where(np.isfinite(A), A, -np.inf).astype(float)
    for _ in range(k):
        m[1:, :] = np.maximum(m[1:, :], m[:-1, :])
        m[:-1, :] = np.maximum(m[:-1, :], m[1:, :])
        m[:, 1:] = np.maximum(m[:, 1:], m[:, :-1])
        m[:, :-1] = np.maximum(m[:, :-1], m[:, 1:])
    return m


def link_plan(surf, cutter, links, sampling=0.1, threads=None,
              rapid_margin=RAPID_MARGIN, clearance=None, use_rapids=True,
              stock=None, stock_allow=RAPID_STOCK_ALLOW):
    """For each ((x0,y0,z0), (x1,y1,z1)) decide 'down', 'rapid' or 'lift'.
    - 'down': stay at cutting height - drop-cutter CL along the link stays
      below the link line (one-sided, no tolerance).
    - 'rapid' (S3 item 1): retract to the MINIMUM verified-clear height
      z_r = max(CL along path) + rapid_margin + stock_allow (G0 across,
      plunge at ramp feed). Verified by drop-cutter along the swept XY path
      (sampled <= RAPID_LINK_SS mm, batched): z_r >= CL + rapid_margin for
      the whole path; the extra stock_allow covers the roughing leftover
      stock above the part when NO stock model is given (the CL is computed
      on the part, not a stock model). The ball's full footprint is covered
      by drop-cutter: at tip z > CL(x, y) the ball touches nothing at that
      xy. If `stock` = (A, x0, y0, cell) heightfield is given (post-roughing
      stock via --stock-from, or the rest pass leftover), the rapid must
      additionally clear it: z_r >= max(stock within a ball-radius box
      around the path) + rapid_margin (S3b: rapids clear the ROUGHING
      STOCK, not just the part; the height is never clamped below this
      requirement - `clearance` only caps heights that stay above it).
    - 'lift': the verified feed link (retract to local max CL + LINK_LIFT,
      traverse at ramp feed) - used when use_rapids is off; with a stock
      model the lift height must clear the stock the same way (S3b).
    Returns [(mode, height_or_None, local_max_cl_or_None), ...]."""
    if not links:
        return []
    ss = min(sampling, RAPID_LINK_SS)
    xy, spans = [], []
    for (a, b) in links:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        m = max(2, int(math.ceil(L / ss))) + 1
        # odd m -> linspace includes t = 0.5 (tangent-sliver phase safety)
        if m % 2 == 0:
            m += 1
        s0 = len(xy)
        for t in np.linspace(0.0, 1.0, m):
            xy.append((a[0] + (b[0] - a[0]) * t,
                       a[1] + (b[1] - a[1]) * t))
        spans.append((s0, len(xy)))
    z = batch_drop(surf, cutter, xy, threads=threads)
    smax = None
    if stock is not None:
        A, sx0, sy0, cell = stock
        sv = grid_sample(A, sx0, sy0, cell,
                        np.array([p[0] for p in xy]),
                        np.array([p[1] for p in xy]))
    out = []
    for li, ((a, b), (s0, s1)) in enumerate(zip(links, spans)):
        cz = z[s0:s1]
        fin = np.isfinite(cz)
        hi = -np.inf
        if stock is not None:
            svl = sv[s0:s1]
            if np.isfinite(svl).any():
                hi = float(np.max(svl))  # stock within ball reach of path
        if not fin.any():
            if hi > -np.inf and use_rapids:
                # all part-air but stock stands under the path: S3b - the
                # rapid must clear it; never clamp below that requirement
                out.append(("rapid", hi + rapid_margin, None))
            else:
                out.append(("down", None, None))  # all air along the path
            continue
        mx = float(np.max(cz[fin]))
        ts = np.linspace(0.0, 1.0, s1 - s0)
        link_z = a[2] + (b[2] - a[2]) * ts
        if float(np.max(cz[fin] - link_z[fin])) <= 1e-9:
            out.append(("down", None, None))
        elif use_rapids:
            # S3b: z_r >= max(CL along path, stock within tool radius along
            # path) + margin; `clearance` only caps heights already above it
            zr = max(mx + rapid_margin + stock_allow, hi + rapid_margin)
            out.append(("rapid", zr, mx))
        else:
            # feed lift: with a stock model the traverse must clear it too
            out.append(("lift", max(mx + LINK_LIFT, hi + rapid_margin), mx))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def load_heightfield(path):
    """Load a heightfield .npy (+ sidecar .json with x0/y0/cell, the
    engine/zmap convention) -> (A, x0, y0, cell)."""
    stem = path[:-4] if path.endswith(".npy") else path
    A = np.load(stem + ".npy")
    with open(stem + ".json") as fh:
        meta = json.load(fh)
    return A, float(meta["x0"]), float(meta["y0"]), float(meta["cell"])


def compute_rest_mask(surf, xs, ys, big_tool=("ball", 6.0, 0.0),
                     small_tool=("ball", 3.0, 0.0), min_rest=0.5,
                     stock=None, threads=None):
    """Leftover map for the corner rest pass (S3 item 3), computed from the
    engine's OWN drop-cutter CL only (no verify/zmap import): a cell is rest
    material where the 6 mm ball's machined surface (its CL tip height, the
    surface point directly under the centre) sits more than `min_rest` above
    what the 3 mm ball reaches:

        CL_big - CL_small > min_rest

    The part lies at or below CL_small wherever the small ball has contact,
    so this implies CL_big - part > min_rest (the 6 mm ball left more than
    min_rest above the part). If `stock` = (A, x0, y0, cell) is given (the
    post-roughing stock .npy or a previous op's zmap heightfield), cells must
    additionally have stock - CL_small > min_rest, i.e. real material left to
    remove down to the small ball's cut. Returns a bool array (len(ys),
    len(xs))."""
    X, Y = np.meshgrid(xs, ys)
    xy = list(zip(X.ravel().tolist(), Y.ravel().tolist()))
    clb = batch_drop(surf, make_cutter(*big_tool), xy,
                    threads=threads).reshape(X.shape)
    cls = batch_drop(surf, make_cutter(*small_tool), xy,
                    threads=threads).reshape(X.shape)
    mask = np.isfinite(clb) & np.isfinite(cls) & (clb - cls > min_rest)
    if stock is not None:
        A, sx0, sy0, cell = stock
        s = grid_sample(A, sx0, sy0, cell, X, Y)
        mask &= np.isfinite(s) & (s - cls > min_rest)
    return mask


def finish(surf, stl_path=None, tool=("ball", 6.0, 0.0), stepover=0.3,
           sampling=0.1, slope_threshold=40.0, overlap_mm=1.0,
           stepdown=0.3, overlap_deg=5.0, floor_z=None, wl_sampling=0.2,
           wl_min_sampling=0.1, max_chord=5.0, cut_feed=3429.0,
           ramp_feed=1270.0, clearance=None, workers=None, threads=8,
           window=None, progress=None, rapid_margin=RAPID_MARGIN,
           use_rapids=True, rest_from=None, big_tool=("ball", 6.0, 0.0),
           min_rest=0.5, stock_from=None, stock_allow=RAPID_STOCK_ALLOW):
    """Slope-split finishing toolpath (action: slope_split_finish).
    Returns (moves, stats).

    workers: pool size for raster rows (capped by the ENGINE_WORKERS env,
    default 4); output order stays deterministic.
    wl_sampling / wl_min_sampling: legacy (OCL waterline, task S1); unused by
    the PLAN B grid contours.
    overlap_mm: legacy (S1 overlap band); unused since S2c - the band
    duplicated cutting of the steep transition zone.
    window: (xmin, xmax, ymin, ymax) - restrict the raster and the steep CL
    grid (smoke tests).
    rapid_margin / use_rapids: verified-clear G0 links (S3 item 1).
    rest_from: path to a stock/zmap heightfield .npy (+ .json sidecar):
    corner rest pass (S3 item 3) - cut only where the big_tool's CL surface
    exceeds the small-ball reach by > min_rest (see compute_rest_mask); the
    tool in `tool` is then a PLACEHOLDER until it joins tools/x7_tools.json.
    stock_from: path to the roughing stock heightfield .npy (+ sidecar,
    engine.cli rough --stock-out): verified rapid/lift heights must clear
    max(CL along the swept path, stock within the tool radius) + margin
    (S3b). Conservative: the INITIAL stock is used for every link (cuts
    only lower it). Without stock_from, rapids add `stock_allow` (default
    1.0 mm) on top of CL + margin to cover the roughing leftover.
    """
    t_start = time.time()
    reset_drop_calls()
    cutter = make_cutter(*tool)
    workers = resolve_workers(workers)
    xmin, xmax, ymin, ymax, zmin, zmax = surf_bounds(surf)
    if floor_z is None:
        floor_z = zmin
    if clearance is None:
        clearance = zmax + 2.0
    window = tuple(float(v) for v in window) if window else None

    # -- shallow raster (CL grid + slope) --------------------------------
    rxmin, rxmax = xmin, xmax
    rymin, rymax = ymin, ymax
    if window:
        rxmin, rxmax = max(xmin, window[0]), min(xmax, window[1])
        rymin, rymax = max(ymin, window[2]), min(ymax, window[3])
    t0 = time.time()
    xs, ys, Z = raster_cl(surf, cutter, (rxmin, rxmax, rymin, rymax),
                          stepover=stepover, sampling=sampling,
                          threads=threads, stl_path=stl_path, workers=workers,
                          tool=tool)
    t_raster = time.time() - t0
    slope = slope_deg(Z, xs[1] - xs[0], ys[1] - ys[0])
    # rest pass (S3 item 3): restrict the CL grid to leftover cells before
    # the slope split - shallow rows and the steep core then exist only
    # where the big ball left > min_rest above the small-ball reach.
    rest_mask = None
    rest_stock = None
    n_rest_cells = 0
    if rest_from is not None:
        stock = load_heightfield(rest_from)
        rest_stock = stock
        rest_mask = compute_rest_mask(surf, xs, ys, big_tool=big_tool,
                                     small_tool=tool, min_rest=min_rest,
                                     stock=stock, threads=threads)
        n_rest_cells = int(rest_mask.sum())
        Z = np.where(rest_mask, Z, np.nan)
    s_runs = shallow_runs(xs, ys, Z, slope, threshold=slope_threshold,
                          overlap_mm=overlap_mm, sampling=sampling,
                          stepover=stepover)

    # -- steep: drop-cutter CL grid + marching-squares contours -------
    # with a window, only levels where the CL inside the window actually
    # exists can produce contours touching it: bound the range coarsely.
    t0 = time.time()
    ztop, zbot = zmax, floor_z
    if window:
        wxs = np.arange(rxmin + 0.5, rxmax, 0.5)
        wys = np.arange(rymin + 0.5, rymax, 0.5)
        wxy = [(float(x), float(y)) for y in wys for x in wxs]
        wz = batch_drop(surf, cutter, wxy, threads=threads)
        finw = np.isfinite(wz)
        ztop = min(zmax, float(np.max(wz[finw])) + 1.0)
        zbot = max(floor_z, float(np.min(wz[finw])) - 1.0)
    zs = np.arange(ztop - stepdown, zbot - 1e-9, -stepdown)
    if len(zs) == 0 or abs(zs[-1] - zbot) > 1e-9:
        zs = np.append(zs, zbot)
    zs = shift_levels(zs, flat_face_zs(surf))

    sp = sampling  # square CL grid pitch in steep regions (0.1 mm)
    r_mm = 0.5 * tool[1] + 1.0
    # extend past the region bbox by the ball radius so CL DESCENTS exist at
    # outer walls (walls at the stock edge drop into air: without the pad the
    # CL stays >= every level on the grid and no contour can be bracketed).
    gxs = np.arange(rxmin - r_mm, rxmax + r_mm + 0.5 * sp, sp)
    gys = np.arange(rymin - r_mm, rymax + r_mm + 0.5 * sp, sp)
    # steep mask: raster CL-surface slope >= lim, dilated by ball radius
    # + 1 mm so contours of every kept wall lie inside the dropped region.
    lim = slope_threshold - overlap_deg
    core = np.isfinite(Z) & (slope >= lim)
    gmask = dilate(core, int(math.ceil(r_mm / sampling)),
                   int(math.ceil(r_mm / stepover)))[np.ix_(
        np.clip(np.round((gys - ys[0]) / stepover).astype(int), 0,
                len(ys) - 1),
        np.clip(np.round((gxs - xs[0]) / sampling).astype(int), 0,
                len(xs) - 1))]
    # the pad frame outside the region bbox must be COMPUTED (its nan then
    # means true air, giving real contact boundaries at outer walls; leaving
    # it uncomputed would put fake jumps at the mask edge)
    gmask[:, (gxs > rxmax) | (gxs < rxmin)] = True
    gmask[(gys > rymax) | (gys < rymin), :] = True
    Zg = cl_grid(surf, cutter, gxs, gys, gmask, threads=threads)
    with np.errstate(invalid="ignore"):
        gyA, gxA = np.gradient(Zg, sp, sp)
    slopeA = np.degrees(np.arctan(np.hypot(gxA, gyA)))

    contours = []
    for z in zs:
        for (P, closed, K) in march_level(Zg, gxs, gys, z, comp=gmask):
            if len(P) >= 2:
                contours.append((z, P, K, closed))
    # batched bracket bisection on the grid edges (true drop-cutter), width
    # <= REFINE_W; low-side endpoint emitted at CL jumps
    refined = refine_contours(surf, cutter, contours, Zg, gxs[0],
                              gys[0], sp, threads=threads)
    lvl_stat = {}
    for (z, P, cl, ok, closed) in refined:
        e = lvl_stat.setdefault(z, [0, 0])
        e[0] += len(P)
        e[1] += int((~ok).sum())
    # slope split + remove points still below CL (runs split at removals)
    st_runs, n_steep_removed = steep_runs_grid(
        refined, slopeA, gxs[0], gys[0], sp, threshold=slope_threshold,
        overlap_deg=overlap_deg)
    # final one-sided net on segment interiors: split, never bridge
    st_runs, n_seg_splits = segment_net(surf, cutter, st_runs, ss=sampling,
                                        tol=NET_TOL, threads=threads)
    t_grid = time.time() - t0
    t_steep = time.time() - t0

    # -- gouge-safe simplification ---------------------------------------
    t0 = time.time()
    # steep runs: every point is a refined drop-cutter CL point at its own
    # xy (violators already removed); chords only need the shared rounds.
    chords = []
    for (z, run) in st_runs:
        P = np.stack([run[:, 0], run[:, 1], np.full(len(run), z)], axis=1)
        chords.append(Chords(P, ss=0.5 * sampling))
    ex_parts = [c.ex_y for c in chords if len(c.ex_y)]
    if ex_parts:
        all_ex = np.concatenate(ex_parts, axis=0)
        all_z = batch_drop(surf, cutter, [tuple(p) for p in all_ex],
                           threads=threads)
        off = 0
        for c in chords:
            m = len(c.ex_y)
            if m:
                c.ex_z = all_z[off:off + m]
                off += m
    # verify-and-split rounds: ALL chord-line samples per round in ONE
    # batched drop-cutter call (O(rounds) setSTL calls, not O(chords))
    steep_paths, n_rounds_steep, n_chords = simplify_rounds(
        chords, surf, cutter, threads=threads, tol=NET_TOL,
        max_chord=max_chord)
    # shallow rows: vertices ARE the 0.1 mm CL samples - no extras needed;
    # rows are collinear so the rounds make zero drop-cutter calls
    shallow_chords = []
    row_of_pre = []
    for (j, i0, i1) in s_runs:
        P = np.stack([xs[i0:i1], np.full(i1 - i0, ys[j]),
                     Z[j, i0:i1]], axis=1)
        shallow_chords.append(Chords(P, ss=0.0))
        row_of_pre.append(j)
    shallow_paths, n_rounds_shallow, n_chords_sh = simplify_rounds(
        shallow_chords, surf, cutter, threads=threads, tol=NET_TOL,
        max_chord=max_chord)
    # final one-sided net at the emitted (4-decimal rounded) coordinates:
    # rounding across a CL discontinuity (ball-catch circle at convex
    # vertical corners) must not leave an unsafe vertex in the output.
    steep_paths, _src_steep, n_vn_steep = vertex_net(surf, cutter,
                                                     steep_paths,
                                                     threads=threads)
    shallow_paths, src_shallow, n_vn_shallow = vertex_net(
        surf, cutter, shallow_paths, threads=threads)
    # row / run index per EMITTED path (vertex_net splits runs, so the
    # pre-net row_of / s_runs indices no longer align with k)
    row_of = [row_of_pre[s] for s in src_shallow]
    run_i0 = [s_runs[s][1] for s in src_shallow]
    t_simplify = time.time() - t0

    # -- order the paths: steep top-down, then shallow rows -----------
    order = list(range(len(steep_paths)))
    order.sort(key=lambda k: (-steep_paths[k][0][2], steep_paths[k][0][1],
                              steep_paths[k][0][0]))
    ordered = [steep_paths[k] for k in order]
    # serpentine shallow rows: reverse alternate rows so consecutive rows
    # connect at the SAME X end with a short stepover link. Without this,
    # every row transition re-traversed the full row length at cutting
    # height (a "down" link's horizontal component), duplicating shallow
    # raster rows many times over (S2c: 11,749 long rows for ~550).
    shallow_order = sorted(range(len(shallow_paths)),
                          key=lambda k: (row_of[k],
                                       run_i0[k] if row_of[k] % 2 == 0
                                       else -run_i0[k]))
    for k in shallow_order:
        p = shallow_paths[k]
        ordered.append(p if row_of[k] % 2 == 0 else p[::-1])

    # -- links -----------------------------------------------------------
    t0 = time.time()
    links = []
    for a, b in zip(ordered, ordered[1:]):
        links.append((a[-1], b[0]))
    # rapids must clear the STOCK too (ball-radius box max along the path):
    # S3b --stock-from = post-roughing stock heightfield, or the rest pass
    # leftover map (leftover ridges stand far above the part). Conservative:
    # the INITIAL stock is used for every link (finishing cuts only lower it).
    stock_arg = None
    link_stock = None
    if stock_from is not None:
        link_stock = load_heightfield(stock_from)
    elif rest_stock is not None:
        link_stock = rest_stock
    if link_stock is not None:
        A, sx0, sy0, cell = link_stock
        r_px = int(math.ceil(0.5 * tool[1] / cell))
        i0 = max(0, int((xs[0] - sx0) / cell) - r_px)
        i1 = min(A.shape[1], int((xs[-1] - sx0) / cell) + r_px + 1)
        j0 = max(0, int((ys[0] - sy0) / cell) - r_px)
        j1 = min(A.shape[0], int((ys[-1] - sy0) / cell) + r_px + 1)
        if i1 > i0 and j1 > j0:
            stock_arg = (box_max(A[j0:j1, i0:i1], r_px),
                        sx0 + i0 * cell, sy0 + j0 * cell, cell)
    lplan = link_plan(surf, cutter, links, sampling=sampling,
                      threads=threads, rapid_margin=rapid_margin,
                      clearance=clearance, use_rapids=use_rapids,
                      stock=stock_arg, stock_allow=stock_allow)
    t_link = time.time() - t0

    # -- emit -------------------------------------------------------------
    moves = []
    stats = {"n_steep_runs": len(steep_paths), "n_shallow_runs": len(shallow_paths),
             "n_steep_pts": int(sum(len(p) for p in steep_paths)),
             "n_shallow_pts": int(sum(len(p) for p in shallow_paths)),
             "n_steep_removed": n_steep_removed, "n_seg_splits": n_seg_splits,
             "t_raster_s": round(t_raster, 1), "t_steep_s": round(t_steep, 1),
             "t_grid_s": round(t_grid, 1),
             "t_simplify_s": round(t_simplify, 1),
             "t_link_s": round(t_link, 1),
             "n_lifts": 0, "cut_len": 0.0, "plunge_len": 0.0,
             "rapid_len": 0.0,
             # S3 item 1: rapid vs feed link counts and lengths
             "n_rapid_links": 0, "n_feed_links": 0, "n_lift_links": 0,
             "rapid_link_len": 0.0, "feed_link_len": 0.0,
             "levels": sorted((round(z, 3) for z in lvl_stat), reverse=True),
             "levels_detail": [[round(z, 3), v[0], v[1]]
                              for z, v in sorted(lvl_stat.items(),
                                                key=lambda kv: -kv[0])]}
    stats["n_drop_calls"] = drop_calls()
    stats["n_simplify_rounds"] = n_rounds_steep + n_rounds_shallow
    stats["n_chords_checked"] = n_chords + n_chords_sh
    if rest_from is not None:
        # S3 item 3: placeholder tool - the LNC post must refuse this tool
        # (not in tools/x7_tools.json); never add it to the table.
        stats["rest_pass"] = True
        stats["placeholder_tool"] = True
        stats["rest_from"] = str(rest_from)
        stats["big_tool"] = "ball:%.1f" % big_tool[1]
        stats["min_rest_mm"] = min_rest
        stats["n_rest_cells"] = n_rest_cells
    if stock_from is not None:
        # S3b: rapids/lifts verified against this post-roughing stock model
        stats["stock_from"] = str(stock_from)
        stats["stock_allow_mm"] = stock_allow
    prev = None

    def emit(g, x, y, z, f=None, stat=None):
        nonlocal prev
        if prev is not None and math.dist(prev, (x, y, z)) <= 1e-9:
            return  # skip zero-length moves (down-link with bz == pz)
        if prev is not None:
            L = math.dist(prev, (x, y, z))
            if g == 0 or stat == "rapid":
                # horizontal travel at a verified lift height (>= local max
                # CL + 1 mm) is repositioning, not cutting (S2c: counting it
                # as cut inflated cut_len ~40% on the synthetic shapes)
                stats["rapid_len"] += L
            elif abs(z - prev[2]) > 1e-6:
                stats["plunge_len"] += L
            else:
                stats["cut_len"] += L
        moves.append({"g": g, "x": round(x, 4), "y": round(y, 4),
                      "z": round(z, 4), "f": f})
        prev = (x, y, z)

    for k, path in enumerate(ordered):
        if not path:
            continue
        if prev is None:
            emit(0, path[0][0], path[0][1], clearance)
            emit(1, path[0][0], path[0][1], path[0][2], ramp_feed)
        else:
            mode, lift_z, _ = lplan[k - 1] if k - 1 < len(lplan) else \
                ("lift", clearance, None)
            if mode == "down":
                # split the diagonal link into horizontal + vertical: safe
                # both ways (descending: horizontal at the old height is
                # above the verified diagonal, then a drop to CL at the new
                # xy; ascending: rise at the old xy above its CL, then
                # horizontal at the new height, above the diagonal). Keeps
                # plunge_len = real Z travel instead of the whole diagonal.
                px, py, pz = prev
                bx, by, bz = path[0][0], path[0][1], path[0][2]
                stats["n_feed_links"] += 1
                stats["feed_link_len"] += math.hypot(bx - px, by - py)
                if bz <= pz:
                    emit(1, bx, by, pz, cut_feed)
                    emit(1, bx, by, bz, cut_feed)
                else:
                    emit(1, px, py, bz, cut_feed)
                    emit(1, bx, by, bz, cut_feed)
            elif mode == "rapid":
                # S3 item 1: retract to the minimum verified-clear height,
                # G0 across, plunge at ramp feed.
                stats["n_lifts"] += 1
                stats["n_rapid_links"] += 1
                stats["rapid_link_len"] += math.hypot(path[0][0] - prev[0],
                                                     path[0][1] - prev[1])
                if abs(lift_z - prev[2]) > 1e-9:
                    emit(1, prev[0], prev[1], lift_z, ramp_feed)
                emit(0, path[0][0], path[0][1], lift_z)
                emit(1, path[0][0], path[0][1], path[0][2], ramp_feed)
            else:
                stats["n_lifts"] += 1
                stats["n_lift_links"] += 1
                stats["feed_link_len"] += math.hypot(path[0][0] - prev[0],
                                                    path[0][1] - prev[1])
                emit(1, prev[0], prev[1], lift_z, ramp_feed)
                emit(1, path[0][0], path[0][1], lift_z, ramp_feed,
                     stat="rapid")
                emit(1, path[0][0], path[0][1], path[0][2], ramp_feed)
        for (x, y, z) in path[1:]:
            emit(1, x, y, z, cut_feed)
    if prev is not None:
        emit(0, prev[0], prev[1], clearance)

    stats["cut_len"] = round(stats["cut_len"], 1)
    stats["plunge_len"] = round(stats["plunge_len"], 1)
    stats["rapid_len"] = round(stats["rapid_len"], 1)
    stats["rapid_link_len"] = round(stats["rapid_link_len"], 1)
    stats["feed_link_len"] = round(stats["feed_link_len"], 1)
    stats["t_total_s"] = round(time.time() - t_start, 1)
    if progress:
        progress(stats)
    return moves, stats


def finish_to_gcode(moves, spindle_rpm=7500, tool_comment=None):
    """Same neutral move list as engine.gcode.moves_to_gcode, finished label."""
    out = ["G21", "G90", "G94", "G17"]
    if tool_comment:
        out.append("(%s)" % tool_comment)
    out.append("(ENGINE FINISH SLOPE-SPLIT)")
    out.append("S%d M3" % spindle_rpm)
    for mv in moves:
        bits = []
        if mv.get("x") is not None:
            bits.append("X%.4f" % mv["x"])
        if mv.get("y") is not None:
            bits.append("Y%.4f" % mv["y"])
        if mv.get("z") is not None:
            bits.append("Z%.4f" % mv["z"])
        if mv["g"] == 0:
            out.append("G0 " + " ".join(bits))
        else:
            if mv.get("f"):
                bits.append("F%.0f" % mv["f"])
            out.append("G1 " + " ".join(bits))
    top = max((m["z"] for m in moves if m.get("z") is not None
               and m["g"] == 0), default=5.0)
    out.append("G0 Z%.4f" % top)
    out.append("M5")
    out.append("M30")
    return "\n".join(out) + "\n"
