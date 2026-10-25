"""2.5D adaptive roughing: per-level islands from a batched drop-cutter CL
grid with the ACTUAL cutter (diameter + 2x radial allowance) + area.Adaptive2d,
rest-aware via the engine's own stock heightfield (engine/stock.py).

R2 (safety-critical): islands NEVER come from ocl Waterline/AdaptiveWaterline.
OCL waterlines under-cover at fillet-meets-vertical-corner geometry (test
block: level 29.906 path at (-17.56, 13.87) ran 3.72 mm below true CL beside
the boss R8 corner where the R3 top fillet starts). Instead, per level Z:
  * ONE drop-cutter CL grid with the big cutter (Cyl/Bull, radius
    tool_r + leave) is computed once per run (CL does not depend on Z);
  * forbidden-for-centers region F(Z) = {CL > Z - axial_leave}; its boundary
    is extracted by marching squares (finish.march_level) and refined by
    batched bisection against the true drop-cutter (finish.refine_contours)
    to < 0.005 mm, emitting the AIR-side bracket endpoint: the loop rounds
    OUTWARD, so F is never under-covered;
  * Adaptive2d geometry gets the raster-eroded contour Em = F (-) disk(R -
    margin) (margin covers grid quantisation + Adaptive2d tolerance), so the
    centres Adaptive2d emits at offset tool_r + leave stay outside F;
  * the refined (authoritative) F loops drive the ground-truth oracle
    isl_ok, path clipping and the hard allowance post-check;
  * an independent CLCHECK gate (engine/probe_rough_clcheck, separate code
    path) re-drops the ACTUAL cutter on every cutting move at the end of
    rough() and fails the run on any tip below CL + axial_leave - 0.005.

Boundary convention (proven in engine/test_engine.py + probe_g_stockregion):
  area.Adaptive2d offsets every loop (stock boundary, holes, islands) by
  tool_radius + stockToLeave, in cutter-centre space. So per level we feed:
  * stock paths (Execute arg 1) = marching-squares contours of the region
    that still needs machining at this level (stock top > Z + axial leave,
    >= ~1 mm above the part), dilated by tool_r + leave (+0.5 mm margin) so
    centres reach the actual stock-region edge and can enter from open sides;
  * geometry = those outers + holes (cleared pockets inside stock) + the
    level's Em island loops (see above).

Levels (Task G): big stepdowns of `stepdown` from the stock top down to the
final Z, and after each big level a climb grid: levels every `stepup` mm
UPWARD from it, clipped at runtime to where the stock model still shows
material (area >= min_level_area). This replaces the old full-area
intermediate/flat levels. Task R2 item 3: every up-facing flat floor F of the
part (STL flat-face Zs) additionally gets a MANDATORY level at F + axial
leave that the rest/skip logic can never drop (min_rest relaxed to 0 there).

Links: between paths/regions we stay tool-down when the stock model says the
straight link at cutting Z (or Z + lift) is clear; only then do we retract to
clearance and helix/plunge. The hard radial-allowance post-check from round 6
still runs per level.

R4 (quality): Adaptive2d's island input is F eroded by (R - margin), so its
centres stay ~margin outside the true forbidden region and a full-height band
+ corner chunks survived below it (test block Z27 pocket: 142 mm2 of floor at
8.38 mm, of which only ~20% is the unreachable R6 crescent). Per level we now
emit wall-hugging rings (hug_regions): the refined (authoritative) island
loops offset eps toward the allowed side, filtered by this level's territory
and isl_ok - centres hug the walls at the closest distance the hard gates
permit, and disk(r_t) cuts the band down to the level's Z, leaving only the
analytic corner crescents. Two latent link bugs surfaced and were fixed with
it: corridor sampling now also tests segment midpoints (a thin island tip can
slip between 0.4 mm samples), and after a clip break the tool re-enters via
the corridor-checked entry instead of diving across the forbidden gap; a flat
level already in the step-up order (the final floor+axl level) keeps its
mandatory flag so it can never be skipped.
"""
import math
import os
import time

import numpy as np
from opencamlib import ocl
import area

from engine import finish as fin
from engine.stock import StockField, save_stock_npy

# SE2: noise floor (same value/name as verify/zmap.py's AXIAL_FLOOR); a side
# entry's feed-in may only cross material already cleared at that level.
AXIAL_FLOOR = 0.2


def rect_loop(xmin, ymin, xmax, ymax):
    return [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]]


def decimate(pts, min_d):
    """Drop consecutive points closer than min_d; keep the loop closed-safe."""
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= min_d:
            out.append(p)
    if len(out) > 2 and math.hypot(out[0][0] - out[-1][0],
                                   out[0][1] - out[-1][1]) < min_d:
        out.pop()
    return out


def big_cutter(tool_r, leave, corner_r=0.0):
    """The island cutter: the actual roughing cutter grown by the radial
    allowance on every side (diameter + 2x leave), same kind (Cyl for flat,
    Bull for bull)."""
    dia = 2.0 * (tool_r + leave)
    if corner_r and corner_r > 1e-9:
        return ocl.BullCutter(dia, corner_r, 50.0)
    return ocl.CylCutter(dia, 50.0)


def actual_cutter(tool_r, corner_r=0.0):
    """The roughing cutter itself (for the CLCHECK gate)."""
    if corner_r and corner_r > 1e-9:
        return ocl.BullCutter(2.0 * tool_r, corner_r, 50.0)
    return ocl.CylCutter(2.0 * tool_r, 50.0)


def cl_island_grid(surf, cutter, xmin, ymin, xmax, ymax, pitch, threads=None):
    """One batched drop-cutter CL grid (tip Z of the BIG cutter) on a square
    grid covering [xmin..xmax] x [ymin..ymax]; nan = no contact (air).
    Computed once per run: the CL surface does not depend on the level Z."""
    xs = np.arange(xmin, xmax + 0.5 * pitch, pitch)
    ys = np.arange(ymin, ymax + 0.5 * pitch, pitch)
    xy = [(float(x), float(y)) for y in ys for x in xs]
    Z = fin.batch_drop(surf, cutter, xy, threads=threads)
    return xs, ys, Z.reshape(len(ys), len(xs))


def _disk_offsets(radius, pitch):
    k = int(math.ceil(radius / pitch))
    return [(dj, di) for dj in range(-k, k + 1) for di in range(-k, k + 1)
            if (dj * dj + di * di) * pitch * pitch <= radius * radius]


def _erode(mask, radius, pitch):
    """Binary erosion by a disk of `radius` (shift-AND)."""
    out = np.ones_like(mask, dtype=bool)
    for dj, di in _disk_offsets(radius, pitch):
        j0, j1 = max(0, dj), min(mask.shape[0], mask.shape[0] + dj)
        i0, i1 = max(0, di), min(mask.shape[1], mask.shape[1] + di)
        out[j0:j1, i0:i1] &= mask[j0 - dj:j1 - dj, i0 - di:i1 - di]
    return out


def _ccw(loops):
    """Orient loops CCW (positive signed area)."""
    out = []
    for lp in loops:
        a2 = sum(lp[i][0] * lp[(i + 1) % len(lp)][1]
                 - lp[(i + 1) % len(lp)][0] * lp[i][1] for i in range(len(lp)))
        out.append(lp if a2 > 0 else lp[::-1])
    return out


def _contour_circuits(Zg, xs, ys, level, comp=None):
    """Closed contours of Zg at `level` (material side {CL >= level}, nan =
    -inf/air, cells with uncomputed nodes invalid). Crossing edges and the
    fixed saddle pairing follow finish.march_level, but the loop stitching is
    a full Hierholzer Euler-circuit extraction: march_level's greedy two-way
    walk can drop edges / split a contour into cycle + dangling tail when the
    boundary self-touches at diagonal mask contacts, which breaks the island
    guard. Returns [(xy list, key list, closed)]."""
    ninf = -1e30
    Zc = np.where(np.isfinite(Zg), Zg, ninf)
    if comp is None:
        comp = np.isfinite(Zg)
    v00 = Zc[:-1, :-1]   # (X=i, Y=j)
    v10 = Zc[:-1, 1:]    # (X=i+1, Y=j)
    v01 = Zc[1:, :-1]    # (X=i, Y=j+1)
    v11 = Zc[1:, 1:]     # (X=i+1, Y=j+1)
    valid = comp[:-1, :-1] & comp[:-1, 1:] & comp[1:, :-1] & comp[1:, 1:]
    case = ((v00 >= level).astype(np.int8) + (v10 >= level).astype(np.int8) * 2
            + (v01 >= level).astype(np.int8) * 4
            + (v11 >= level).astype(np.int8) * 8)
    cells = np.argwhere(valid & (case > 0) & (case < 15))
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    E = []
    for jc, ic in cells:
        j, i = int(jc), int(ic)   # j = Y row index, i = X col (Zg[row=y, col=x])
        b00, b10, b01, b11 = float(v00[j, i]), float(v10[j, i]), \
            float(v01[j, i]), float(v11[j, i])
        m00, m10, m01, m11 = b00 >= level, b10 >= level, \
            b01 >= level, b11 >= level
        if m00 == m10 == m01 == m11:
            continue
        cr = []  # crossings in order B, R, T, L: (key, x, y)
        d = b10 - b00
        if m00 != m10 and abs(d) > 1e-12:
            t = (level - b00) / d
            cr.append((('h', i, j), xs[i] + t * dx, ys[j]))
        d = b11 - b10
        if m10 != m11 and abs(d) > 1e-12:
            t = (level - b10) / d
            cr.append((('v', i + 1, j), xs[i + 1], ys[j] + t * dy))
        d = b11 - b01
        if m01 != m11 and abs(d) > 1e-12:
            t = (level - b01) / d
            cr.append((('h', i, j + 1), xs[i] + t * dx, ys[j + 1]))
        d = b01 - b00
        if m00 != m01 and abs(d) > 1e-12:
            t = (level - b00) / d
            cr.append((('v', i, j), xs[i], ys[j] + t * dy))
        if len(cr) == 2:
            pairs = [(0, 1)]
        elif len(cr) == 4:
            pairs = [(0, 3), (1, 2)]  # fixed saddle resolution (as march)
        else:
            continue
        for (a, b) in pairs:
            E.append((cr[a][0], cr[b][0],
                     (float(cr[a][1]), float(cr[a][2])),
                     (float(cr[b][1]), float(cr[b][2]))))
    return _euler_circuits(E)


def _euler_circuits(E, tol=1e-6):
    """Group crossing edges E=(ka,kb,pa,pb) into Eulerian circuits (one per
    connected component; open trails when degrees are odd). Keys map to their
    crossing point consistently, so circuits close exactly."""
    from collections import defaultdict
    adj = defaultdict(list)
    for ei, (a, b, _pa, _pb) in enumerate(E):
        adj[a].append(ei)
        adj[b].append(ei)
    used = [False] * len(E)
    out = []
    for s in range(len(E)):
        if used[s]:
            continue
        used[s] = True
        ka, kb, pa, pb = E[s]
        stack = [(ka, pa), (kb, pb)]   # (key, point on arrival)
        circuit = []
        ck = []
        while stack:
            v, p = stack[-1]
            nxt = None
            lst = adj[v]
            while lst:
                ei = lst.pop()
                if not used[ei]:
                    used[ei] = True
                    a, b, pqa, pqb = E[ei]
                    w, wp = (b, pqb) if a == v else (a, pqa)
                    nxt = (w, wp)
                    break
            if nxt is None:
                circuit.append(p)
                ck.append(v)
                stack.pop()
            else:
                stack.append(nxt)
        circuit.reverse()
        ck.reverse()
        closed = len(circuit) > 2 and math.dist(circuit[0], circuit[-1]) < tol
        if closed:
            circuit = circuit[:-1]
            ck = ck[:-1]
        out.append((circuit, ck, closed))
    return out


def _loops_from_mask(mask, xs, ys, min_perimeter=4.0):
    """Closed marching-squares contours of a boolean raster, CCW, decimated
    and rounded."""
    Zf = np.where(mask, 1.0, 0.0)
    comp = np.ones_like(mask, dtype=bool)
    loops = []
    for (pts0, _K, closed) in _contour_circuits(Zf, xs, ys, 0.5, comp=comp):
        if not closed or len(pts0) < 3:
            continue
        pts = decimate(pts0, 0.05)
        if len(pts) < 3:
            continue
        per = sum(math.dist(pts[i], pts[(i + 1) % len(pts)])
                  for i in range(len(pts)))
        if per < min_perimeter:
            continue
        loops.append([[round(x, 4), round(y, 4)] for (x, y) in pts])
    return _ccw(loops)


def _usable_area(loop, Fm, gxs, gys):
    """Area (mm^2) of the cells of the CL raster inside `loop` that are NOT
    in the forbidden region Fm (centre-safe territory inside an outer).
    Scanline fill on the node grid; spans beyond the grid edge count as
    usable (no islands can exist outside the padded CL grid)."""
    ny, nx = Fm.shape
    pitch = gxs[1] - gxs[0]
    x0, y0 = gxs[0], gys[0]
    ys_l = [p[1] for p in loop]
    j_lo = max(0, int(math.floor((min(ys_l) - y0) / pitch)))
    j_hi = min(ny - 1, int(math.ceil((max(ys_l) - y0) / pitch)))
    n = len(loop)
    total = 0
    for j in range(j_lo, j_hi + 1):
        y = y0 + j * pitch
        xsec = []
        for k in range(n):
            ax, ay = loop[k]
            bx, by = loop[(k + 1) % n]
            if (ay <= y < by) or (by <= y < ay):
                xsec.append(ax + (y - ay) * (bx - ax) / (by - ay))
        xsec.sort()
        for a, b in zip(xsec[0::2], xsec[1::2]):
            ia = int(math.floor((a - x0) / pitch))
            ib = int(math.ceil((b - x0) / pitch))
            outside = max(0, ia) + max(0, ib - (nx - 1))
            ca, cb = max(0, ia), min(nx - 1, ib)
            if ca <= cb:
                total += int((~Fm[j, ca:cb + 1]).sum())
            total += outside
    return total * pitch * pitch


def level_islands(surf, cutter_big, Zg, xs, ys, z, axl, threads=None):
    """Islands for level Z. Returns (forbidden_loops, Fm):
    * forbidden_loops: the refined boundary of F = {CL_big > Z - axl},
      the authoritative forbidden region for cutter CENTRES at this level.
      Points are the air-side endpoint of each refined bracket (CL <= level
      + KEEP_TOL), i.e. the loop rounds OUTWARD and never under-covers F;
      refined by bisection to < 0.005 mm (finish.refine_contours).
    * Fm: the raster {CL_big > Z - axl} (its eroded contour feeds Adaptive2d,
      which offsets every loop by tool_r + leave so centres stay outside F).
    """
    lvl = z - axl
    # march_level's material side is {CL >= z}; the island region is the
    # STRICT {CL > Z - axl} (a floor exactly at the level is not forbidden),
    # so march/refine at level + eps. NaN (no cutter contact) is AIR: the
    # forbidden region's boundary frequently IS the finite/NaN transition
    # (CL drops off where the cutter loses contact with the model), so cells
    # touching NaN must stay valid for marching - unlike finish's dilated
    # cl_grid, this grid is not pre-grown past the contour of interest.
    mlvl = lvl + 1e-6
    allc = _contour_circuits(Zg, xs, ys, mlvl,
                             comp=np.ones_like(Zg, dtype=bool))
    circuits = [(P, K, c) for (P, K, c) in allc if c and len(P) > 2]
    Fm = np.isfinite(Zg) & (Zg > lvl)
    # R3: if F reaches the CL grid boundary (open circuits, or forbidden cells
    # on the outermost rows/cols) its outer boundary cannot close inside the
    # grid. Silently dropping those open circuits flips the even-odd parity of
    # the island test and ADMITS cutter centres next to pocket walls (the synth
    # pocket failure: centres at 0.39 mm from the wall instead of >= R +
    # leave). Close F with a fence rectangle at the grid bounds so parity stays
    # correct; centres are confined to the stock territory strictly inside the
    # grid anyway, so the fence never rejects a legitimate centre.
    edge = bool(Fm[0, :].any() or Fm[-1, :].any() or
               Fm[:, 0].any() or Fm[:, -1].any())
    fence = edge or any((not c) and len(P) > 1 for (P, _K, c) in allc)
    if not circuits:
        if not fence:
            return [], Fm
        # F covers the whole grid (tool too big for the gap): fence alone.
        rect = [[round(gx, 4), round(gy, 4)] for gx, gy in
                ((xs[0], ys[0]), (xs[-1], ys[0]),
                 (xs[-1], ys[-1]), (xs[0], ys[-1]))]
        return [rect], Fm
    tagged = [(mlvl, np.asarray(P, dtype=float), K, True)
              for (P, K, _c) in circuits]
    pitch = float(xs[1] - xs[0])
    forbidden = []
    for (_lvl, pos, _cl, _ok, closed) in fin.refine_contours(
            surf, cutter_big, tagged, Zg, float(xs[0]), float(ys[0]), pitch,
            width_tol=0.005, threads=threads):
        if not closed or len(pos) < 3:
            continue
        pts = decimate([(float(x), float(y)) for x, y in pos], 0.05)
        if len(pts) < 3:
            continue
        per = sum(math.dist(pts[i], pts[(i + 1) % len(pts)])
                  for i in range(len(pts)))
        if per < 4.0:
            continue
        forbidden.append([[round(x, 4), round(y, 4)] for (x, y) in pts])
    forbidden = _ccw(forbidden)
    if fence:
        rect = [[round(gx, 4), round(gy, 4)] for gx, gy in
                ((xs[0], ys[0]), (xs[-1], ys[0]),
                 (xs[-1], ys[-1]), (xs[0], ys[-1]))]
        forbidden.append(rect)   # CCW, encloses every refined loop
    return forbidden, Fm


