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
import time

import numpy as np
from opencamlib import ocl
import area

from engine import finish as fin
from engine.stock import StockField, save_stock_npy


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


def _helix_moves(cx, cy, sx, sy, z_top, z_bot, feed):
    """Downward CCW helix around (cx,cy) from (sx,sy)@z_top to depth z_bot."""
    r = math.dist((cx, cy), (sx, sy))
    if r < 0.05:
        return [{"g": 1, "x": sx, "y": sy, "z": z_bot, "f": feed}]
    a0 = math.atan2(sy - cy, sx - cx)
    turns = max(1.0, (z_top - z_bot) / max(0.2 * r, 0.5))
    turns = min(turns, (z_top - z_bot) / (2 * math.pi * r) * 4 + 1)
    n = max(8, int(turns * 36))
    out = []
    for i in range(1, n + 1):
        t = i / n
        a = a0 + t * turns * 2 * math.pi
        out.append({"g": 1, "x": round(cx + r * math.cos(a), 4),
                    "y": round(cy + r * math.sin(a), 4),
                    "z": round(z_top + t * (z_bot - z_top), 4), "f": feed})
    return out


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


def _run_a2d(outers, holes, islands, tool_r, leave, stepover, tolerance,
             keep_tool_down):
    """One level's Adaptive2d run; returns plain picklable region dicts."""
    a2d = area.Adaptive2d()
    a2d.stepOverFactor = stepover
    a2d.toolDiameter = 2 * tool_r
    a2d.helixRampTargetDiameter = 0.8 * 2 * tool_r
    a2d.helixRampMinDiameter = 0.4 * 2 * tool_r
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
          progress=None, stock_out=None):
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

    stats = {"levels": [], "n_regions": 0, "cut_len": 0.0, "plunge_len": 0.0,
             "rapid_len": 0.0, "n_rapid_bumps": 0,
             "t_islands": 0.0, "t_adaptive": 0.0,
             "n_retracts": 0, "n_lifts": 0, "n_notclear_links": 0,
             "n_clip_breaks": 0,
             "n_tooldown_links": 0, "levels_planned": [round(z, 3) for z in order],
             "mandatory_levels": sorted(round(z, 3) for z in mand)}

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
        emit({"g": 0, "x": prev[0] if prev[0] is not None else x,
              "y": prev[1] if prev[1] is not None else y, "z": clearance_z})
        emit({"g": 0, "x": x, "y": y, "z": clearance_z})

    def enter_at(x, y, z, hc):
        """Get the tool to (x, y, Z) cutting depth, keeping it down when the
        stock model says the way is clear."""
        px = prev[0] if prev[0] is not None else x
        py = prev[1] if prev[1] is not None else y
        pz = prev[2]
        # 1) straight tool-down link at cutting Z (clear in BOTH the stock
        # model and the exact forbidden islands - the hf can miss steep walls)
        if corridor_ok((px, py), (x, y)) and stock.link_clear([(px, py), (x, y)], z) \
                and stock.rise_clear(px, py, pz, z):
            if abs(pz - z) > 1e-6:
                emit({"g": 1, "x": px, "y": py, "z": z, "f": ramp_feed})
                mill_now(px, py, z)
            emit({"g": 1, "x": x, "y": y, "z": z, "f": cut_feed})
            stats["n_tooldown_links"] += 1
            return
        # 2) traverse at Z + lift, short plunge at the far end
        if corridor_ok((px, py), (x, y)) and \
                stock.link_clear([(px, py), (x, y)], z + lift) and \
                stock.rise_clear(px, py, pz, z + lift):
            if abs(pz - (z + lift)) > 1e-6:
                emit({"g": 1, "x": px, "y": py, "z": z + lift,
                      "f": ramp_feed})
            emit({"g": 0, "x": x, "y": y, "z": z + lift})
            emit({"g": 1, "x": x, "y": y, "z": z, "f": ramp_feed})
            mill_now(x, y, z)
            stats["n_tooldown_links"] += 1
            return
        # 3) retract to clearance, then helix or straight air plunge
        retract_to(x, y)
        top_stock = stock.top_at(x, y)
        helix_r = math.dist((hc[0], hc[1]), (x, y)) if hc is not None else 0.0
        if top_stock <= z + 0.05:
            emit({"g": 1, "x": x, "y": y, "z": z, "f": ramp_feed})
            mill_now(x, y, z)
        elif helix_r > 0.05:
            z_top = min(clearance_z, z + stepdown)
            emit({"g": 1, "x": x, "y": y, "z": z_top, "f": ramp_feed})
            mill_now(x, y, z_top)
            for hv in _helix_moves(hc[0], hc[1], x, y, z_top, z, ramp_feed):
                emit(hv)
        else:
            emit({"g": 1, "x": x, "y": y, "z": z, "f": ramp_feed})
            mill_now(x, y, z)

    def mill_now(x, y, z_bot):
        """Vertical plunge: the tool physically clears its footprint down to
        z_bot, so update the stock model immediately at the LOW end - the
        next link check in the same region sees the real floor."""
        stock.mill_segment(x, y, x, y, z_bot, tool_r, corner_r)

    zi = 0
    for z in order:
        del hf_pts[:]
        mandatory = round(z, 4) in mand
        mask = stock.region_mask(z, axl, 0.0 if mandatory else min_rest,
                                leave_margin=leave + 0.4)
        area_mm2 = stock.region_area(mask)
        if area_mm2 < min_level_area and not mandatory:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1)})
            continue
        grown = stock.dilate(mask, tool_r + leave + 0.5)
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
        # Adaptive2d geometry islands: F eroded by disk(R - margin), so the
        # tool_r + leave offset Adaptive2d applies keeps centres outside F
        isl_in = _loops_from_mask(_erode(Fm, erode_r, pitch), gxs, gys) \
            if Fm.any() else []

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
        holes = keep_holes
        if not outers:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1)})
            continue
        t0 = time.time()
        regions = _run_a2d(outers, holes, isl_in, tool_r, leave, stepover,
                           tolerance, keep_tool_down)
        # R4: wall-hugging rings close the margin-wide rest band + corner
        # chunks Adaptive2d cannot reach (its islands are pre-eroded).
        regions.extend(hug_regions(islands, grown, stock, isl_ok,
                                  eps=max(0.5 * tolerance, 0.03)))
        t_a2d = time.time() - t0
        stats["t_adaptive"] += t_a2d
        if not regions:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1),
                                   "n_islands": len(islands)})
            continue

        nreg = 0
        level_pts = []  # (x, y, tag) cutter centres cutting at this level's Z
        region_dump = []
        for res in regions:
            nreg += 1
            first_cut = next((p for (k, p) in res["paths"]
                              if k == "cutting" and p), None)
            entry = res["start"] or (first_cut[0] if first_cut else None)
            if entry is None:
                continue
            if not isl_ok([entry])[0]:
                g0 = next(((p, m) for (k, p) in res["paths"] if k == "cutting"
                          for m in [isl_ok(p)] if any(m)), (None, None))
                if g0[0] is None:
                    continue
                entry = g0[0][g0[1].index(True)]
            enter_at(round(entry[0], 4), round(entry[1], 4), z, res["helix"])
            level_pts.append((round(entry[0], 4), round(entry[1], 4),
                             "start r%d" % nreg))
            region_dump.append({"start": entry, "helix": res["helix"],
                              "paths": [[k, len(p)] for (k, p) in res["paths"]]})
            for (kind, pts) in res["paths"]:
                if kind == "cutting":
                    good = isl_ok(pts)
                    i = 0
                    gap = False
                    while i < len(pts):
                        if not good[i]:
                            stats["n_clip_breaks"] += 1
                            gap = True
                            i += 1
                            continue
                        if prev[2] is None or abs(prev[2] - z) > 1e-6 or gap:
                            # tool is up (after a notclear link or a clip
                            # break) or the path skipped over forbidden ground
                            # (clip break at z): re-enter at this point via the
                            # corridor-checked entry, don't dive across the gap
                            if prev[2] is None or abs(prev[2] - z) > 1e-6 or \
                                    math.dist((prev[0], prev[1]), pts[i]) > 0.6:
                                enter_at(round(pts[i][0], 4),
                                       round(pts[i][1], 4), z, None)
                                level_pts.append((round(pts[i][0], 4),
                                                round(pts[i][1], 4),
                                                "reentry r%d" % nreg))
                            gap = False
                        j = i
                        while j + 1 < len(pts) and good[j + 1]:
                            j += 1
                        run = [(round(x, 4), round(y, 4)) for (x, y)
                               in pts[i:j + 1]]
                        for (x, y) in run:
                            emit({"g": 1, "x": x, "y": y, "z": z,
                                  "f": cut_feed})
                            level_pts.append((x, y, "cut r%d" % nreg))
                        stock.mill_path(run, z, tool_r, corner_r)
                        i = j + 1
                elif kind == "linkclear":
                    land = (round(pts[-1][0], 4), round(pts[-1][1], 4))
                    corridor = [(round(x, 4), round(y, 4)) for (x, y) in pts]
                    if not isl_ok([land])[0] or \
                            not stock.link_clear(corridor, z + lift):
                        # landing point or the lift corridor is not actually
                        # clear of stock/islands: retract to clearance and let
                        # the next cutting run re-enter via enter_at
                        stats["n_notclear_links"] += 1
                        emit({"g": 0, "x": prev[0], "y": prev[1],
                              "z": clearance_z})
                        emit({"g": 0, "x": land[0], "y": land[1],
                              "z": clearance_z})
                        continue
                    stats["n_lifts"] += 1
                    emit({"g": 0, "x": prev[0], "y": prev[1], "z": z + lift})
                    for (x, y) in pts[:-1]:
                        emit({"g": 0, "x": round(x, 4), "y": round(y, 4),
                              "z": z + lift})
                    emit({"g": 0, "x": round(pts[-1][0], 4),
                          "y": round(pts[-1][1], 4), "z": z + lift})
                    emit({"g": 1, "x": round(pts[-1][0], 4),
                          "y": round(pts[-1][1], 4), "z": z, "f": ramp_feed})
                    mill_now(round(pts[-1][0], 4), round(pts[-1][1], 4), z)
                    level_pts.append((round(pts[-1][0], 4),
                                     round(pts[-1][1], 4),
                                     "liftland r%d" % nreg))
                else:  # notclear -> clear of everything, re-plunge at end
                    stats["n_notclear_links"] += 1
                    emit({"g": 0, "x": prev[0], "y": prev[1],
                          "z": clearance_z})
                    for (x, y) in pts:
                        emit({"g": 0, "x": round(x, 4), "y": round(y, 4),
                              "z": clearance_z})

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

        emit({"g": 0, "x": prev[0], "y": prev[1], "z": clearance_z})
        stats["levels"].append({"z": round(z, 3), "skipped": False,
                                 "region_mm2": round(area_mm2, 1),
                                 "n_islands": len(islands),
                                 "n_regions": nreg, "n_cl_pts": len(level_pts),
                                 "mandatory": bool(mandatory),
                                 "t_islands_s": round(t_isl, 1),
                                 "t_adaptive_s": round(t_a2d, 1)})
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
    if stock_out:
        # S3b: the engine's own final stock heightfield (after all levels),
        # for finish --stock-from rapid verification
        save_stock_npy(stock, stock_out)
    return moves, stats
