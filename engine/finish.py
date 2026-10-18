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
(default 40 deg) dilated by a 1 mm overlap band into the steep zone.
Steep: AdaptiveWaterline at Z levels from part top down to the floor,
stepdown default 0.3 mm; keep loop segments where the CL slope (same grid)
>= threshold - overlap_deg. Waterline points are exact ball centres at the
level Z (OCL rolls the ball), so steep runs cannot sit below the CL.
Links: stay down only if drop-cutter along the link stays below the link;
otherwise retract to local max CL + 1 mm.

moves are the neutral dicts of engine/gcode.py: {g:0|1, x, y, z, f}.
"""
import math
import multiprocessing as mp
import os
import time

import numpy as np
from opencamlib import ocl

CHORD_TOL = 0.005     # mm, one-sided gouge-safe chord tolerance
LINK_LIFT = 1.0       # mm above local max CL when a link is blocked
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
                 sampling=0.1, stepover=0.3):
    """Contiguous (x, y, z) runs of shallow CL points per raster row:
    slope < threshold plus an overlap_mm band dilated into the steep zone.
    Returns list of (row_index, i0, i1)."""
    valid = np.isfinite(Z)
    core = valid & (slope < threshold)
    keep = core | (dilate(core, int(math.ceil(overlap_mm / sampling)),
                           int(math.ceil(overlap_mm / stepover))) & valid)
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
                if math.sqrt(L2) > max_chord:
                    break
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
                        with np.errstate(invalid="ignore"):
                            bad = float(np.nanmax(np.abs(zc - self.ex_z[msk])))
                        if bad > tol:
                            ok = False
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


def link_plan(surf, cutter, links, sampling=0.1, threads=None):
    """For each ((x0,y0,z0), (x1,y1,z1)) decide 'down' or 'lift'.
    Stay down only if drop-cutter CL along the link stays below the link
    (one-sided, no tolerance); else lift to local max CL + LINK_LIFT.
    Returns [(mode, lift_z_or_None, local_max_cl_or_None), ...]."""
    if not links:
        return []
    xy, spans = [], []
    for (a, b) in links:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        m = max(2, int(math.ceil(L / sampling))) + 1
        s0 = len(xy)
        for t in np.linspace(0.0, 1.0, m):
            xy.append((a[0] + (b[0] - a[0]) * t,
                       a[1] + (b[1] - a[1]) * t))
        spans.append((s0, len(xy)))
    z = batch_drop(surf, cutter, xy, threads=threads)
    out = []
    for (a, b), (s0, s1) in zip(links, spans):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        ts = np.linspace(0.0, 1.0, s1 - s0)
        link_z = a[2] + (b[2] - a[2]) * ts
        cz = z[s0:s1]
        fin = np.isfinite(cz)
        if not fin.any() or float(np.max(cz[fin] - link_z[fin])) <= 1e-9:
            out.append(("down", None, None))
        else:
            out.append(("lift", float(np.max(cz[fin])) + LINK_LIFT,
                        float(np.max(cz[fin]))))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def finish(surf, stl_path=None, tool=("ball", 6.0, 0.0), stepover=0.3,
           sampling=0.1, slope_threshold=40.0, overlap_mm=1.0,
           stepdown=0.3, overlap_deg=5.0, floor_z=None, wl_sampling=0.2,
           wl_min_sampling=0.1, max_chord=5.0, cut_feed=3429.0,
           ramp_feed=1270.0, clearance=None, workers=None, threads=8,
           window=None, progress=None):
    """Slope-split finishing toolpath (action: slope_split_finish).
    Returns (moves, stats).

    workers: pool size for raster rows + waterline levels (capped by the
    ENGINE_WORKERS env, default 4); output order stays deterministic.
    window: (xmin, xmax, ymin, ymax) - restrict the raster and keep only
    waterline loops that touch the window (smoke tests)."""
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
    s_runs = shallow_runs(xs, ys, Z, slope, threshold=slope_threshold,
                          overlap_mm=overlap_mm, sampling=sampling,
                          stepover=stepover)

    # -- steep waterline levels ------------------------------------------
    # with a window, only levels where the CL inside the window actually
    # exists can produce loops touching it: bound the range coarsely.
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
    t0 = time.time()
    levels, t_wl = waterline_levels(surf, zs, tool, wl_sampling=wl_sampling,
                                    wl_min_sampling=wl_min_sampling,
                                    stl_path=stl_path, workers=workers,
                                    threads=threads)
    levels.sort(key=lambda r: -r[0])
    if window:
        m = 2.0 * wl_sampling
        levels = [(z, [lp for lp in loops if any(
            rxmin - m <= px <= rxmax + m and rymin - m <= py <= rymax + m
            for px, py in lp)])
                  for z, loops in levels]
    lslopes = steep_slopes(surf, cutter, levels, stepover, threads=threads)
    st_runs = steep_runs(lslopes, threshold=slope_threshold,
                         overlap_deg=overlap_deg)
    t_steep = time.time() - t0

    # -- gouge-safe simplification ---------------------------------------
    t0 = time.time()
    # steep runs: ocl AdaptiveWaterline is approximate near tangencies -
    # validate every loop point against the true drop-cutter CL and lift
    # points that sit below it (a cutter position is gouge-free iff its
    # tip z >= CL at its own xy). Extras need real drop-cutter samples;
    # batch them all once.
    chords = []
    all_pts = [(float(x), float(y)) for (_, run) in st_runs
               for (x, y) in run[:, :2]]
    cl_all = batch_drop(surf, cutter, all_pts, threads=threads)
    off = 0
    n_wl_lift = 0
    n_cl_nan = 0
    for (z, run) in st_runs:
        m = len(run)
        cl = cl_all[off:off + m]
        off += m
        # ocl drop-cutter returns nan at points just off the contact
        # cylinder (tangency edge) while neighbours land on it; at a
        # no-contact xy every z is gouge-free, so fill nan with the run's
        # max CL to keep the run flat (a level-z sawtooth would plunge
        # 5-7 mm every ~0.2 mm along vertical walls).
        if not np.isfinite(cl).all():
            n_cl_nan += int((~np.isfinite(cl)).sum())
            cl = np.where(np.isfinite(cl), cl,
                          np.nanmax(cl) if np.isfinite(cl).any() else z)
        need = np.isfinite(cl) & (cl > z + CHORD_TOL)
        n_wl_lift += int(need.sum())
        P = np.stack([run[:, 0], run[:, 1], np.where(need, cl, z)], axis=1)
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
        chords, surf, cutter, threads=threads, max_chord=max_chord)
    # shallow rows: vertices ARE the 0.1 mm CL samples - no extras needed;
    # rows are collinear so the rounds make zero drop-cutter calls
    shallow_chords = []
    row_of = []
    for (j, i0, i1) in s_runs:
        P = np.stack([xs[i0:i1], np.full(i1 - i0, ys[j]),
                     Z[j, i0:i1]], axis=1)
        shallow_chords.append(Chords(P, ss=0.0))
        row_of.append(j)
    shallow_paths, n_rounds_shallow, n_chords_sh = simplify_rounds(
        shallow_chords, surf, cutter, threads=threads, max_chord=max_chord)
    t_simplify = time.time() - t0

    # -- order the paths: steep top-down, then shallow rows -----------
    order = list(range(len(steep_paths)))
    order.sort(key=lambda k: (-steep_paths[k][0][2], steep_paths[k][0][1],
                              steep_paths[k][0][0]))
    ordered = [steep_paths[k] for k in order]
    shallow_order = sorted(range(len(shallow_paths)), key=lambda k: row_of[k])
    ordered += [shallow_paths[k] for k in shallow_order]

    # -- links -----------------------------------------------------------
    t0 = time.time()
    links = []
    for a, b in zip(ordered, ordered[1:]):
        links.append((a[-1], b[0]))
    lplan = link_plan(surf, cutter, links, sampling=sampling,
                      threads=threads)
    t_link = time.time() - t0

    # -- emit -------------------------------------------------------------
    moves = []
    stats = {"n_steep_runs": len(steep_paths), "n_shallow_runs": len(shallow_paths),
             "n_steep_pts": int(sum(len(p) for p in steep_paths)),
             "n_shallow_pts": int(sum(len(p) for p in shallow_paths)),
             "n_wl_lifted": n_wl_lift, "n_cl_nan_filled": n_cl_nan,
             "t_raster_s": round(t_raster, 1), "t_steep_s": round(t_steep, 1),
             "t_waterline_s": round(t_wl, 1),
             "t_simplify_s": round(t_simplify, 1),
             "t_link_s": round(t_link, 1),
             "n_lifts": 0, "cut_len": 0.0, "plunge_len": 0.0,
             "rapid_len": 0.0, "levels": [round(z, 3) for z, lp in levels
                                           if lp]}
    stats["n_drop_calls"] = drop_calls()
    stats["n_simplify_rounds"] = n_rounds_steep + n_rounds_shallow
    stats["n_chords_checked"] = n_chords + n_chords_sh
    prev = None

    def emit(g, x, y, z, f=None):
        nonlocal prev
        if prev is not None:
            L = math.dist(prev, (x, y, z))
            if g == 0:
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
                if bz <= pz:
                    emit(1, bx, by, pz, cut_feed)
                    emit(1, bx, by, bz, cut_feed)
                else:
                    emit(1, px, py, bz, cut_feed)
                    emit(1, bx, by, bz, cut_feed)
            else:
                stats["n_lifts"] += 1
                emit(1, prev[0], prev[1], lift_z, ramp_feed)
                emit(1, path[0][0], path[0][1], lift_z, ramp_feed)
                emit(1, path[0][0], path[0][1], path[0][2], ramp_feed)
        for (x, y, z) in path[1:]:
            emit(1, x, y, z, cut_feed)
    if prev is not None:
        emit(0, prev[0], prev[1], clearance)

    stats["cut_len"] = round(stats["cut_len"], 1)
    stats["plunge_len"] = round(stats["plunge_len"], 1)
    stats["rapid_len"] = round(stats["rapid_len"], 1)
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