def plan_levels(stock_zmax, floor_z, leave, stepdown, flat_floors=None,
               axial_leave=None, final_zmin=None, min_level_gap=0.5):
    """Z levels (tip depths) top-down (legacy, round 6).

    Last level = final_zmin when given, else floor_z + axial_leave (axial
    leave defaults to the radial `leave`). Flat-area detection:
    each flat floor F of the part adds a level at F + axial leave, kept only
    when it sits at least `min_level_gap` below every other level (so it is
    neither redundant with the final level nor a duplicate of a neighbouring
    flat) and stays below the stock top (a level at/above the stock top cuts
    nothing).
    """
    axl = leave if axial_leave is None else axial_leave
    final = final_zmin if final_zmin is not None else floor_z + axl
    zs = []
    z = stock_zmax
    while z > final + 1e-9:
        zs.append(z)
        z -= stepdown
    zs.append(final)
    # first level at stock top removes nothing (tip flush with stock surface)
    if len(zs) > 1 and zs[0] >= stock_zmax - 1e-9:
        zs = zs[1:]
    flat_lvls = []
    for f in sorted(flat_floors or [], reverse=True):
        lvl = round(f + axl, 4)
        if lvl <= final + min_level_gap or lvl >= stock_zmax - 1e-9:
            continue
        if all(abs(lvl - k) >= min_level_gap for k in zs + flat_lvls):
            flat_lvls.append(lvl)
    return sorted(set(zs) | set(flat_lvls), reverse=True)


def plan_stepup_levels(stock_zmax, final_zmin, stepdown=19.05, stepup=1.905,
                      axial_leave=0.381, min_level_gap=0.5):
    """Execution-order level list (Task G item 3).

    Defaults are James's cutting data (stepdown 19.05, stepup 1.905, axial
    leave 0.381). Big levels: stock_zmax - k*stepdown down to final_zmin (the
    last level is final_zmin). After each big level, climb candidates every
    `stepup` mm upward (capped at one stepdown above it and below the stock
    top), so a big level is followed immediately by its step-up levels climbing
    the remaining tall stock (the 41.91 -> 43.81/45.72/47.62 and
    24.95 -> 36.2/38.1/40.0 climb pattern). Candidates too close to an earlier
    level are dropped; empties get pruned at runtime against the stock model.
    """
    big = []
    z = stock_zmax - stepdown
    while z > final_zmin + 1e-9:
        big.append(round(z, 4))
        z -= stepdown
    big.append(round(final_zmin, 4))
    order = []
    cap_hi = stock_zmax - axial_leave - 1e-9
    for zb in big:
        order.append(zb)
        k = 1
        while True:
            zk = round(zb + k * stepup, 4)
            if zk > min(cap_hi, zb + stepdown) + 1e-9:
                break
            if all(abs(zk - kept) >= min_level_gap for kept in order):
                order.append(zk)
            k += 1
    return order


def find_flat_floors(part, cell, x0, y0, stock_box, z_lo, z_hi,
                     min_area_mm2=200.0):
    """Z heights of large flat floors in the part heightfield within
    (z_lo, z_hi): connected cell areas (0.01 mm Z bins, 4-connected, inside
    the stock box) of at least min_area_mm2. (Legacy: Task G replaced the
    flat-area levels with stock-clipped step-up levels.)"""
    import numpy as np
    from collections import deque
    ny, nx = part.shape
    sxmin, sxmax, symin, symax, _, _ = stock_box
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    inb = ((xs >= sxmin) & (xs <= sxmax))[None, :] & \
          ((ys >= symin) & (ys <= symax))[:, None]
    fin = np.isfinite(part)
    q = np.where(fin, np.round(part * 100.0), -10 ** 9).astype(np.int64)
    min_cells = int(math.ceil(min_area_mm2 / (cell * cell)))
    lo_q, hi_q = int(round(z_lo * 100)), int(round(z_hi * 100))
    counts = np.bincount(q[inb & fin].ravel())
    vals = np.nonzero(counts >= min_cells)[0]
    vals = vals[(vals > lo_q) & (vals < hi_q)]
    floors = []
    for v in vals:
        mask = (q == v) & inb
        cells = {tuple(c) for c in np.argwhere(mask)}
        found = False
        while cells and not found:
            seed = cells.pop()
            n_comp = 1
            dq = deque([seed])
            while dq:
                j, i = dq.popleft()
                for nb in ((j + 1, i), (j - 1, i), (j, i + 1), (j, i - 1)):
                    if nb in cells:
                        cells.discard(nb)
                        n_comp += 1
                        dq.append(nb)
            if n_comp >= min_cells:
                found = True
        if found:
            floors.append(v / 100.0)
    return sorted(floors, reverse=True)


def _pt_seg_dist_np(P, A, B):
    """(N,2) points vs (M,2) segment ends A,B -> (N,M) point-segment dist."""
    import numpy as np
    AB = B - A
    AP = P[:, None, :] - A[None, :, :]
    L2 = np.maximum((AB * AB).sum(axis=1)[None, :], 1e-12)
    t = np.clip((AP * AB[None, :, :]).sum(axis=2) / L2, 0.0, 1.0)
    d = AP - t[:, :, None] * AB[None, :, :]
    return np.sqrt((d * d).sum(axis=2))


def _inside_loops(P, loops, chunk=512):
    """Even-odd point-in-polygon for closed loops: (N,2) array -> bool array,
    True where the point is strictly inside the region bounded by ALL loops
    TOGETHER (crossings summed over every loop, then mod 2 - OR-ing per-loop
    parity would wrongly mark points inside a hole of an annulus, e.g. the
    floor of a pocket ringed by a taller frame). Distance-to-loop alone
    cannot see centres deep inside an island loop (R1: those gouge the part
    while every distance check stays green)."""
    import numpy as np
    tot = np.zeros(len(P), dtype=np.int64)
    for lp in loops:
        L = np.asarray(lp, dtype=float)
        if len(L) < 3:
            continue
        x, y = L[:, 0], L[:, 1]
        xn, yn = np.roll(x, -1), np.roll(y, -1)
        for s in range(0, len(P), chunk):
            blk = P[s:s + chunk]
            py = blk[:, 1][:, None]
            cross = (y[None, :] > py) != (yn[None, :] > py)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = x[None, :] + (py - y[None, :]) * (xn[None, :] - x[None, :]) \
                       / (yn[None, :] - y[None, :])
            hit = cross & (blk[:, 0][:, None] < xint)
            tot[s:s + chunk] += hit.sum(axis=1)
    return (tot % 2) == 1


def allowance_violation(points, islands, tool_r, leave, tol=0.02):
    """HARD post-check for one level: every cutter centre cutting at this
    level's Z must stay >= tool_r + leave - tol from that level's island
    loops (the round-5 failure lost 0.37 mm of radial allowance), and must
    never be INSIDE an island loop (R1: distance alone missed centres deep
    inside a loop - the no-hf gouge). Returns (x, y, dist) of the
    closest-to-material offender, else None."""
    import numpy as np
    req = tool_r + leave - tol
    if not points or not islands:
        return None
    P = np.asarray(points, dtype=float)
    ins = _inside_loops(P, islands)
    if ins.any():
        k = int(np.nonzero(ins)[0][0])
        return (float(P[k, 0]), float(P[k, 1]), 0.0)
    worst = None
    for lp in islands:
        L = np.asarray(lp, dtype=float)
        if len(L) < 3:
            continue
        A = L
        B = np.roll(L, -1, axis=0)
        dbox = np.maximum.reduce([
            L[:, 0].min() - P[:, 0], P[:, 0] - L[:, 0].max(),
            L[:, 1].min() - P[:, 1], P[:, 1] - L[:, 1].max(),
            np.zeros(len(P))])
        cand = np.nonzero(dbox < req)[0]
        if cand.size == 0:
            continue
        for s in range(0, cand.size, 512):
            blk = P[cand[s:s + 512]]
            d = _pt_seg_dist_np(blk, A, B).min(axis=1)
            k = int(np.argmin(d))
            if worst is None or d[k] < worst[2]:
                worst = (float(blk[k, 0]), float(blk[k, 1]), float(d[k]))
    if worst is not None and worst[2] < req - 1e-9:
        return worst
    return None


def island_clear_fn(islands, req):
    """Return f(pts) -> bool list: True where a cutter centre is >= `req`
    away from every island loop AND not inside one (the exact drop-cutter
    forbidden geometry - the ground truth the emitted CL must obey,
    independent of the stock heightfield model; R1: the inside test closes the
    distance-only blind spot that let centres deep inside an island pass)."""
    import numpy as np
    segs = []
    for lp in islands:
        L = np.asarray(lp, dtype=float)
        if len(L) < 2:
            continue
        segs.append(np.stack([L, np.roll(L, -1, axis=0)], axis=1))
    if not segs:
        return lambda pts: [True] * len(pts)
    AB = np.concatenate(segs, axis=0)          # (nseg, 2, 2)
    A = AB[:, 0, :]
    B = AB[:, 1, :]

    def f(pts):
        P = np.asarray(pts, dtype=float)
        out = np.full(len(P), np.inf)
        for s in range(0, len(P), 512):
            blk = P[s:s + 512]
            d = _pt_seg_dist_np(blk, A, AB[:, 1, :])
            out[s:s + 512] = d.min(axis=1)
        ins = _inside_loops(P, [lp for lp in islands if len(lp) >= 3])
        return [bool(v >= req) and not i for v, i in zip(out, ins)]
    return f


def build_part_hf(surf, x0, y0, cell, nx, ny, threads=None, drop_z=0.0):
    """Rasterise the part heightfield on a grid (x0/y0 = lower-left corner,
    cell mm, row j = +Y) by dropping a small cylinder (r 0.05 mm) with ocl's
    batch drop-cutter:
    part[j, i] = highest part surface at the cell centre, NaN where the
    column is empty. R1: rough() builds this itself when no --hf is given,
    so the rest/step-up clips and the part-footprint guards always have the
    part model (the no-hf gouge on core_front_setup came from running with
    stock.part = None: every part clip silently degraded)."""
    import numpy as np
    total = nx * ny
    z = np.empty(total)
    CH = 200000
    for a in range(0, total, CH):
        n = min(CH, total - a)
        idx = np.arange(a, a + n)
        jj, ii = np.divmod(idx, nx)
        bd = ocl.BatchDropCutter()   # fresh batch per chunk (reuse crashes)
        bd.setSTL(surf)
        bd.setCutter(ocl.CylCutter(0.05, 50.0))
        if threads:
            bd.setThreads(min(8, threads))
        for k in range(n):
            bd.appendPoint(ocl.CLPoint(x0 + (int(ii[k]) + 0.5) * cell,
                                      y0 + (int(jj[k]) + 0.5) * cell, drop_z))
        bd.run()
        z[a:a + n] = [p.z for p in bd.getCLPoints()]
    z[z < -1e29] = np.nan
    return z.reshape(ny, nx)


def hf_gouge_violation(points, stock, tool_r, tol=0.02):
    """Backstop for the island post-check: no part-heightfield cell within
    (tool_r - cell) of a cutting centre may stand above that point's own Z
    + tol. Catches levels whose island loops came out empty/missing
    (features below min_perimeter) - exactly where
    the island-loop check is blind. The disk shrinks by one cell because the
    hf raster quantises walls by up to one cell, so a centre honouring
    tool_r + leave at a wall keeps a >= leave - tol margin against this
    check at any stock_cell."""
    import numpy as np
    if stock.part is None or not points:
        return None
    c = stock.cell
    rad = tool_r - c
    if rad <= 0:
        return None
    k = int(math.floor(rad / c))
    offs = [(dj, di) for dj in range(-k, k + 1)
            for di in range(-k, k + 1)
            if (dj * dj + di * di) * c * c <= rad * rad]
    P = np.asarray([(p[0], p[1]) for p in points], dtype=float)
    Z = np.asarray([p[2] for p in points], dtype=float)
    ii = np.floor((P[:, 0] - stock.x0) / c).astype(np.int64)
    jj = np.floor((P[:, 1] - stock.y0) / c).astype(np.int64)
    mx = np.full(len(P), -np.inf)
    for dj, di in offs:
        a = np.clip(ii + di, 0, stock.nx - 1)
        b = np.clip(jj + dj, 0, stock.ny - 1)
        np.maximum(mx, stock.part[b, a], out=mx)
    d = mx - Z
    k2 = int(np.argmax(d))
    if d[k2] > tol:
        return (float(P[k2, 0]), float(P[k2, 1]), float(Z[k2]), float(mx[k2]))
    return None


def _bore_pred(isl_ok, zone, stock, x, y, tool_r):
    # BS1a4d2b: helix_entry(centred=True) mirror for band entries - circle
    # THROUGH the start (d = 0), shrinking radii; bore = disk(c, r + tool_r).
    # same order as the emitted centred ladder: radius outer, direction inner
    for rh in [fr * tool_r for fr in (0.8, 0.5, 0.3)] + [0.5, 0.35, 0.2]:
        for q in range(16):
            a = q * math.pi / 8.0
            cx = x + (rh - 0.05) * math.cos(a)   # as the centred ladder
            cy = y + (rh - 0.05) * math.sin(a)
            n = max(16, int(2.0 * math.pi * rh / 0.5))
            a0 = math.atan2(y - cy, x - cx)   # circle_ok's phase + rounding
            circ = [(round(cx + rh * math.cos(a0 + t * 2.0 * math.pi / n),
                           4),
                   round(cy + rh * math.sin(a0 + t * 2.0 * math.pi / n), 4))
                  for t in range(n + 1)]
            if all(isl_ok(circ)) and all(
                    0 <= stock._ci(px) < stock.nx
                    and 0 <= stock._cj(py) < stock.ny
                    and zone[stock._cj(py), stock._ci(px)]
                    for (px, py) in circ):
                return (cx, cy, rh)
    return None


def _helix_turns(r, dz, angle_deg=2.0):
    """Integer turn count so the LAST turn runs a full circle at the bottom
    and completes the bore at exactly z_bot (no separate depth circle needed:
    every point within r + tool_r is swept by the bottom turn). RT2a: the
    pitch honors the ramp angle - turns round UP so the pitch per turn is
    <= 2*pi*r*tan(angle) at the helix radius, and so no emitted G1 segment
    (which travels a chord, slightly shorter than the arc) descends steeper
    than angle + 0.05 deg."""
    if dz <= 0:
        return 1.0
    turns = max(1, int(math.ceil(dz / (2.0 * math.pi * r *
                                       math.tan(math.radians(angle_deg))))))
    seg_per_turn = max(8, int(2 * math.pi * r / 1.0))
    while True:
        n = max(8, int(turns * seg_per_turn))
        chord = 2.0 * r * math.sin(turns * math.pi / n)
        # +/-(1e-4) worst-case jitter from rounding the emitted coords to 4 dp
        if (dz / n + 1e-4) <= (chord - 1e-4) \
                * math.tan(math.radians(angle_deg + 0.04)):
            return turns
        turns += 1



def _rp2_offsets(cell, radius):
    """Disk cell offsets for RP2_0 diagnosis (same shift trick as stock)."""
    k = int(math.ceil(radius / cell))
    return [(dj, di) for dj in range(-k, k + 1) for di in range(-k, k + 1)
            if (dj * dj + di * di) * cell * cell <= radius * radius]


def _rp2_dilate(mask, offs):
    out = np.zeros_like(mask)
    m = mask.astype(np.uint8)
    ny, nx = mask.shape
    for dj, di in offs:
        j0, j1 = max(0, dj), min(ny, ny + dj)
        i0, i1 = max(0, di), min(nx, nx + di)
        if j0 >= j1 or i0 >= i1:
            continue
        out[j0:j1, i0:i1] |= m[j0 - dj:j1 - dj, i0 - di:i1 - di].astype(bool)
    return out


def _rp2_shiftmax(arr, offs):
    out = np.full_like(arr, -np.inf)
    ny, nx = arr.shape
    for dj, di in offs:
        j0, j1 = max(0, dj), min(ny, ny + dj)
        i0, i1 = max(0, di), min(nx, nx + di)
        if j0 >= j1 or i0 >= i1:
            continue
        np.maximum(out[j0:j1, i0:i1], arr[j0 - dj:j1 - dj, i0 - di:i1 - di],
                   out=out[j0:j1, i0:i1])
    return out


def rapid_swept_clear(stock, p0, p1, reach, margin, step=None):
    """True if a straight G0 from p0 to p1 ((x, y, z) tip positions) keeps the
    tip at least `margin` above the highest material (max of live stock top
    and part) within `reach` of the tool axis at EVERY point along the move -
    sampled at the stock cell pitch - not only at its end height. A diagonal
    climb that starts low beside a wall fails here."""
    c = stock.cell if step is None else step
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = max(1, int(math.ceil(L / c)))
    for i in range(n + 1):
        t = i / n
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        z = p0[2] + (p1[2] - p0[2]) * t
        m = stock.link_top_max([(x, y), (x, y)], reach)
        if m > -1e8 and z < m + margin - 1e-3:
            return False
    return True

def _helix_moves(cx, cy, sx, sy, z_top, z_bot, feed, r, angle_deg=2.0):
    """Downward CCW helix at FIXED radius r (the ONE helix entry diameter /
    2, same centre Adaptive2d ramped against) starting at the angle of
    (sx,sy), descending z_top->z_bot in an integer number of turns; the
    bottom turn is the bore-completing circle."""
    if r < 0.05:
        return [{"g": 1, "x": sx, "y": sy, "z": z_bot, "f": feed}]
    a0 = math.atan2(sy - cy, sx - cx)
    turns = _helix_turns(r, z_top - z_bot, angle_deg)
    seg_per_turn = max(8, int(2 * math.pi * r / 1.0))
    n = max(8, int(turns * seg_per_turn))
    out = []
    for i in range(1, n + 1):
        t = i / n
        a = a0 + t * turns * 2 * math.pi
        out.append({"g": 1, "x": round(cx + r * math.cos(a), 4),
                    "y": round(cy + r * math.sin(a), 4),
                    "z": round(z_top + t * (z_bot - z_top), 4), "f": feed})
    return out


def _strip_engage(stock, pts, z, R):
    """RT2: max perpendicular chord of stock standing above Z within the tool
    footprint along a corridor (same measure zmap uses for radial engagement).
    Used to keep at-cut-height feed links to thin strips: a link that would
    cross a broad face at cutting height is a full-width horizontal move."""
    if len(pts) < 2:
        return 0.0
    dx = pts[-1][0] - pts[0][0]
    dy = pts[-1][1] - pts[0][1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return 0.0
    px, py = -dy / L, dx / L
    cell = stock.cell
    k = int(math.ceil(R / cell))
    step = max(1, int(0.5 / cell))
    best = 0.0
    for (cx, cy) in pts[::step]:
        i0, j0 = stock._ci(cx), stock._cj(cy)
        ilo, ihi = max(0, i0 - k), min(stock.nx, i0 + k + 1)
        jlo, jhi = max(0, j0 - k), min(stock.ny, j0 + k + 1)
        if ilo >= ihi or jlo >= jhi:
            continue
        gx = (np.arange(ilo, ihi) - i0) * cell
        gy = (np.arange(jlo, jhi) - j0) * cell
        d = np.hypot(*np.meshgrid(gx, gy))
        win = stock.top[jlo:jhi, ilo:ihi]
        cells = (d <= R + 0.75 * cell) & (win > z + 0.05)
        if not cells.any():
            continue
        proj = gx[None, :] * px + gy[:, None] * py
        w = float(proj[cells].max()) - float(proj[cells].min())
        if w > best:
            best = w
    return best


def _hug_offset(L, eps):
    """Offset a closed polygon (N,2) by eps along per-vertex miter normals
    (right normal of a CCW loop points away from its interior). Spikes at
    sharp corners are capped; the caller chooses the sign so the ring lands
    on the allowed (air) side of the forbidden loops."""
    n = len(L)
    out = np.empty_like(L)
    for i in range(n):
        px, py = L[i]
        ax, ay = L[(i - 1) % n]
        bx, by = L[(i + 1) % n]
        e1 = (px - ax, py - ay)
        e2 = (bx - px, by - py)
        L1 = math.hypot(*e1)
        L2 = math.hypot(*e2)
        if L1 < 1e-12 or L2 < 1e-12:
            out[i] = (px, py)
            continue
        n1 = (e1[1] / L1, -e1[0] / L1)
        n2 = (e2[1] / L2, -e2[0] / L2)
        bx_, by_ = n1[0] + n2[0], n1[1] + n2[1]
        Lb = math.hypot(bx_, by_)
        if Lb < 1e-9:            # 180 deg reversal: just use n1
            out[i] = (px + eps * n1[0], py + eps * n1[1])
            continue
        cos_h = (bx_ * n1[0] + by_ * n1[1]) / Lb
        scale = eps / max(cos_h, 0.34)   # cap miter spike ~3x
        out[i] = (px + bx_ / Lb * scale, py + by_ / Lb * scale)
    return out


def hug_regions(islands, grown, stock, isl_ok, eps=0.05, min_run=1.0):
    """R4: wall-hugging rings that close the reach gap Adaptive2d leaves at
    pocket/island walls. The a2d island input is F eroded by (R - margin)
    (margin ~1.25 mm covers raster quantisation), so a2d centres stay
    margin-distance outside the true forbidden region F and a full-height
    band + corner chunks survive below it (test block Z27 pocket: 142 mm2
    of floor at 8.38 mm). Here each refined island loop (already the
    authoritative, outward-rounded F boundary) is offset by eps toward the
    ALLOWED side and emitted as a contour-parallel cutting run: centres sit
    eps outside refined F - safe by the same construction every other centre
    must obey (isl_ok, allowance post-check, hf backstop, CLCHECK all still
    gate them) - and the disk(r_t) swept by the ring cuts the band down to
    this level's Z, leaving only the analytic R-corner crescent. Points are
    kept only where this level's territory (grown mask) exists and isl_ok
    agrees, so rings appear exactly where rest material remains; the grid
    fence loop filters out on its own (no territory outside the grid)."""
    regions = []
    for lp in islands:
        L = np.asarray(lp, dtype=float)
        if len(L) < 3:
            continue
        ring = _hug_offset(L, eps)
        if int(_inside_loops(ring, islands).sum()) > len(L) // 2:
            ring = _hug_offset(L, -eps)
        P = ring
        ii = np.floor((P[:, 0] - stock.x0) / stock.cell).astype(np.int64)
        jj = np.floor((P[:, 1] - stock.y0) / stock.cell).astype(np.int64)
        inb = (ii >= 0) & (ii < stock.nx) & (jj >= 0) & (jj < stock.ny)
        terr = np.zeros(len(P), dtype=bool)
        if inb.any():
            terr[inb] = grown[jj[inb], ii[inb]]
        ok = np.asarray(isl_ok([(float(x), float(y)) for x, y in P]))
        good = terr & ok
        if not good.any():
            continue
        # rotate to an invalid start so runs are linear, then split
        order = np.roll(np.arange(len(P)), -(int(np.argmax(~good)) + 1)) \
            if good.any() and not good[0] else np.arange(len(P))
        g = good[order]
        runs = []
        s = None
        for k in range(len(g)):
            if g[k] and s is None:
                s = k
            if not g[k] and s is not None:
                runs.append((s, k))
                s = None
        if s is not None:
            runs.append((s, len(g)))
        # merge wrap-around run (loop): first and last both good
        if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == len(g):
            runs[0] = (runs[-1][0] - len(g), runs[0][1])
            runs.pop()
        for (a, b) in runs:
            idx = [order[t % len(g)] for t in range(a, b)]
            if len(idx) < 2:
                continue
            pts = [(round(float(P[t, 0]), 4), round(float(P[t, 1]), 4))
                   for t in idx]
            per = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            if per < min_run:
                continue
            regions.append({"start": list(pts[0]), "helix": None,
                           "paths": [["cutting", pts]]})
    return regions


def _nn_order(phase, cand, pos):
    """DT1: nearest-neighbour ordering of region indices for one HR1 phase
    with deterministic tie-breaking: equal travel distance picks the LOWEST
    region index, and a chosen region's entry point breaks an exact distance
    tie by (distance, x, y) - never by the order a set/dict/worker pool
    happened to emit the candidates. Returns (order, end_pos)."""
    out = []
    remaining = sorted(phase)
    while remaining:
        if pos is None:
            k = remaining[0]
        else:
            k = min(remaining, key=lambda k: (min(math.dist(pos, p)
                                                  for p in cand[k]), k))
        out.append(k)
        remaining.remove(k)
        pos = min(cand[k], key=lambda p: (math.dist(pos, p), p[0],
                                            p[1])) if pos is not None \
            else cand[k][0]
    return out, pos


def _run_a2d(outers, holes, islands, tool_r, leave, stepover, tolerance,
             keep_tool_down, helix_dia):
    """One level's Adaptive2d run; returns plain picklable region dicts."""
    a2d = area.Adaptive2d()
    a2d.stepOverFactor = stepover
    a2d.toolDiameter = 2 * tool_r
    # R6c-n: ONE helix entry diameter feeds both a2d's ramp settings and
    # our entry generator, so the bore we cut equals the bore a2d assumed.
    a2d.helixRampTargetDiameter = helix_dia
    a2d.helixRampMinDiameter = helix_dia
    a2d.keepToolDownDistRatio = keep_tool_down
    a2d.stockToLeave = leave
    a2d.tolerance = tolerance
    a2d.forceInsideOut = False
    a2d.finishingProfile = False
    a2d.opType = area.AdaptiveOperationType.ClearingInside
    results = a2d.Execute(list(outers), list(outers) + holes + islands, [],
                          lambda tp: False)
    CT = area.AdaptiveMotionType.Cutting
    LC = area.AdaptiveMotionType.LinkClear
    regions = []
    for res in results:
        if getattr(res, "StartPointNotFound", False) or not res.AdaptivePaths:
            continue
        paths = []
        for pth in res.AdaptivePaths:
            mt, pts = pth[0], pth[1]
            if not pts:
                continue
            kind = "cutting" if mt == CT else ("linkclear" if mt == LC
                                              else "notclear")
            paths.append([kind, [[round(float(x), 4), round(float(y), 4)]
                                for (x, y) in pts]])
        if not any(k == "cutting" for (k, _) in paths):
            continue
        sp = res.StartPoint
        hc = res.HelixCenterPoint
        regions.append({
            "start": [round(float(sp[0]), 4), round(float(sp[1]), 4)]
            if sp is not None and len(sp) >= 2 else None,
            "helix": [round(float(hc[0]), 4), round(float(hc[1]), 4)]
            if hc is not None and len(hc) >= 2 else None,
            "paths": paths,
        })
    return regions


def mandatory_flat_levels(flat_zs, axl, final, stock_zmax, min_gap=0.5):
    """Task R2 item 3: every up-facing flat floor F of the part (STL
    flat-face Zs) gets a level at F + axial leave that the rest/skip logic
    can never drop. Candidates at/above the stock top (cut nothing) or below
    the final level are excluded; near-duplicate flat faces (tessellation
    noise) collapse to one level per min_gap cluster, keeping the highest so
    the level still stands >= axial leave above every face in the cluster."""
    cand = sorted({round(f + axl, 4) for f in flat_zs
                   if final - 1e-9 <= f + axl < stock_zmax - axl},
                  reverse=True)
    out = []
    for z in cand:
        if all(abs(z - k) >= min_gap for k in out):
            out.append(z)
    return sorted(out)


def insert_levels(order, extra):
    """Insert levels into the execution order right after the last level
    below them (keeps each big level's climb-grid run ascending)."""
    order = list(order)
    for z in sorted(extra):
        if any(abs(z - k) < 1e-6 for k in order):
            continue
        pos = len(order)
        for i, k in enumerate(order):
            if k >= z - 1e-9:
                pos = i
                break
        order.insert(pos, z)
    return order


def rough(surf, stock_box, tool_r, floor_z, leave=0.381, stepdown=19.05,
          stepover=0.16, cut_feed=3429.0, ramp_feed=1270.0,
          clearance_z=None, lift=1.9, wl_sampling=None, threads=8,
          tolerance=0.05, keep_tool_down=3.0, stl_path=None, workers=None,
          axial_leave=None, final_zmin=None, allowance_check=True,
          corner_r=0.127, part_hf=None, stock_cell=0.5, stepup=1.905,
          min_rest=1.0, min_level_area=20.0, rapid_margin=1.0,
          clip_bridge_mm=5.0, feed_link_max=40.0,
          progress=None, stock_out=None, ramp_angle_deg=2.0):
    """Plan the rest-aware roughing toolpath. Returns (moves, stats).

    moves: neutral dicts {g:0|1, x,y,z, f (mm/min or None)}.
    stock_box: (xmin,xmax,ymin,ymax,zmin,zmax) of the raw stock.
    part_hf: (part, x0, y0, cell) final-part heightfield for the
      "remaining stock above the part > min_rest" clip on level regions.
      When None it is built from `surf` itself (build_part_hf, R1) so the
      part clips are never silently skipped.
    Levels: big stepdowns + stock-clipped step-up climb grids (Task G) plus
      the mandatory flat-floor levels (R2 item 3); `stepup` = climb grid
      pitch, levels whose clipped region is smaller than min_level_area mm^2
      are skipped (mandatory levels never are - their min_rest clip relaxes
      to 0).
    Islands: drop-cutter CL grid with the big cutter (tool_r + leave),
      per-level F = {CL > Z - axial_leave} refined to < 0.005 mm
      (level_islands) - never ocl waterlines (R2).
    Links: stay tool-down within/between levels when the stock heightfield
      says the straight link at cutting Z (or Z + lift) is clear; otherwise
      retract to clearance and helix/plunge.
    rapid_margin: Task R5 - every G0 (retracts, lifts, traverses) is checked
      against the engine's LIVE stock model (StockField as cut so far, plus
      the part heightfield): the rapid height must be >= max(stock top, part)
      within the tool radius along the swept path + rapid_margin (default
      1.0 mm); emit() raises the height to that verified level when needed
      (or to the clearance plane), so no rapid can pass through uncut stock.
    allowance_check: HARD post-check per level that no cutter centre at the
      level's Z entered or came within 0.005 mm of that level's forbidden
      island loops, plus the part-heightfield backstop; at the very end an
      independent CLCHECK gate (probe_rough_clcheck, separate code path)
      drops the ACTUAL cutter on every cutting move (sampled <= 0.1 mm) and
      fails the run if any tip sits below CL + axial_leave - 0.005 mm.
      Raises RuntimeError with the location on violation.
    stock_out: optional .npy path: write the engine's OWN final stock
      heightfield (engine/stock.py model after all levels, NaN outside the
      tracked box) with a .json sidecar {x0,y0,cell} so finishing can verify
      rapids against it (finish --stock-from, S3b).
    """
    sxmin, sxmax, symin, symax, szmin, szmax = stock_box
    # RT2a: the ramp angle is the parameter the generator honors (helix pitch
    # and straight ramps); <= 0 is rejected, out-of-range clamps to [0.5, 15].
    if ramp_angle_deg <= 0:
        raise ValueError("ramp angle must be > 0 deg")
    ramp_angle_deg = min(max(float(ramp_angle_deg), 0.5), 15.0)
    if clearance_z is None:
        clearance_z = szmax + 2.0
    axl = leave if axial_leave is None else axial_leave
    final = final_zmin if final_zmin is not None else floor_z + axl

    stock = StockField(stock_box, cell=stock_cell)
    if part_hf is not None:
        part, px0, py0, pcell = part_hf
        stock.set_part_from_other_grid(part, px0, py0, pcell, fill=-1e9)
    else:
        # R1: the part model is mandatory - without it region_mask's
        # pz/min_rest clips and the grown-mask island punch-out silently
        # degrade, and levels whose islands are missing cut straight
        # through the part. Build it from the STL we already load.
        part = build_part_hf(surf, stock.x0, stock.y0, stock.cell,
                             stock.nx, stock.ny, threads=threads,
                             drop_z=szmin - 1.0)
        stock.set_part_from_other_grid(part, stock.x0, stock.y0, stock.cell,
                                      fill=-1e9)
    stock.set_tool(tool_r)

    # Task RS: the cutting region comes from the STOCK box, never from the
    # heightfield / CL grid extent: cutter centres may pass a stock face by
    # at most the tool radius (edge clean-up), whatever the --hf grid bounds.
    centre_zone = stock.dilate(stock.inb, tool_r)

    order = plan_stepup_levels(szmax, final, stepdown=stepdown, stepup=stepup,
                              axial_leave=axl)
    # R2 item 3: mandatory flat-floor levels (up-facing flat faces + axl)
    # R4: a flat level already present in the step-up order (typically the
    # final level floor+axl) keeps its mandatory flag too - it is the level
    # that must finish the floor at exactly axial leave and may never be
    # skipped because an early hug pass already cut most of the rest.
    mand = set(mandatory_flat_levels(fin.flat_face_zs(surf), axl, final,
                                    szmax))
    order = insert_levels(order, mand - {round(z, 4) for z in order})
    # RT items 1+2: plane the topmost flat floors (plateau) FIRST. While raw
    # stock top stands, every link and entry over it flies at stock-top +
    # margin; after the top flats run, those rapids drop to flat-top + margin.
    # Only flats at least one stepdown below the stock top qualify (the deep
    # final-floor flat stays in its tier - plunging the pocket before the
    # plateau is planed would raise rapids, not lower them).
    hoist = [z for z in order if round(z, 4) in {round(m, 4) for m in mand}
             and szmax - stepdown <= z < szmax - 1e-9]
    if hoist:
        hoisted = set(hoist)
        top_flat = max(hoist)
        hoist += [z for z in order if z > top_flat and z not in hoisted]
        order = sorted(hoist) + [z for z in order if z not in hoisted]

    # R6c-n: ONE helix entry diameter - feeds a2d.helixRampTargetDiameter/
    # MinDiameter AND _helix_moves, so the entry bore we cut equals the
    # bore Adaptive2d plans its first loops against.
    helix_dia = 0.8 * 2 * tool_r
    stats = {"levels": [], "n_regions": 0, "cut_len": 0.0, "plunge_len": 0.0,
             "rapid_len": 0.0, "n_rapid_bumps": 0,
             "t_islands": 0.0, "t_adaptive": 0.0,
             "n_retracts": 0, "n_lifts": 0, "n_notclear_links": 0,
             "n_clip_breaks": 0, "n_axial_plunge": 0, "n_clip_bridges": 0,
             "n_offset_descends": 0, "n_axial_suspect": 0,
             "n_feed_links": 0, "n_air_links": 0, "n_deep_links": 0,
             "helix_dia_mm": round(helix_dia, 4),
             "ramp_angle_deg": round(ramp_angle_deg, 3),
             "n_tooldown_links": 0, "levels_planned": [round(z, 3) for z in order],
             "n_entry_descends": 0, "entry_feed_mm": 0.0,
             "n_reentry_descends": 0, "reentry_feed_mm": 0.0,
             "n_side_entries": 0, "side_entry_feed_mm": 0.0,
             "credit_fallback": [],  # BS1a4c: every credit fallback at emit
             "mandatory_levels": sorted(round(z, 3) for z in mand)}
    helix_n = [0]   # BS1a4c: successful entry helices emitted (f3f2165)
    # RP0 diagnosis (engine/TASK_RP0.md): env-gated instrumentation only, no
    # behavior change when RT_RP is unset.
    _RP = bool(os.environ.get("RT_RP"))
    rp_levels = []
    # RP2_0 diagnosis (engine/TASK_RP2_0.md): per-region OPEN/CLOSED side-
    # entry classification on the LIVE stock model. RP2_1: the classification
    # now DRIVES entry selection (open regions try the verified offset/side
    # descent before any helix); the per-region dump stays env-gated.
    _RP2 = bool(os.environ.get("RT_RP2"))
    rp2_regions = []
    rp2_lv_sum = []
    _c0 = stock.cell
    RP2_OFF_U = _rp2_offsets(_c0, tool_r)          # swept cutting disk
    RP2_OFF_C = _rp2_offsets(_c0, tool_r + 2.0)     # contact/reach band
    RP2_OFF_D = _rp2_offsets(_c0, tool_r + 0.5)      # descent clearance

    # R2 item 1: ONE batched drop-cutter CL grid with the ACTUAL cutter
    # grown by 2x the radial allowance; per-level islands threshold this grid
    # (CL does not depend on Z). Covers the part bbox + cutter radius so all
    # island loops close strictly inside the grid.
    R = tool_r + leave
    pitch = min(stock_cell, 0.5)
    pad = R + 2.0 * pitch
    pbx0, pbx1, pby0, pby1 = (float(v) for v in surf.getBounds()[:4])
    gx0 = max(sxmin - pad, pbx0 - pad)
    gx1 = min(sxmax + pad, pbx1 + pad)
    gy0 = max(symin - pad, pby0 - pad)
    gy1 = min(symax + pad, pby1 + pad)
    cutter_big = big_cutter(tool_r, leave, corner_r)
    t0 = time.time()
    gxs, gys, Zg = cl_island_grid(surf, cutter_big, gx0, gy0, gx1, gy1,
                                  pitch, threads=threads)
    stats["t_islands"] = time.time() - t0
    # Adaptive2d island input: F eroded by disk(R - margin); margin covers
    # grid quantisation (~1 pitch), contour staircasing and the a2d
    # tolerance, so centres at a2d's tool_r + leave offset stay outside F.
    isl_margin = 2.0 * pitch + tolerance + 0.2
    erode_r = max(R - isl_margin, pitch)

    moves = []
    prev = [None, None, clearance_z]
    hf_pts = []  # cutting (G1) points with their own Z, per level (backstop)

    # RT: descent-clearance and flat-bottom disk offsets on the stock grid.
    # Descent clearance = the existing R5 rapid-clear criterion (max live
    # material within tool_r + rapid_margin); flat-bottom disk shrunk by one
    # cell (hf quantisation convention of hf_gouge_violation): a wall sliver
    # whose cell centres sit just beyond the flat bottom is a side cut, not
    # an axial plunge.
    c_sc = stock.cell
    k_rt = int(math.ceil((tool_r + rapid_margin) / c_sc))
    offs_rt = [(dj, di) for dj in range(-k_rt, k_rt + 1)
               for di in range(-k_rt, k_rt + 1)
               if (dj * dj + di * di) * c_sc * c_sc
               <= (tool_r + rapid_margin) ** 2]
    # flat bottom disk shrunk by one cell (hf quantisation convention of
    # hf_gouge_violation): a wall sliver whose cell centres sit just beyond
    # the flat bottom is a side cut, not an axial plunge
    r_flat = max(tool_r - corner_r - c_sc, 0.0)
    k_fl = int(math.ceil(r_flat / c_sc)) if r_flat > 0 else -1
    offs_fl = [(dj, di) for dj in range(-k_fl, k_fl + 1)
               for di in range(-k_fl, k_fl + 1)
               if (dj * dj + di * di) * c_sc * c_sc <= r_flat * r_flat]
    # RT item 3 enforcement disk: the judge (verify/zmap.py) samples its own
    # grid; cell centres of two grids with the same pitch differ by at most
    # half a cell diagonal (cell/sqrt(2)). Checking one judge-radius + that
    # phase shift means any wall the judge can see inside its flat-bottom disk
    # is visible here too - while material just outside (a pure side/rim cut)
    # does not trigger a needless helix.
    r_ax = max(tool_r - corner_r - c_sc + c_sc / math.sqrt(2.0) + 0.01, 0.0)
    k_ax = int(math.ceil(r_ax / c_sc)) if r_ax > 0 else -1
    offs_ax = [(dj, di) for dj in range(-k_ax, k_ax + 1)
               for di in range(-k_ax, k_ax + 1)
               if (dj * dj + di * di) * c_sc * c_sc <= r_ax * r_ax]
    # RT: the judge reads its stock model BEFORE each move cuts, so material
    # this engine has already cleared at the move's start may still show under
    # its disk at descent. Verify straight feed-down against the full tool
    # radius + half a cell diagonal; anything there goes to helix or to the
    # offset-descent corridor instead of a straight feed plunge.
    # RT2: the engine's own mill kernel lowers a 0.5 mm cell once its centre
    # is inside the tool disk, so a cell at the disk edge is cleared more
    # optimistically than the judge's 0.1 mm grid ever cuts it - add one full
    # cell beyond the phase-shift margin so those rim slivers still trigger a
    # helix/offset descent.
    r_wide = tool_r - corner_r + c_sc / math.sqrt(2.0) + c_sc
    k_wide = int(math.ceil(r_wide / c_sc)) if r_wide > 0 else -1
    offs_wide = [(dj, di) for dj in range(-k_wide, k_wide + 1)
                 for di in range(-k_wide, k_wide + 1)
                 if (dj * dj + di * di) * c_sc * c_sc <= r_wide * r_wide]

    def disk_top(x, y, offs):
        """max live stock top over the cell offsets around (x, y)."""
        i0 = stock._ci(x)
        j0 = stock._cj(y)
        mx = -np.inf
        for dj, di in offs:
            a, b = i0 + di, j0 + dj
            if 0 <= a < stock.nx and 0 <= b < stock.ny:
                v = stock.top[b, a]
                if v > mx:
                    mx = float(v)
        return mx

    def helix_entry(x, y, z, hc, centred=False, bore=None):
        """RT: bore down to cutting depth on a helix instead of axially
        plunging. The region entry point often hugs a forbidden island with
        only marginal clearance, so the helix is placed at a nearby position
        whose full circle is island-legal and inside this level's territory;
        the tool then feeds at Z from the helix end back to (x, y, Z).
        Adaptive2d's own helix centre is tried first. Returns True when a
        helix was emitted."""
        z_top0 = max(disk_top(x, y, offs_rt), -1e8)
        z_top = min(clearance_z, max(z_top0 + rapid_margin if z_top0 > -1e8
                                     else z, z + 0.3))

        def circle_ok(cx, cy, r):
            n = max(16, int(2 * math.pi * r / 0.5))
            a0 = math.atan2(y - cy, x - cx) if math.dist((cx, cy), (x, y)) \
                > 1e-9 else 0.0
            circ = [(round(cx + r * math.cos(a0 + t * 2 * math.pi / n), 4),
                    round(cy + r * math.sin(a0 + t * 2 * math.pi / n), 4))
                   for t in range(n + 1)]
            if not all(isl_ok(circ)):
                return None
            for (px, py) in circ:
                i = int(math.floor((px - stock.x0) / c_sc))
                j = int(math.floor((py - stock.y0) / c_sc))
                if not (0 <= i < stock.nx and 0 <= j < stock.ny
                       and centre_zone[j, i]):
                    return None
            return circ

        def try_cand(cx, cy, r):
            """emit helix around (cx,cy) radius r through/near the entry;
            return True on success. RT2: the circle is VALIDATED at exactly
            the radius we EMIT (the old code checked a candidate radius but
            emitted helix_dia/2, so the real path could cross islands and
            leave uncut stock under the flat bottom)."""
            circ = circle_ok(cx, cy, r)
            if circ is None:
                if os.environ.get("RT2_DEBUG"):
                    print("  helix cand (%.2f,%.2f,r=%.2f) for entry (%.3f,"
                          "%.3f,%.3f): circle bad" % (cx, cy, r, x, y, z),
                          flush=True)
                return False
            # start point on the circle nearest the current XY (short rapid
            # across at z_top), bore down, then feed back to the entry
            # BS1a4d2b: a centred bore starts OPPOSITE the entry, so the floor
            # circle runs before the return feed lands on it across the bore
            s = (max if centred else min)(
                circ[:-1], key=lambda p: (math.dist(p, (x, y)), p[0], p[1]))
            # helix end point (same turn count as _helix_moves) - validate
            # the return segment to the entry BEFORE emitting anything
            a0s = math.atan2(s[1] - cy, s[0] - cx)
            turns = _helix_turns(r, z_top - z, ramp_angle_deg)
            ea = a0s + turns * 2 * math.pi
            e = (round(cx + r * math.cos(ea), 4),
                 round(cy + r * math.sin(ea), 4))
            seg_n = max(2, int(math.dist(e, (x, y)) / 0.4) + 1)
            seg = [(round(e[0] + (x - e[0]) * t / (seg_n - 1), 4),
                    round(e[1] + (y - e[1]) * t / (seg_n - 1), 4))
                   for t in range(seg_n)]
            if not all(isl_ok(seg)):
                if os.environ.get("RT2_DEBUG"):
                    print("  helix cand (%.2f,%.2f,r=%.2f): seg bad"
                          % (cx, cy, r), flush=True)
                return False          # caller falls back (counts axial)
            # RT2: the return feed runs at cutting Z, entirely inside the
            # bore the helix + depth circle just cut (disk r + tool_r about
            # the centre) - its floor is at Z there. Requiring containment
            # keeps the flat bottom from dragging over uncleared stock at
            # full width (the horizontal engagement spikes zmap reports).
            if any(math.dist(p, (cx, cy)) > r + tool_r - corner_r - 0.25
                   for p in seg):
                if os.environ.get("RT2_DEBUG"):
                    print("  helix cand (%.2f,%.2f,r=%.2f): entry outside bore"
                          % (cx, cy, r), flush=True)
                return False
            # RT2: the traverse height must clear BOTH the entry column and
            # the corridor from the entry to the helix start. The old code
            # descended at the entry to z_top (column-clear only) and then ran
            # diagonally to s: emit()'s rapid bump lifted the END point over
            # the corridor's tall stock but the diagonal sweep still rode
            # below it near the start - a rapid collision zmap flags.
            zh = z_top
            reqc = stock.link_top_max([(x, y), (s[0], s[1])],
                                     tool_r + rapid_margin)
            if reqc > -1e8:
                zh = min(clearance_z, max(zh, reqc + rapid_margin))
            if prev[2] is not None and prev[2] > zh + 1e-6:
                emit({"g": 0, "x": prev[0] if prev[0] is not None else x,
                      "y": prev[1] if prev[1] is not None else y,
                      "z": round(zh, 4)})
            emit({"g": 0, "x": s[0], "y": s[1], "z": round(zh, 4)})
            # RT2: do NOT pre-write the entry corridor at z_top - nothing has
            # cut it yet (the G0 into the helix start is a rapid; the corridor
            # is really cleared by the return feed at Z below, which writes it
            # honestly). Claiming it early let a later rapid ride at height
            # z_top+margin into stock zmap still saw standing.
            # RT2: mill the helix segment-by-segment at each segment's START
            # z. Milling the ideal circle at z_bot (the old model) claimed the
            # bore was complete at full radius, but a point on the ring is only
            # under the disk during part of each turn: where that angular
            # window closes above z_bot, a crescent of stock really remains
            # (zmap replays the emitted segments and sees it). Modelling the
            # conservative start height keeps feed_down's axial checks honest.
            # Also, if the rapid to the helix start was lifted above zh (R5
            # verified-clear bump), descend from the ACTUAL height: otherwise
            # the first helix segment bridges the lift at ~90 deg - a plunge.
            zt = prev[2] if (prev[2] is not None and prev[2] > zh) else zh
            hx, hy, hz = s[0], s[1], zt
            for hv in _helix_moves(cx, cy, s[0], s[1], zt, z, ramp_feed, r,
                                  ramp_angle_deg):
                emit(hv)
                stock.mill_segment(hx, hy, hv["x"], hv["y"], hz, tool_r,
                                  corner_r)
                hx, hy, hz = hv["x"], hv["y"], hv["z"]
            # HB1v2: a helix floor is a spiral - the point opposite the run's
            # end last stood under the disk one turn earlier, so it stands up
            # to one pitch above Z INSIDE the bore; the region's first
            # horizontal loop then shears that ridge across nearly the whole
            # disk at the CUTTING feed (the a2d_first ridge windows). Emit one
            # full flat circle at Z on the helix path (same centre/radius, at
            # the ramp feed) as part of the entry, milled honestly into the
            # live stock model, so the ridge is cut flat before any
            # cutting-feed move runs over it.
            if r >= 0.15:
                n_c = max(8, int(2 * math.pi * r / 1.0))
                ea2 = math.atan2(hy - cy, hx - cx)
                for i in range(1, n_c + 1):
                    aa = ea2 + i * 2.0 * math.pi / n_c
                    cxx = round(cx + r * math.cos(aa), 4)
                    cyy = round(cy + r * math.sin(aa), 4)
                    emit({"g": 1, "x": cxx, "y": cyy, "z": round(z, 4),
                          "f": ramp_feed})
                    stock.mill_segment(hx, hy, cxx, cyy, z, tool_r, corner_r)
                    hx, hy = cxx, cyy
            emit({"g": 1, "x": x, "y": y, "z": z, "f": cut_feed})
            stock.mill_path(seg, z, tool_r, corner_r)
            mill_now(x, y, z)
            return True

        if bore is not None:
            # BS1a4d4: the emitted entry IS the planned bore - no re-search
            if not try_cand(bore[2], bore[3], bore[4]):
                raise RuntimeError("band credit bore rejected at emit: "
                                   "(%.3f, %.3f)" % (x, y))
            return True
        if hc is not None:
            r0 = math.dist((hc[0], hc[1]), (x, y))
            if r0 > 0.05 and try_cand(hc[0], hc[1], r0):
                return True
        if centred:
            # BS1a4d2b: band channel entries bore ONLY circles THROUGH the
            # start (centre rh away, shrinking radii: main-tier then fine-tier)
            # so the whole start disk lies inside the swept bore; every
            # candidate keeps try_cand's CL/island/zone/containment checks.
            for rh in [fr * tool_r for fr in (0.8, 0.5, 0.3)] + [0.5, 0.35,
                                                                  0.2]:
                for q in range(16):
                    a = q * math.pi / 8.0
                    # centre 0.05 short of rh: the start lies just INSIDE
                    # the circle, so no helix/floor-circle vertex lands on it
                    # and the one landing is the return feed after the floor
                    if try_cand(x + (rh - 0.05) * math.cos(a),
                               y + (rh - 0.05) * math.sin(a), rh):
                        return True
            return False
        # RT2: every tier now EMITS at the validated radius and the pitch is
        # capped so no segment descends steeper than ~12 deg (zmap's axial
        # gate is 15): the old tiers descended at 0.5 mm/turn regardless of
        # radius, which at r <= 0.5 is ~22 deg - an axial plunge by the
        # judge's own angle criterion.
        for d in (1.5, 3.0, 4.5, 6.0, 8.0):
            for q in range(16):
                a = q * math.pi / 8.0
                nx_, ny_ = math.cos(a), math.sin(a)
                px_, py_ = x + d * nx_, y + d * ny_
                for fr in (0.5, 0.8, 0.3):
                    rh = fr * tool_r
                    if rh < 0.15:
                        continue
                    # circle through p, bulging further inward from p
                    if try_cand(px_ + rh * nx_, py_ + rh * ny_, rh):
                        return True
        # fine tier: narrow edge-cleanup bands (stock face + tool reach) are
        # too tight for a full-size helix - bore with a small eccentricity.
        # RT2: no `grown` prefilter on p - the entry candidate itself can sit
        # at the territory edge (a2d fallback points); circle_ok (isl_ok +
        # centre_zone) plus bore containment are the real guards.
        for d in (0.0, 0.3, 0.6, 1.0):
            for q in range(16):
                a = q * math.pi / 8.0
                nx_, ny_ = math.cos(a), math.sin(a)
                px_, py_ = x + d * nx_, y + d * ny_
                for rh in (0.5, 0.35, 0.2):
                    if try_cand(px_ + rh * nx_, py_ + rh * ny_, rh):
                        return True
        return False

    def lnk_cut_ok(st, path, z, key):
        """BS1a4d3 (e): a cutting-feed link that is NOT stock-clear on the
        live stock at its Z is checked as a cut - the band planner's window
        measure on the live stock at Z, credit 0. Max window <= SPIKE_MM
        stays a link; over it the caller lifts and re-enters via enter_at."""
        if st.link_clear(path, z):
            return True
        from engine.band import _simulate, SPIKE_MM
        stats[key + "_chk"] = stats.get(key + "_chk", 0) + 1
        w = _simulate(path, st, z, tool_r, st.cell, 0.0)
        ok = not w or max(w) <= SPIKE_MM
        if not ok:
            stats[key + "_cvt"] = stats.get(key + "_cvt", 0) + 1
        return ok

    def find_shift(x, y, z, force=False, flank=False):
        """RT item 1: when the descent column at (x, y) has tall material in
        its R5 pad ring beside it (long feed stretch), find a nearby point
        whose FULL pad column is clear down to just above Z. The tool G0s
        down there and feeds the last bit horizontally at depth - side
        engagement only, no axial drag (floor under the feed-in path must be
        at/below Z).
        RP2_1 flank=True (OPEN region side entry): the feed-in at depth is
        allowed to engage THIS level's standing stock with the tool flank -
        that is the material the region exists to remove. What stays checked
        exactly as today: judge-disk-clear descent column (no axial removal),
        island legality of the whole feed path, and the part heightfield
        backstop (hf_gouge_violation) so the flank never crosses finished
        geometry; only the live-stock floor test is replaced by the part test.
        """
        req = disk_top(x, y, offs_rt)
        if not force and not flank and req <= z + 3.0:
            return None          # the vertical feed stretch is short anyway
        for dist in (2.0, 3.5, 5.0, 7.0, 9.0, 11.0, 13.0):
            for q in range(16):
                a = q * math.pi / 8.0
                sx = round(x + dist * math.cos(a), 4)
                sy = round(y + dist * math.sin(a), 4)
                if not (stock_box[0] + tool_r <= sx <= stock_box[1] - tool_r
                        and stock_box[2] + tool_r <= sy
                        <= stock_box[3] - tool_r):
                    continue     # footprint must stay inside the stock box
                # RT2: judge-disk clearance (not the wider R5 pad) makes far
                # more columns available near walls; a straight descent there is
                # still axial-safe because no material stands above Z+0.04
                # within the judge's own disk, and the horizontal feed-in is
                # floor-checked below.
                if disk_top(sx, sy, offs_wide) > z + 0.04:
                    continue
                n = max(2, int(dist / 0.4))
                path = [(round(sx + (x - sx) * t / n, 4),
                        round(sy + (y - sy) * t / n, 4))
                       for t in range(n + 1)]
                if not all(isl_ok3(path)):
                    continue
                if flank:
                    if hf_gouge_violation([(px, py, z) for (px, py) in path],
                                         stock, tool_r) is not None:
                        continue     # feed-in would take the flank over part
                    # SE2: the whole sideways feed-in (column -> region start,
                    # swept by tool_r) must run through material ALREADY
                    # cleared at this level: live stock top along the swept
                    # path <= Z + AXIAL_FLOOR. Standing stock above the level
                    # (e.g. a full-width slot of the flat at up to full
                    # stepdown) means helix instead; link_clear fails closed
                    # when the path leaves the tracked stock record.
                    if not stock.link_clear(path, z + AXIAL_FLOOR):
                        continue     # feed-in crosses standing stock at depth
                    if not lnk_cut_ok(stock, path, z, "fdin"):
                        continue     # (e): the flank feed-in reads a heavy cut
                    # the G0 descent at (sx, sy) must itself be rapid-clear
                    # down to Z: max(stock, part) within tool_r + margin at the
                    # column <= Z + 0.05, else emit()'s R5 bump lifts the
                    # descent back to the traverse height and the feed-in
                    # becomes a diagonal plunge (zmap axial gate).
                    if stock.link_top_max([(sx, sy), (sx, sy)],
                                         tool_r + rapid_margin) > z + 0.05:
                        continue
                elif stock.link_top_max(path,
                                       max(tool_r - corner_r - 0.5, 0.1)) \
                        > z + 0.05:
                    continue     # would drag the flat bottom over stock
                return (sx, sy)
        return None

    def offset_down(x, y, z, off):
        """RT item 1 / RP2_1: descend on the verified-clear column at off and
        feed the last bit horizontally at depth onto (x, y, Z)."""
        sx, sy = off
        emit({"g": 0, "x": sx, "y": sy, "z": round(prev[2], 4)})
        # The column at (sx, sy) is judge-disk-clear + part-pad-clear down to
        # Z, so the descent there removes nothing axially: feed it at ramp
        # feed rather than rapid - a G0 descent could be R5-bumped back up by
        # pad material, stranding the tool at traverse height and turning the
        # feed-in into a diagonal plunge.
        if prev[2] > z + 1e-6:
            emit({"g": 1, "x": sx, "y": sy, "z": z, "f": ramp_feed})
        mill_now(sx, sy, z)
        emit({"g": 1, "x": x, "y": y, "z": z, "f": cut_feed})
        n = max(2, int(math.dist((sx, sy), (x, y)) / 0.4))
        stock.mill_path([(round(sx + (x - sx) * t / n, 4),
                         round(sy + (y - sy) * t / n, 4))
                        for t in range(n + 1)], z, tool_r, corner_r)
        mill_now(x, y, z)
        stats["n_offset_descends"] += 1

    def feed_down(x, y, z, hc=None, side=False, centred=False, bore=None):
        """RT item 1+3: reach (x, y, Z) from directly above. Straight feed is
        only allowed where the flat bottom cuts already-cleared ground: any
        stock under the footprint goes through a helix/ramp entry; the air
        stretch above a verified-clear height (max live material within the
        tool radius + margin along the column, R5 criterion) travels at G0,
        and only the remaining stretch feeds at ramp feed.
        RP2_1 side=True (OPEN region entry / re-entry): try the verified
        offset descent FIRST - G0 down beside the target in cleared stock or
        air (judge-disk + island + part checks as today), then feed in
        sideways at depth with flank-only engagement - and only fall back to
        the 2-deg helix when no such column passes its checks."""
        ax_hard = disk_top(x, y, offs_fl) > z + corner_r + 0.05
        ax_judge = (k_ax >= 0 and disk_top(x, y, offs_ax) > z + corner_r
                    + 0.05)
        ax_wide = (k_wide >= 0 and disk_top(x, y, offs_wide) > z + corner_r
                   + 0.05)
        wide_fail = False
        if ax_hard or ax_judge or ax_wide:
            if side and prev[2] is not None:
                off = find_shift(x, y, z, force=True, flank=True)
                if off is not None:
                    offset_down(x, y, z, off)
                    stats["n_side_entries"] += 1
                    stats["side_entry_feed_mm"] += math.dist(off, (x, y))
                    return
            if helix_entry(x, y, z, hc, centred=centred or bore is not None,
                           bore=bore):
                helix_n[0] += 1   # BS1a4c: this helix backs an entry credit
                return
            if ax_hard:
                stats["n_axial_plunge"] += 1
                stats.setdefault("axial_pts", []).append(
                    ("hard", round(x, 3), round(y, 3), round(z, 3)))
            else:
                # material only inside the judge-phase disk (a rim sliver the
                # judge MIGHT see, but not under the true flat bottom): try an
                # offset descent; fall back to a straight descent at ramp feed.
                stats["n_axial_suspect"] += 1
                wide_fail = True
        req = disk_top(x, y, offs_rt)
        h = z if req <= -1e8 else max(
            z, min(req + rapid_margin, prev[2] if prev[2] is not None
                   else clearance_z))
        # RT item 1: a long feed stretch means a tall wall stands in the pad
        # ring beside the column - descend on a nearby fully-clear column (G0)
        # and feed the last bit horizontally at depth (side engagement only).
        if prev[2] is not None and (h - z > 3.0 or wide_fail):
            off = find_shift(x, y, z, force=wide_fail)
            if off is not None:
                offset_down(x, y, z, off)
                return
        if wide_fail:
            # RT2: neither a full-size helix nor a verified-clear column was
            # available where the judge's disk sees stock above Z - a straight
            # feed-down here WOULD be an axial plunge. Count it (the run
            # aborts on n_axial_plunge) instead of emitting a judged plunge.
            stats["n_axial_plunge"] += 1
            stats.setdefault("axial_pts", []).append(
                ("wide", round(x, 3), round(y, 3), round(z, 3)))
        if prev[2] is not None and prev[2] > h + 1e-6:
            emit({"g": 0, "x": x, "y": y, "z": round(h, 4)})
        if h > z + 1e-6:
            emit({"g": 1, "x": x, "y": y, "z": z, "f": ramp_feed})
        mill_now(x, y, z)

    def emit(mv):
        x0, y0, z0 = prev
        x0 = mv["x"] if x0 is None else x0
        y0 = mv["y"] if y0 is None else y0
        z0 = mv["z"] if z0 is None else z0
        if mv["g"] == 0:
            # R5: every rapid (retract, lift, traverse) is verified against
            # the LIVE stock model + part: the height must clear max(stock
            # top, part) within tool_r + rapid_margin along the swept path
            # by rapid_margin (the radial pad covers heightfield
            # quantisation - a wall sliver whose cell centres sit just
            # beyond the tool radius can still stand under the flank);
            # otherwise lift to that verified height.
            req = stock.link_top_max([(x0, y0), (mv["x"], mv["y"])],
                                    tool_r + rapid_margin)
            if req > -1e8 and mv["z"] < req + rapid_margin:
                mv = dict(mv, z=round(max(mv["z"], req + rapid_margin), 4))
                stats["n_rapid_bumps"] += 1
            # a rapid that moves in XY while starting BELOW the verified height
            # would climb diagonally through the material it is clearing
            # (Core Front: 1.8 mm into stock); rise vertically first - straight
            # up out of the cut is always clear - then traverse at height
            if (req > -1e8 and z0 < req + rapid_margin - 1e-9
                    and (abs(mv["x"] - x0) > 1e-9 or abs(mv["y"] - y0) > 1e-9)):
                stats["n_rapid_rises"] = stats.get("n_rapid_rises", 0) + 1
                emit({"g": 0, "x": x0, "y": y0, "z": mv["z"]})
                x0, y0, z0 = prev
            # engine-side swept check (never only the end height): a rapid
            # that moves in XY must clear live stock + part by the margin along
            # its whole length, or the run fails here rather than in the judge
            if (abs(mv["x"] - x0) > 1e-9 or abs(mv["y"] - y0) > 1e-9) and \
                    not rapid_swept_clear(stock, (x0, y0, z0),
                                          (mv["x"], mv["y"], mv["z"]),
                                          tool_r + rapid_margin, rapid_margin):
                raise RuntimeError(
                    "rapid from (%.3f, %.3f, %.3f) to (%.3f, %.3f, %.3f) does "
                    "not clear live stock/part by %.2f mm along its length"
                    % (x0, y0, z0, mv["x"], mv["y"], mv["z"], rapid_margin))
        if (mv.get("x") is not None and mv.get("y") is not None
                and mv.get("z") is not None
                and abs(mv["x"] - x0) < 1e-9 and abs(mv["y"] - y0) < 1e-9
                and abs(mv["z"] - z0) < 1e-9):
            return  # zero-length move
        if mv["g"] == 1:
            hf_pts.append((mv["x"], mv["y"], mv["z"]))
        length = math.dist((x0, y0, z0), (mv["x"], mv["y"], mv["z"]))
        if mv["g"] == 0:
            stats["rapid_len"] += length
            if abs(mv["z"] - clearance_z) < 1e-9 and abs(z0 - mv["z"]) > 1e-6:
                stats["n_retracts"] += 1
        elif abs(mv["z"] - z0) > 1e-6:
            stats["plunge_len"] += length
        else:
            stats["cut_len"] += length
        moves.append(mv)
        prev[0], prev[1], prev[2] = mv["x"], mv["y"], mv["z"]


    def retract_to(x, y):
        """RT item 2: lift to the MINIMUM verified-clear height over the link
        (max live material within tool_r + rapid_margin along the swept path
        + margin, R5 criterion), never to full clearance unless the link
        really needs it; the horizontal rapid stays at that height."""
        px = prev[0] if prev[0] is not None else x
        py = prev[1] if prev[1] is not None else y
        req = stock.link_top_max([(px, py), (x, y)], tool_r + rapid_margin)
        h = clearance_z if req <= -1e8 else \
            min(clearance_z, max(req + rapid_margin, prev[2]))
        emit({"g": 0, "x": px, "y": py, "z": round(h, 4)})
        emit({"g": 0, "x": x, "y": y, "z": round(h, 4)})

    def enter_at(x, y, z, hc, side=False, centred=False, bore=None):
        """Get the tool to (x, y, Z) cutting depth, keeping it down when the
        stock model says the way is clear. RP2_1 side=True: OPEN region -
        feed_down tries the verified side entry before any helix."""
        px = prev[0] if prev[0] is not None else x
        py = prev[1] if prev[1] is not None else y
        pz = prev[2]
        # 1) straight tool-down link at cutting Z (clear in BOTH the stock
        # model and the exact forbidden islands - the hf can miss steep walls)
        if corridor_ok((px, py), (x, y)) and stock.link_clear([(px, py), (x, y)], z) \
                and stock.rise_clear(px, py, pz, z):
            feed_down(px, py, z)
            emit({"g": 1, "x": x, "y": y, "z": z, "f": cut_feed})
            stats["n_tooldown_links"] += 1
            return
        # 2) traverse at Z + lift, short plunge at the far end
        if corridor_ok((px, py), (x, y)) and \
                stock.link_clear([(px, py), (x, y)], z + lift) and \
                stock.rise_clear(px, py, pz, z + lift):
            if abs(pz - (z + lift)) > 1e-6:
                if pz > z + lift:
                    feed_down(px, py, z + lift)
                else:
                    emit({"g": 1, "x": px, "y": py, "z": z + lift,
                          "f": ramp_feed})
            emit({"g": 0, "x": x, "y": y, "z": z + lift})
            feed_down(x, y, z, side=side, centred=centred)
            stats["n_tooldown_links"] += 1
            return
        # 3) RP2_1 side-first (OPEN region): find the verified clear column
        # BEFORE retracting, then lift straight up at the current point and
        # traverse directly to it - no detour over (x, y) first; the entry
        # descent + sideways feed-in happen at depth in offset_down.
        if side:
            off = find_shift(x, y, z, force=True, flank=True)
            if off is not None:
                req = stock.link_top_max([(px, py), off],
                                        tool_r + rapid_margin)
                h = clearance_z if req <= -1e8 else min(
                    clearance_z, max(req + rapid_margin, pz if pz else
                                    clearance_z))
                emit({"g": 0, "x": px, "y": py, "z": round(h, 4)})
                offset_down(x, y, z, off)
                stats["n_side_entries"] += 1
                return
        # 4) retract (minimum verified-clear height), then helix or a
        # G0-shortened descent; never an axial plunge into stock (RT item 3).
        # feed_down itself diverts long air descents to a nearby clear column.
        retract_to(x, y)
        feed_down(x, y, z, hc, centred=centred, bore=bore)

    def mill_now(x, y, z_bot):
        """Vertical plunge: the tool physically clears its footprint down to
        z_bot, so update the stock model immediately at the LOW end - the
        next link check in the same region sees the real floor."""
        stock.mill_segment(x, y, x, y, z_bot, tool_r, corner_r)

    def descend_feed(p0, i0):
        """RP2_1 reporting: descending G1 feed length (mm) emitted since move
        index i0, starting at point p0=(x, y, z) (None-safe)."""
        tot = 0.0
        a = p0
        for mv in moves[i0:]:
            b = (mv["x"], mv["y"], mv["z"])
            if None not in a and mv["g"] == 1 and b[2] < a[2] - 1e-9:
                tot += math.dist(a, b)
            a = b
        return tot

    zi = 0
    for z in order:
        del hf_pts[:]
        mandatory = round(z, 4) in mand
        mask = stock.region_mask(z, axl, 0.0 if mandatory else min_rest,
                                leave_margin=leave + 0.4)
        area_mm2 = stock.region_area(mask)
        if area_mm2 < min_level_area and not mandatory:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1),
                                   "n_regions": 0, "n_clip_breaks": 0})
            continue
        grown = stock.dilate(mask, tool_r + leave + 0.5)
        # Task RS: territory (and with it the Adaptive2d outers and the
        # hug-ring filter) is clipped to the stock box + tool radius, so no
        # level region can follow a padded --hf / CL grid past the stock.
        grown &= centre_zone
        # NB: do NOT pre-carve the part footprint (pz) out of `grown`:
        # Adaptive2d offsets the outer inward by tool_r + leave AND the island
        # loops outward by the same amount; carving pz by tool_r + leave as
        # well would double-offset and erase every pocket whose floor-to-wall
        # span is under 2x(tool_r + leave) (the Z27 pocket vanishing at
        # 27.381). Walls are guarded by this level's drop-cutter islands
        # (isl_in), and stock.region_mask already excludes pz cells from the
        # territory core.
        outers, holes = stock.contours(grown)
        t0 = time.time()
        islands, Fm = level_islands(surf, cutter_big, Zg, gxs, gys, z, axl,
                                    threads=threads)
        t_isl = time.time() - t0
        stats["t_islands"] += t_isl
        # ground-truth clearance oracle for THIS level: the refined forbidden
        # loops (centres must stay OUTSIDE them; they never under-cover F) -
        # the hf model can under-report steep walls by ~1 cell
        isl_ok = island_clear_fn(islands, 0.01)
        # stricter oracle for points WE choose (entries, bridge chords): the
        # allowance gate demands >= 0.025 mm outside the forbidden loops, so
        # self-picked centres validate at 0.03 to stay clear of the bound.
        isl_ok3 = island_clear_fn(islands, 0.03)
        # Adaptive2d geometry islands: F eroded by disk(R - margin), so the
        # tool_r + leave offset Adaptive2d applies keeps centres outside F
        isl_in = _loops_from_mask(_erode(Fm, erode_r, pitch), gxs, gys) \
            if Fm.any() else []
        def rp2_open(res):
            """RP2_0: OPEN iff a cutter centre q exists with (a) the full
            tool disk + 0.5 mm margin over already-cleared/air material at
            level Z (max(top, part) <= Z + 0.05 within tool_r + 0.5: the
            tool descends in cleared air/stock, no axial removal, contact
            gap >= tool dia + 2 x 0.5), (b) this region's still-standing
            cutting material (within tool_r of its cutting paths, top >
            Z + 0.05 in the LIVE model) within tool_r + 2.0 mm of q, so a
            short sideways feed engages it with the tool flank only, and
            (c) q island-legal at 0.03. Returns (open, n_candidates)."""
            pts2 = [p for (k, p) in res["paths"]
                    if k == "cutting" for p in p]
            if len(pts2) < 2:
                return False, 0
            xs = [p[0] for p in pts2]
            ys = [p[1] for p in pts2]
            mgn = tool_r + 3.5
            i0 = max(stock._ci(min(xs) - mgn), 0)
            i1 = min(stock._ci(max(xs) + mgn) + 2, stock.nx)
            j0 = max(stock._cj(min(ys) - mgn), 0)
            j1 = min(stock._cj(max(ys) + mgn) + 2, stock.ny)
            if i0 >= i1 or j0 >= j1:
                return False, 0
            Ms = np.maximum(stock.top[j0:j1, i0:i1],
                           stock.part[j0:j1, i0:i1])
            pm = np.zeros(Ms.shape, dtype=bool)
            iiL, jjL = [], []
            for (kind, pp) in res["paths"]:
                if kind != "cutting" or not pp:
                    continue
                for (xa, ya), (xb, yb) in zip(pp[:-1], pp[1:]):
                    n = max(1, int(math.hypot(xb - xa, yb - ya) / 0.4))
                    for t in range(n + 1):
                        iiL.append(int((xa + (xb - xa) * t / n
                                      - stock.x0) / c_sc))
                        jjL.append(int((ya + (yb - ya) * t / n
                                      - stock.y0) / c_sc))
            iiA = np.clip(np.asarray(iiL, dtype=int) - i0,
                          0, Ms.shape[1] - 1)
            jjA = np.clip(np.asarray(jjL, dtype=int) - j0,
                          0, Ms.shape[0] - 1)
            pm[jjA, iiA] = True
            U = _rp2_dilate(pm, RP2_OFF_U) & (Ms > z + 0.05)
            if not U.any():
                return True, 1   # region cuts nothing standing: open
            band = _rp2_dilate(U, RP2_OFF_C)
            T = _rp2_shiftmax(Ms, RP2_OFF_D) <= z + 0.05
            cand = band & T
            nq = int(cand.sum())
            if not nq:
                return False, 0
            jjc, iic = np.nonzero(cand)
            stq = max(1, nq // 400)
            qs = [(stock.x0 + (int(iic[t]) + i0 + 0.5) * c_sc,
                  stock.y0 + (int(jjc[t]) + j0 + 0.5) * c_sc)
                  for t in range(0, nq, stq)]
            return any(isl_ok3(qs)), nq

        # ---- RP0 instrumentation (RT_RP=1): safe region vs Adaptive2d input
        rp = None
        if _RP:
            c_sc0 = stock.cell
            xs_s = stock.x0 + (np.arange(stock.nx) + 0.5) * c_sc0
            ys_s = stock.y0 + (np.arange(stock.ny) + 0.5) * c_sc0
            ii_s = np.floor((xs_s - gxs[0]) / pitch + 0.5).astype(int)
            jj_s = np.floor((ys_s - gys[0]) / pitch + 0.5).astype(int)
            Fs = np.zeros((stock.ny, stock.nx), dtype=bool)
            sel_i = (xs_s >= gxs[0] - 0.5 * pitch) & \
                    (xs_s <= gxs[-1] + 0.5 * pitch)
            sel_j = (ys_s >= gys[0] - 0.5 * pitch) & \
                    (ys_s <= gys[-1] + 0.5 * pitch)
            if sel_i.any() and sel_j.any():
                Fs[np.ix_(sel_j, sel_i)] = \
                    (np.isfinite(Zg) & (Zg > z - axl + 0.005))[
                        np.ix_(jj_s[sel_j], ii_s[sel_i])]
            SAFE0 = centre_zone & ~Fs           # legal centres (raw)
            MAT = stock.dilate(mask, tool_r)    # centres reaching this level
            SAFE = SAFE0 & MAT                  # legal AND relevant

            def _ero(m, r):
                return ~stock.dilate(~m, r)
            inp_c = _ero(grown, tool_r + leave)  # centres allowed by the outer
            over = inp_c & ~SAFE0                # planned but illegal -> clips
            under = SAFE & ~inp_c                # legal+relevant, outer misses
            per_s = float((SAFE & ~_ero(SAFE, c_sc0)).sum()) * c_sc0
            per_i = float((inp_c & ~_ero(inp_c, c_sc0)).sum()) * c_sc0
            if os.environ.get("RT_RP_DBG"):
                _jj, _ii = np.nonzero(SAFE)
                _bj, _bi = np.nonzero(inp_c)
                print("RPDBG z=%.3f SAFE n=%d x[%.1f,%.1f] y[%.1f,%.1f]"
                      " INP n=%d x[%.1f,%.1f] y[%.1f,%.1f] Fm n=%d"
                      " overlap=%d" % (
                          z, _jj.size, xs_s[_ii].min() if _ii.size else 0,
                          xs_s[_ii].max() if _ii.size else 0,
                          ys_s[_jj].min() if _jj.size else 0,
                          ys_s[_jj].max() if _jj.size else 0,
                          _bi.size, xs_s[_bi].min() if _bi.size else 0,
                          xs_s[_bi].max() if _bi.size else 0,
                          ys_s[_bj].min() if _bj.size else 0,
                          ys_s[_bj].max() if _bj.size else 0,
                          int(Fm.sum()), int((inp_c & SAFE).sum())),
                      flush=True)
                _f = 8
                for _j in range(0, stock.ny, _f):
                    print("".join(" SF*"[
                        (2 if SAFE[_j, _i] else 0) + (1 if inp_c[_j, _i]
                                                      else 0)]
                        for _i in range(0, stock.nx, _f))
                                  .rstrip("*"), flush=True)
            rp = {"z": round(z, 3), "n_islands": len(islands),
                  "safe_mm2": round(float(SAFE.sum()) * c_sc0 * c_sc0, 1),
                  "safe_per_mm": round(per_s, 1),
                  "input_c_mm2": round(float(inp_c.sum()) * c_sc0 * c_sc0, 1),
                  "input_c_per_mm": round(per_i, 1),
                  "over_mm2": round(float(over.sum()) * c_sc0 * c_sc0, 1),
                  "under_mm2": round(float(under.sum()) * c_sc0 * c_sc0, 1),
                  "breaks": {}, "bridged": {}, "break_len": {},
                  "bridge_len": {}, "clip_len_mm": 0.0,
                  "bridge_len_mm": 0.0, "n_hug": 0, "a2d_cut_len_mm": 0.0,
                  "n_links_in": 0, "dropped_outers": 0, "dropped_holes": 0}
            rp_il = [lp for lp in islands
                     if not (len(lp) == 4 and abs(lp[0][0] - gxs[0]) < 1e-6
                             and abs(lp[0][1] - gys[0]) < 1e-6)]
            rp_ok0 = island_clear_fn(rp_il, 0.0)

            def rp_cat(bad):
                """classify a run of clipped points -> category string"""
                P = np.asarray(bad, dtype=float)
                ii = np.clip(((P[:, 0] - stock.x0) / c_sc0).astype(int),
                             0, stock.nx - 1)
                jj = np.clip(((P[:, 1] - stock.y0) / c_sc0).astype(int),
                             0, stock.ny - 1)
                outside_box = ~centre_zone[jj, ii]
                inside_il = [not v for v in rp_ok0(bad)]
                n_in = sum(1 for a, b2 in zip(inside_il, outside_box)
                          if a and not b2)
                n_box = int(outside_box.sum())
                n_m = len(bad) - n_in - n_box
                if n_in >= max(n_box, n_m):
                    return "island/part-offset"
                if n_box >= n_m:
                    return "stock box/RS"
                return "allowance margin(<0.01)"

            def rp_poly(pl):
                return sum(math.dist(pl[k], pl[k + 1])
                          for k in range(len(pl) - 1))

        def corridor_ok(p0, p1):
            if not islands:
                return True
            L = math.dist(p0, p1)
            n = max(2, int(L / 0.4) + 1)
            pts = [(p0[0] + (p1[0] - p0[0]) * t / (n - 1),
                    p0[1] + (p1[1] - p0[1]) * t / (n - 1)) for t in range(n)]
            if not all(isl_ok(pts)):
                return False
            # R4: also test segment midpoints - a thin island tip can slip
            # between 0.4 mm samples on a long link (the level-29.906 ring
            # link crossing the boss fillet corner at (-17.5, 13.9))
            mids = [((p0[0] + (p1[0] - p0[0]) * (t + 0.5) / (n - 1),
                     p0[1] + (p1[1] - p0[1]) * (t + 0.5) / (n - 1)))
                    for t in range(n - 1)]
            return all(isl_ok(mids))

        # drop clearance-ring outers: a territory component that passes within
        # tool_r+leave of an island input loop usually has no room for the tool
        # inside it, and Adaptive2d answers by offsetting it right onto the
        # island loop (violations at 43.815 and 41.91). But keep the outer when
        # the cells inside it that are OUTSIDE this level's forbidden region F
        # can still host cutter centres (a wide plateau next to a boss whose
        # clearance ring clips one edge must still get its floor machined -
        # the Z27 pocket at 27.381). Cells beyond the CL grid have no islands
        # (F closes strictly inside the padded grid), so they count as usable.
        rp_n_out0 = len(outers) if _RP else 0
        if isl_in and outers:
            ip = np.asarray([p for lp in isl_in for p in lp], dtype=float)
            min_d = tool_r + leave + 0.5
            min_usable = 0.6 * math.pi * (tool_r + leave) ** 2
            keep = []
            for lp in outers:
                P = np.asarray(lp, dtype=float)
                d2 = ((P[:, None, 0] - ip[None, :, 0]) ** 2
                     + (P[:, None, 1] - ip[None, :, 1]) ** 2)
                if float(d2.min()) >= min_d * min_d:
                    keep.append(lp)
                    continue
                x, y = P[:, 0], P[:, 1]
                area2 = abs(float(np.dot(x, np.roll(y, -1))
                                 - np.dot(y, np.roll(x, -1))))
                if area2 >= 3000.0:   # wide territory: keep, holes guard it
                    keep.append(lp)
                    continue
                if _usable_area(lp, Fm, gxs, gys) >= min_usable:
                    keep.append(lp)
            outers = keep
            if _RP:
                rp["dropped_outers"] = rp_n_out0 - len(outers)
        # keep only genuine cleared-pocket holes: a hole whose interior still
        # has stock above the level is a part footprint (excluded cells with
        # part > Z) - passing it next to the coincident island loop breaks
        # Adaptive2d (probe_g_duploop: centres end up inside the hole). R2:
        # the feature is guarded by this level's drop-cutter islands instead.
        keep_holes = []
        for hp in holes:
            cx = sum(p[0] for p in hp) / len(hp)
            cy = sum(p[1] for p in hp) / len(hp)
            if stock.top_at(cx, cy) <= z + axl + 0.05:
                keep_holes.append(hp)
        if _RP:
            rp["dropped_holes"] = len(holes) - len(keep_holes)
        holes = keep_holes
        if not outers:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1),
                                   "n_regions": 0, "n_clip_breaks": 0})
            continue
        t0 = time.time()
        regions = _run_a2d(outers, holes, isl_in, tool_r, leave, stepover,
                           tolerance, keep_tool_down, helix_dia)
        n_a2d = len(regions)  # HR1: everything from here on is hug rings
        if _RP:
            rp["a2d_cut_len_mm"] = round(sum(
                rp_poly(p) for res in regions for (k, p) in res["paths"]
                if k == "cutting"), 1)
            rp["n_links_in"] = sum(
                1 for res in regions for (k, _p) in res["paths"]
                if k != "cutting")
            rp["_n_a2d"] = len(regions)
        # R4: wall-hugging rings close the margin-wide rest band + corner
        # chunks Adaptive2d cannot reach (its islands are pre-eroded).
        # BS1a3: the channel check runs INSIDE the emit loop, at the -1
        # sentinel, once this level's a2d passes are milled into the LIVE stock.
        rings = hug_regions(islands, grown, stock, isl_ok,
                           eps=max(0.5 * tolerance, 0.03))
        regions.extend(rings)
        if _RP:
            rp["n_hug"] = len(regions) - rp.pop("_n_a2d")
        t_a2d = time.time() - t0
        stats["t_adaptive"] += t_a2d
        if not regions:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1),
                                   "n_islands": len(islands),
                                   "n_regions": 0, "n_clip_breaks": 0})
            continue

        # RT travel: order regions nearest-neighbour from the current tool
        # position and enter each at its nearest island-valid candidate, so
        # inter-region rapids stay short instead of following a2d's order.
        # HR1/BS1a3: all Adaptive2d regions first (NN among themselves); the
        # channel-clear trochoids and ALL hug-ring regions are ordered at the
        # -1 sentinel inside the emit loop, once this level's a2d passes are
        # milled into the LIVE stock - a ring must always be the thin skim
        # R4 intended, never slot full-width ahead of its level's passes.
        cand = []
        for res in regions:
            fc = next((p for (k, p) in res["paths"]
                       if k == "cutting" and p), None)
            pts0 = [p for p in (res["start"], fc[0] if fc else None) if p]
            ok = [p for p in pts0 if isl_ok([p])[0]]
            if not ok:
                g0 = next(((p, m) for (k, p) in res["paths"] if k == "cutting"
                          for m in [isl_ok(p)] if any(m)), (None, None))
                if g0[0] is not None:
                    ok = [g0[0][g0[1].index(True)]]
            cand.append(ok)
        order = []
        pos = (prev[0], prev[1]) if prev[0] is not None else None
        sub, pos = _nn_order([k for k, c in enumerate(cand) if c
                              and k < n_a2d], cand, pos)
        order.extend(sub)
        order.append(-1)        # sentinel: the band phase is detected here
        nreg = 0
        cb0 = stats["n_clip_breaks"]
        rp_lk0 = ({k: stats[k] for k in ("n_lifts", "n_notclear_links",
                                         "n_feed_links", "n_air_links",
                                         "n_deep_links", "n_retracts")}
                  if _RP else None)
        level_pts = []  # (x, y, tag) cutter centres cutting at this level's Z
        region_dump = []
        for idx, k in enumerate(order):   # order grows by one phase at the -1
            if k < 0:                    # sentinel: every a2d region of this
                # level is emitted and milled into the LIVE stock - detect the
                # full-width ring stretches against it now, then order bands
                # (NN) and rings (NN from the last band).
                from engine.band import (channel_regions, _simulate, AE_SS,
                                       AE_SPIKE, shrink_ladder, bore_context,
                                       _split_at_jumps)
                with bore_context(lambda p, zz: _bore_pred(
                        isl_ok, centre_zone, stock, p[0], p[1], tool_r)):
                    bands = channel_regions(rings, stock, isl_ok3, z, tool_r,
                                          leave, stock.cell, stats)
                base = len(regions)
                regions.extend(bands)
                for res in bands:                 # candidate rule as above
                    fc = next((p for (k, p) in res["paths"]
                              if k == "cutting" and p), None)
                    pts0 = [p for p in (res["start"], fc[0] if fc else None)
                            if p]
                    ok = [p for p in pts0 if isl_ok([p])[0]]
                    if not ok:
                        g0 = next(((p, m) for (k, p) in res["paths"]
                                  if k == "cutting"
                                  for m in [isl_ok(p)] if any(m)),
                                 (None, None))
                        if g0[0] is not None:
                            ok = [g0[0][g0[1].index(True)]]
                    cand.append(ok)
                if _RP:
                    rp["n_hug"] += len(bands)
                sub, pos = _nn_order([k for k in range(base, len(cand))
                                     if cand[k]], cand, pos)
                order.extend(sub)
                sub, pos = _nn_order([k for k in range(n_a2d, base)
                                     if cand[k]], cand, pos)
                order.extend(sub)
                continue
            res = regions[k]
            nreg += 1
            if prev[0] is None:
                entry = cand[k][0]
            else:
                # DT1: stable tie-break (distance, x, y) - an exact distance
                # tie must not follow candidate list order.
                entry = min(cand[k], key=lambda p: (math.dist(
                    (prev[0], prev[1]), p), p[0], p[1]))
            if res.get("bore"):
                entry = res["bore"][:2]   # BS1a4d4: enter at the stored start
            rp2_flag, rp2_cand = rp2_open(res)
            pxy0 = (prev[0], prev[1])
            pz0 = prev[2]
            i0m = len(moves)
            h0 = helix_n[0]
            enter_at(round(entry[0], 4), round(entry[1], 4), z, res["helix"],
                     side=bool(rp2_flag), bore=res.get("bore"))
            de = descend_feed(pxy0 + (pz0,), i0m)
            # BS1a4c (f3f2165): a credited BAND start is backed at emit only
            # by an emitted helix or live-clear disk; else credit-0 re-check,
            # or not emitted. BS1a4c-fix: never a helix AFTER enter_at - the
            # tool is already at depth there (gouged); enter_at's own ladder
            # (link / side / helix, each CL-checked) is the only entry.
            drop_cut = False
            if ((res.get("credit") or 0.0) > 1e-9 and helix_n[0] == h0) \
                    or res.get("replan0"):   # BS1a4d4: plan0_split piece
                pts_c, q4 = res["paths"][0][1], tuple(res["start"])
                if res.get("replan0") or not stock.link_clear([q4, q4], z):
                    rb = res.get("replan0") == 2 and helix_n[0] > h0
                    ew0 = _simulate(pts_c, stock, z, tool_r, stock.cell,
                                    res["bore"][4] + tool_r if rb else 0.0,
                                    bore_xy=res["bore"][2:] if rb else None)
                    if ew0 and max(ew0) <= AE_SPIKE and sorted(
                            ew0)[max(0, int(0.95 * len(ew0)) - 1)] <= AE_SS:
                        act = "replan0_ok"
                    else:
                        # BS1a4d (a0): Fix 1's lightest option - shrink ladder
                        # at credit 0 on the LIVE stock vs drop-ring, same
                        # rank; recorded in BOTH lists. Same prep as at plan
                        # time (isl_ok3 points, split at jumps): only a first
                        # piece joining q4 by a segment-checked chord emits.
                        opt, pnew, wn, ba, _g = shrink_ladder(
                            res["seg"], stock, z, tool_r, stock.cell, 0.0,
                            (res["dropkey"], "drop_ring", None, []))
                        act, drop_cut = "replan0_drop", True
                        if pnew is not None:
                            g2 = isl_ok3([(round(a, 4), round(b, 4))
                                        for (a, b) in pnew])
                            pp = [q4] + [(round(a, 4), round(b, 4))
                                       for (a, b), ok in zip(pnew, g2) if ok]
                            pcs = _split_at_jumps(isl_ok3, pp)
                            if len(pcs[0]) >= 4:
                                res["paths"][0][1] = pcs[0]
                                act, drop_cut = "replan0_" + opt, False
                            else:
                                # BS1a4d6 (a): a piece that cannot rejoin q4
                                # is NOT dropped - its lightest option goes
                                # out as its OWN region, entered through its
                                # own enter_at ladder (the only entry), never
                                # at the failing load; its stock is cut here,
                                # never left for the ring.
                                own = next((pc for pc in pcs[1:]
                                            if len(pc) >= 4), None)
                                if own is not None:
                                    i0o = len(moves)
                                    p0o = (prev[0], prev[1], prev[2])
                                    enter_at(own[0][0], own[0][1], z, None,
                                             side=bool(rp2_flag))
                                    stats["reentry_feed_mm"] += \
                                        descend_feed(p0o, i0o)
                                    level_pts.append((own[0][0], own[0][1],
                                                      "own r%d" % nreg))
                                    res["paths"][0][1] = own
                                    act, drop_cut = "replan0_" + opt, False
                        stats["failed_region_emitted"].append(
                            {"x": q4[0], "y": q4[1], "z": round(z, 3),
                             "area": round(ba, 2),
                             "option": opt if not drop_cut else "drop_ring",
                             "max_ae": round(max(wn), 3) if wn else None})
                    stats["credit_fallback"].append(
                        (q4[0], q4[1], round(z, 3), act))
            stats["entry_feed_mm"] += de
            if de > 1e-6:
                stats["n_entry_descends"] += 1
            if _RP2:
                seq = [pxy0 + (pz0, 0)] + [(mv["x"], mv["y"], mv["z"],
                                           mv["g"]) for mv in moves[i0m:]]
                L2 = 0.0
                zhi = -1e9
                for a, b in zip(seq[:-1], seq[1:]):
                    if None not in (a[0], a[1], a[2], b[0], b[1], b[2]):
                        if b[3] == 1 and b[2] < a[2] - 1e-9:
                            L2 += math.dist(a, b)
                        zhi = max(zhi, a[2], b[2])
                    if b[3] == 1 and abs(b[2] - z) <= 1e-6:
                        break      # first horizontal cut at Z: entry done
                rp2_regions.append({"z": round(z, 3), "r": nreg,
                                   "open": bool(rp2_flag), "cand": rp2_cand,
                                   "entry_mm": round(L2, 1),
                                   "dz_mm": round(max(zhi - z, 0.0), 2)})

            level_pts.append((round(entry[0], 4), round(entry[1], 4),
                             "start r%d" % nreg))
            region_dump.append({"start": entry, "helix": res["helix"],
                              "paths": [[k, len(p)] for (k, p) in res["paths"]]})
            for (kind, pts) in res["paths"]:
                if kind == "cutting" and not drop_cut:  # BS1a4c: unbacked
                    good = isl_ok(pts)
                    i = 0
                    gap = False
                    bridge = None
                    rp_g0 = None
                    while i < len(pts):
                        if not good[i]:
                            gap = True
                            if _RP and rp_g0 is None:
                                rp_g0 = i
                            i += 1
                            continue
                        if prev[2] is None or abs(prev[2] - z) > 1e-6 or gap:
                            # tool is up (after a notclear link or a clip
                            # break) or the path skipped over forbidden ground
                            # (clip break at z): bridge short slivers whose
                            # straight chord is itself island-valid, otherwise
                            # re-enter at this point via the corridor-checked
                            # entry - don't dive across the gap blindly.
                            d_chord = math.dist((prev[0], prev[1]), pts[i]) \
                                if prev[2] is not None and \
                                abs(prev[2] - z) <= 1e-6 else None
                            bridge = None
                            if d_chord is not None and 1e-9 < d_chord <= \
                                    clip_bridge_mm:
                                ns = max(2, int(math.ceil(d_chord / 0.5)))
                                chord = [(prev[0] + (pts[i][0] - prev[0]) * t / ns,
                                        prev[1] + (pts[i][1] - prev[1]) * t / ns)
                                       for t in range(1, ns)]
                                # the forbidden loop between the runs is a
                                # quantisation sliver only if every chord
                                # sample keeps the same island clearance the
                                # unbroken path would have (isl_ok): no gouge,
                                # and the chord removes MORE material than the
                                # detour it replaces, never less.
                                if all(isl_ok3(chord + [tuple(pts[i])])) and \
                                        lnk_cut_ok(stock, [(prev[0], prev[1])] +
                                                 chord + [tuple(pts[i])], z,
                                                 "brdg"):
                                    bridge = chord
                            if bridge is not None:
                                stats["n_clip_bridges"] += 1
                                if _RP and rp_g0 is not None:
                                    _bad = pts[rp_g0:i]
                                    _cat = rp_cat(_bad)
                                    _rem = rp_poly([(prev[0], prev[1])] + _bad +
                                                [tuple(pts[i])]) - d_chord
                                    rp["bridged"][_cat] = \
                                        rp["bridged"].get(_cat, 0) + 1
                                    rp["bridge_len"][_cat] = \
                                        round(rp["bridge_len"].get(_cat, 0.0) +
                                              _rem, 2)
                                    rp["bridge_len_mm"] += _rem
                                rp_g0 = None
                                gap = False
                            else:
                                stats["n_clip_breaks"] += 1
                                if _RP:
                                    if rp_g0 is not None:
                                        _bad = pts[rp_g0:i]
                                        _cat = rp_cat(_bad)
                                        if prev[2] is None or \
                                                abs(prev[2] - z) > 1e-6:
                                            _cat += " + tool up"
                                        _rem = rp_poly([(prev[0], prev[1])] +
                                                    _bad + [tuple(pts[i])]) - \
                                            (d_chord if d_chord is not None
                                             else math.dist((prev[0], prev[1]),
                                                          pts[i]))
                                    else:
                                        _cat = "link split (tool up, no clip)"
                                        _rem = 0.0
                                    rp["breaks"][_cat] = \
                                        rp["breaks"].get(_cat, 0) + 1
                                    rp["break_len"][_cat] = \
                                        round(rp["break_len"].get(_cat, 0.0) +
                                              _rem, 2)
                                    rp["clip_len_mm"] += _rem
                                rp_g0 = None
                                if prev[2] is None or abs(prev[2] - z) > 1e-6 or \
                                        d_chord is None or d_chord > 0.6:
                                    p0r = (prev[0], prev[1], prev[2])
                                    i0r = len(moves)
                                    enter_at(round(pts[i][0], 4),
                                           round(pts[i][1], 4), z, None,
                                           side=bool(rp2_flag))
                                    der = descend_feed(p0r, i0r)
                                    stats["reentry_feed_mm"] += der
                                    if der > 1e-6:
                                        stats["n_reentry_descends"] += 1
                                    level_pts.append((round(pts[i][0], 4),
                                                    round(pts[i][1], 4),
                                                    "reentry r%d" % nreg))
                                gap = False
                        j = i
                        while j + 1 < len(pts) and good[j + 1]:
                            j += 1
                        run = list(bridge) if bridge else []
                        bridge = None
                        run += [(round(x, 4), round(y, 4)) for (x, y)
                               in pts[i:j + 1]]
                        for (x, y) in run:
                            emit({"g": 1, "x": x, "y": y, "z": z,
                                  "f": cut_feed})
                            level_pts.append((x, y, "cut r%d" % nreg))
                        stock.mill_path(run, z, tool_r, corner_r)
                        i = j + 1
                    if _RP and rp_g0 is not None:
                        _cat = rp_cat(pts[rp_g0:]) + " (tail dropped)"
                        rp["breaks"][_cat] = rp["breaks"].get(_cat, 0) + 1
                        rp_g0 = None
                elif kind == "linkclear":
                    land = (round(pts[-1][0], 4), round(pts[-1][1], 4))
                    corridor = [(round(x, 4), round(y, 4)) for (x, y) in pts]
                    # RP1(a): an Adaptive2d link that stays over CLEARED stock
                    # at cutting depth is an at-depth link: verified against the
                    # LIVE stock model (link_clear at z, dense cell sampling) and
                    # the part (corridor_ok: this level's refined forbidden loops,
                    # 0.4 mm samples + midpoints). Emit it as a feed traverse at
                    # Z - the tool stays down, no R5 rapid bump can leave it up,
                    # and the next cutting run continues without a link split or
                    # a re-entry descent. Anything failing these checks takes the
                    # lift/retract path exactly as before.
                    if prev[2] is not None and abs(prev[2] - z) <= 1e-6 and \
                            all(isl_ok3(corridor)) and \
                            all(corridor_ok(a, b) for a, b
                                in zip(corridor[:-1], corridor[1:])) and \
                            stock.link_clear(corridor, z) and \
                            stock.link_clear(corridor, z + lift) and \
                            not _strip_engage(stock, corridor, z, tool_r) > 2.438:
                        stats["n_deep_links"] += 1
                        for (x, y) in corridor:
                            if x == prev[0] and y == prev[1]:
                                continue
                            emit({"g": 1, "x": x, "y": y,
                                  "z": round(z, 4), "f": cut_feed})
                            level_pts.append((x, y, "dlink r%d" % nreg))
                        stock.mill_path(corridor, z, tool_r, corner_r)
                        continue
                    if os.environ.get("RT_DEBUG"):
                        _dd = math.dist((prev[0], prev[1]), land)
                        _cl = sum(math.dist(corridor[i], corridor[i + 1])
                                 for i in range(len(corridor) - 1))
                        _ns = max(2, int(_dd / 0.5))
                        _ch = [(prev[0] + (land[0] - prev[0]) * t / _ns,
                                prev[1] + (land[1] - prev[1]) * t / _ns)
                               for t in range(1, _ns)]
                        _ok = all(isl_ok(_ch + [land]))
                        _r = stats.setdefault("_lnk", [0, 0, 0.0, 0.0, 0.0])
                        _r[0] += 1
                        _r[1] += 1 if _ok else 0
                        _r[2] += _dd
                        _r[3] += _cl
                        if _ok and _dd <= stepover * tool_r * 2 * 6.0 / 6.0 + 0.5:
                            _r[4] += _dd
                    top = (stock.link_top_max(corridor, tool_r)
                          if prev[2] is not None else -1e9)
                    wide = (top > z + 0.05 and _strip_engage(
                        stock, corridor, z, tool_r) > 2.438)
                    if prev[2] is not None and abs(prev[2] - z) <= 1e-6 and \
                            all(isl_ok(corridor)) and \
                            stock.link_clear(corridor, z + lift) and \
                            math.dist(corridor[0], land) <= feed_link_max \
                            and not wide and (top <= z + 0.05 or lnk_cut_ok(
                                stock, corridor, z, "flnk")):
                        # RT items 1+2: the corridor is island-clear and no
                        # material stands above z + lift. Where it shears only
                        # a THIN strip of stock this level may remove, feed
                        # across at cutting height (no lift at all); where it
                        # spans only already-cut ground, traverse at G0 just
                        # above the floor - emit()'s R5 check still raises it
                        # to the verified pad-clear height wherever a wall is
                        # near. RT2: a corridor crossing a WIDE face at z is a
                        # run of full-width horizontal moves (p99 spike) - it
                        # fails the `not wide` gate above and takes the lift.
                        if top > z + 0.05:
                            stats["n_feed_links"] += 1
                            for (x, y) in corridor:
                                if x == prev[0] and y == prev[1]:
                                    continue
                                emit({"g": 1, "x": x, "y": y,
                                      "z": round(z, 4), "f": cut_feed})
                                level_pts.append((x, y, "flink r%d" % nreg))
                            stock.mill_path(corridor, z, tool_r, corner_r)
                        else:
                            stats["n_air_links"] += 1
                            for (x, y) in corridor:
                                if x == prev[0] and y == prev[1]:
                                    continue
                                emit({"g": 0, "x": x, "y": y,
                                      "z": round(z, 4)})
                                level_pts.append((x, y, "alink r%d" % nreg))
                        continue
                    if not isl_ok([land])[0] or \
                            not stock.link_clear(corridor, z + lift):
                        # landing point or the lift corridor is not actually
                        # clear of stock/islands: retract (minimum verified
                        # height, RT item 2) and let the next cutting run
                        # re-enter via enter_at
                        stats["n_notclear_links"] += 1
                        px, py = prev[0], prev[1]
                        req = stock.link_top_max([(px, py), land],
                                                tool_r + rapid_margin)
                        h = clearance_z if req <= -1e8 else \
                            min(clearance_z, max(req + rapid_margin, prev[2]))
                        emit({"g": 0, "x": px, "y": py, "z": round(h, 4)})
                        emit({"g": 0, "x": land[0], "y": land[1],
                              "z": round(h, 4)})
                        continue
                    stats["n_lifts"] += 1
                    lift_h = z + lift
                    emit({"g": 0, "x": prev[0], "y": prev[1],
                          "z": round(lift_h, 4)})
                    for (x, y) in pts[:-1]:
                        emit({"g": 0, "x": round(x, 4), "y": round(y, 4),
                              "z": round(lift_h, 4)})
                    emit({"g": 0, "x": round(pts[-1][0], 4),
                          "y": round(pts[-1][1], 4), "z": round(lift_h, 4)})
                    p0l = (prev[0], prev[1], prev[2])
                    i0l = len(moves)
                    feed_down(round(pts[-1][0], 4), round(pts[-1][1], 4), z,
                             side=bool(rp2_flag))
                    del_ = descend_feed(p0l, i0l)
                    stats["reentry_feed_mm"] += del_
                    if del_ > 1e-6:
                        stats["n_reentry_descends"] += 1
                    level_pts.append((round(pts[-1][0], 4),
                                     round(pts[-1][1], 4),
                                     "liftland r%d" % nreg))
                else:  # notclear -> clear of everything, re-plunge at end
                    stats["n_notclear_links"] += 1
                    px, py = prev[0], prev[1]
                    path = [(px, py)] + [(round(x, 4), round(y, 4))
                                        for (x, y) in pts]
                    req = stock.link_top_max(path, tool_r + rapid_margin)
                    h = clearance_z if req <= -1e8 else \
                        min(clearance_z, max(req + rapid_margin, prev[2]))
                    emit({"g": 0, "x": px, "y": py, "z": round(h, 4)})
                    for (x, y) in pts:
                        emit({"g": 0, "x": round(x, 4), "y": round(y, 4),
                              "z": round(h, 4)})

        if allowance_check:
            # islands are the FORBIDDEN region for centres (R2): every centre
            # must be outside them with >= 0.005 mm margin - the same bound
            # the CLCHECK gate enforces on the tip.
            viol = allowance_violation([(p[0], p[1]) for p in level_pts],
                                      islands, 0.0, 0.025)
            if viol:
                try:
                    import json as _json
                    import numpy as _np
                    _np.save("out/dbg_mask_%s.npy" % round(z, 3), mask)
                    _np.save("out/dbg_grown_%s.npy" % round(z, 3), grown)
                    near = [p for p in level_pts
                            if math.dist((p[0], p[1]), viol[:2]) < 3.0]
                    with open("out/dbg_loops_%s.json" % round(z, 3), "w") as fh:
                        _json.dump({"z": z, "viol": viol, "outers": outers,
                                  "holes": holes, "islands": islands,
                                  "regions": region_dump,
                                  "level_pts_near": near}, fh)
                except Exception:
                    pass
                raise RuntimeError(
                    "lost allowance at level Z=%.3f: CL point (%.3f, %.3f) is "
                    "%.3f mm from the forbidden island loop (inside: 0.0), "
                    "need >= %.3f outside it"
                    % (z, viol[0], viol[1], viol[2], 0.005))
            # R1 backstop: the island loops above can be empty/stale for a
            # level (small features drop below min_perimeter); the part
            # heightfield check never depends on islands.
            hv = hf_gouge_violation(hf_pts, stock, tool_r)
            if hv:
                try:
                    import json as _json
                    import numpy as _np
                    _np.save("out/dbg_mask_%s.npy" % round(z, 3), mask)
                    _np.save("out/dbg_grown_%s.npy" % round(z, 3), grown)
                    near = [p for p in level_pts
                            if math.dist((p[0], p[1]), hv[:2]) < 4.0]
                    with open("out/dbg_loops_%s.json" % round(z, 3), "w") as fh:
                        _json.dump({"z": z, "viol": list(hv),
                                  "outers": outers, "holes": holes,
                                  "islands": islands, "regions": region_dump,
                                  "level_pts_near": near}, fh)
                except Exception:
                    pass
                raise RuntimeError(
                    "hf backstop at level Z=%.3f: CL point (%.3f, %.3f) at "
                    "Z=%.3f cuts to %.3f mm below the part heightfield"
                    % (z, hv[0], hv[1], hv[2], hv[3] - hv[2]))

        stock.refresh_tool()   # per-level tool-kernel refresh (cuts milled live)

        # RT item 2: end-of-level lift only to the local verified-clear
        # height (the next level's enter_at plans its own link from there);
        # full clearance only when the column itself demands it.
        px, py = prev[0], prev[1]
        req = stock.link_top_max([(px, py), (px, py)], tool_r + rapid_margin)
        h = clearance_z if req <= -1e8 else min(clearance_z,
                                                max(req + rapid_margin,
                                                    prev[2]))
        emit({"g": 0, "x": px, "y": py, "z": round(h, 4)})
        stats["levels"].append({"z": round(z, 3), "skipped": False,
                                 "region_mm2": round(area_mm2, 1),
                                 "n_islands": len(islands),
                                 "n_regions": nreg, "n_cl_pts": len(level_pts),
                                 "n_clip_breaks": stats["n_clip_breaks"] - cb0,
                                 "mandatory": bool(mandatory),
                                 "t_islands_s": round(t_isl, 1),
                                 "t_adaptive_s": round(t_a2d, 1)})
        if _RP2:
            lv = [r for r in rp2_regions if r["z"] == round(z, 3)]
            no = sum(1 for r in lv if r["open"])
            rp2_lv_sum.append({"z": round(z, 3), "n_open": no,
                              "n_closed": len(lv) - no,
                              "entry_mm_closed": round(sum(
                                  r["entry_mm"] for r in lv
                                  if not r["open"]), 1)})
        if _RP:
            rp["n_regions"] = nreg
            rp["n_clip_breaks"] = stats["n_clip_breaks"] - cb0
            rp["link_splits"] = {k: stats[k] - v
                                for k, v in rp_lk0.items()}
            rp["clip_len_mm"] = round(rp["clip_len_mm"], 1)
            rp["bridge_len_mm"] = round(rp["bridge_len_mm"], 1)
            rp_levels.append(rp)
        stats["n_regions"] += nreg
        zi += 1
        if progress:
            progress(zi, z, islands, nreg, stats)
    if prev[0] is not None:
        emit({"g": 0, "x": prev[0], "y": prev[1], "z": clearance_z})
    if allowance_check:
        # R2 item 2: independent CLCHECK gate - exact one-sided drop-cutter
        # with the ACTUAL cutter on every cutting move (separate code path
        # from the islands, engine/probe_rough_clcheck.py). A tip more than
        # 0.005 mm below CL + axial_leave fails the run.
        from engine.probe_rough_clcheck import clcheck_moves
        bad = clcheck_moves(surf, actual_cutter(tool_r, corner_r), moves,
                           axl, ss=0.1, tol=0.005)
        stats["clcheck_violations"] = len(bad)
        if bad:
            worst = max(bad, key=lambda b: b[4])
            raise RuntimeError(
                "rough CLCHECK FAILED: %d sample(s) below CL + axial_leave "
                "%.3f - 0.005, worst move %d at X%.3f Y%.3f Z%.3f sits "
                "%.3f mm below CL %.3f"
                % (len(bad), axl, worst[0], worst[1], worst[2], worst[3],
                   worst[4], worst[3] + axl - worst[4]))
    if stats["n_axial_plunge"]:
        # Task RT item 3: axial plunging into stock is forbidden - every
        # straight feed-down must enter cleared ground; anything that would
        # cut stock axially under the flat bottom must be a helix/ramp.
        raise RuntimeError(
            "rough axial-plunge FAILED: %d straight feed-down move(s) would "
            "cut stock axially under the flat bottom disk and no helix/ramp "
            "entry was possible; points: %s"
            % (stats["n_axial_plunge"], stats.get("axial_pts", [])[:12]))
    if stock_out:
        # S3b: the engine's own final stock heightfield (after all levels),
        # for finish --stock-from rapid verification
        save_stock_npy(stock, stock_out)
    if _RP:
        import json as _json
        tot, btot, ltot, btt = {}, {}, {}, {}
        for r in rp_levels:
            for k, v in r["breaks"].items():
                tot[k] = tot.get(k, 0) + v
            for k, v in r["bridged"].items():
                btot[k] = btot.get(k, 0) + v
            for k, v in r["break_len"].items():
                ltot[k] = round(ltot.get(k, 0.0) + v, 1)
            for k, v in r["bridge_len"].items():
                btt[k] = round(btt.get(k, 0.0) + v, 1)
        with open(os.environ.get("RT_RP_OUT", "out/rp0_probe.json"),
                  "w") as fh:
            _json.dump({"totals_breaks": tot, "totals_bridged": btot,
                       "break_len_mm": ltot, "bridge_len_mm": btt,
                       "clip_len_mm": round(sum(r["clip_len_mm"]
                                               for r in rp_levels), 1),
                       "bridge_len_mm_total": round(sum(r["bridge_len_mm"]
                                                       for r in rp_levels), 1),
                       "a2d_cut_len_mm": round(sum(r["a2d_cut_len_mm"]
                                                  for r in rp_levels), 1),
                       "levels": rp_levels}, fh, indent=1)
    if _RP2:
        import json as _json
        def _rp2_helix_len(dz, ang):
            r_h = helix_dia / 2.0
            if dz <= 0:
                return 0.0
            turns = _helix_turns(r_h, dz, ang)
            return turns * math.hypot(2.0 * math.pi * r_h, dz / turns)
        closed = [r for r in rp2_regions if not r["open"]]
        remaining = {}
        for ang in (2.0, 5.0, 10.0, 15.0):
            s = 0.0
            for r in closed:
                rest = max(r["entry_mm"] - _rp2_helix_len(r["dz_mm"], 2.0),
                          0.0)
                s += rest + _rp2_helix_len(r["dz_mm"], ang)
            remaining[str(ang)] = round(s, 1)
        with open(os.environ.get("RT_RP2_OUT", "out/rp2_0.json"),
                  "w") as fh:
            _json.dump({
                "n_regions": len(rp2_regions),
                "n_open": sum(1 for r in rp2_regions if r["open"]),
                "n_closed": len(closed),
                "entry_feed_all_mm": round(sum(r["entry_mm"]
                                             for r in rp2_regions), 1),
                "entry_feed_closed_mm": round(sum(r["entry_mm"]
                                                for r in closed), 1),
                "remaining_if_only_closed_helix_mm": remaining,
                "levels": rp2_lv_sum,
                "regions": rp2_regions}, fh)
    return moves, stats
