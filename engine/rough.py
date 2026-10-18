"""2.5D adaptive roughing: ocl waterline islands per Z level + area.Adaptive2d,
rest-aware via the engine's own stock heightfield (engine/stock.py).

Boundary convention (proven in engine/test_engine.py + probe_g_stockregion):
  area.Adaptive2d offsets every loop (stock boundary, holes, islands) by
  tool_radius + stockToLeave, in cutter-centre space. So per level we feed:
  * stock paths (Execute arg 1) = marching-squares contours of the region
    that still needs machining at this level (stock top > Z + axial leave,
    >= ~1 mm above the part), dilated by tool_r + leave (+0.5 mm margin) so
    centres reach the actual stock-region edge and can enter from open sides;
  * geometry = those outers + holes (cleared pockets inside stock) + the
    level's waterline islands (raw part silhouettes at Z, near-zero-radius
    cutter) -> centres end up `leave` (+0.05 margin) from the part.

Levels (Task G): big stepdowns of `stepdown` from the stock top down to the
final Z, and after each big level a climb grid: levels every `stepup` mm
UPWARD from it, clipped at runtime to where the stock model still shows
material (area >= min_level_area). This replaces the old full-area
intermediate/flat levels.

Links: between paths/regions we stay tool-down when the stock model says the
straight link at cutting Z (or Z + lift) is clear; only then do we retract to
clearance and helix/plunge. The hard radial-allowance post-check from round 6
still runs per level.
"""
import math
import multiprocessing as mp
import os
import time

from opencamlib import ocl
import area

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


def waterline_islands(surf, z, radius, sampling=0.1, min_sampling=0.02,
                     threads=None, min_perimeter=20.0):
    """Cutter-centre forbidden loops (islands) for a cylinder of `radius`
    with its bottom at Z = z, against the part surface."""
    cutter = ocl.CylCutter(radius, 50.0)
    wl = ocl.AdaptiveWaterline()
    wl.setSTL(surf)
    wl.setCutter(cutter)
    wl.setZ(z)
    wl.setSampling(sampling)
    wl.setMinSampling(min_sampling)
    if threads:
        wl.setThreads(threads)
    wl.run()
    loops = []
    for loop in wl.getLoops():
        pts = decimate([(p.x, p.y) for p in loop], 0.05)
        if len(pts) < 3:
            continue
        per = sum(math.dist(pts[i], pts[(i + 1) % len(pts)])
                 for i in range(len(pts)))
        if per < min_perimeter:
            continue
        loops.append([[round(x, 4), round(y, 4)] for (x, y) in pts])
    return loops


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


def allowance_violation(points, islands, tool_r, leave, tol=0.02):
    """HARD post-check for one level: every cutter centre cutting at this
    level's Z must stay >= tool_r + leave - tol from that level's island
    loops (the round-5 failure lost 0.37 mm of radial allowance). Returns
    (x, y, dist) of the closest-to-material offender, else None."""
    import numpy as np
    req = tool_r + leave - tol
    if not points or not islands:
        return None
    P = np.asarray(points, dtype=float)
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
    away from every island loop (exact waterline geometry - the ground truth
    the emitted CL must obey, independent of the stock heightfield model)."""
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
        return [bool(v >= req) for v in out]
    return f


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


_POOL = {}


def _wl_worker(z):
    """Waterline islands for one level, in a pool worker process."""
    g = _POOL
    surf = g.get("surf")
    if surf is None:
        surf = ocl.STLSurf()
        ocl.STLReader(g["stl"], surf)
        g["surf"] = surf
    t0 = time.time()
    loops = waterline_islands(surf, z, g["wl_rho"], sampling=g["wl_sampling"],
                              threads=1)
    sxmin, sxmax, symin, symax = g["stock"][:4]
    loops = [lp for lp in loops
             if sxmin - 1 <= min(p[0] for p in lp)
             and max(p[0] for p in lp) <= sxmax + 1
             and symin - 1 <= min(p[1] for p in lp)
             and max(p[1] for p in lp) <= symax + 1]
    return z, loops, time.time() - t0


def rough(surf, stock_box, tool_r, floor_z, leave=0.381, stepdown=19.05,
          stepover=0.16, cut_feed=3429.0, ramp_feed=1270.0,
          clearance_z=None, lift=1.9, wl_sampling=0.1, threads=8,
          tolerance=0.05, keep_tool_down=3.0, stl_path=None, workers=None,
          axial_leave=None, final_zmin=None, allowance_check=True,
          corner_r=0.127, part_hf=None, stock_cell=0.5, stepup=1.905,
          min_rest=1.0, min_level_area=20.0, progress=None, stock_out=None):
    """Plan the rest-aware roughing toolpath. Returns (moves, stats).

    moves: neutral dicts {g:0|1, x,y,z, f (mm/min or None)}.
    stock_box: (xmin,xmax,ymin,ymax,zmin,zmax) of the raw stock.
    part_hf: (part, x0, y0, cell) final-part heightfield for the
      "remaining stock above the part > min_rest" clip on level regions.
    Levels: big stepdowns + stock-clipped step-up climb grids (Task G);
      `stepup` = climb grid pitch, levels whose clipped region is smaller
      than min_level_area mm^2 are skipped.
    Links: stay tool-down within/between levels when the stock heightfield
      says the straight link at cutting Z (or Z + lift) is clear; otherwise
      retract to clearance and helix/plunge.
    allowance_check: HARD post-check per level that no cutter centre at the
      level's Z came closer than tool_r + leave - 0.02 to that level's island
      loops; raises RuntimeError with the location on violation.
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
    stock.set_tool(tool_r)

    order = plan_stepup_levels(szmax, final, stepdown=stepdown, stepup=stepup,
                              axial_leave=axl)

    stats = {"levels": [], "n_regions": 0, "cut_len": 0.0, "plunge_len": 0.0,
             "rapid_len": 0.0, "t_waterline": 0.0, "t_adaptive": 0.0,
             "n_retracts": 0, "n_lifts": 0, "n_notclear_links": 0,
             "n_clip_breaks": 0,
             "n_tooldown_links": 0, "levels_planned": [round(z, 3) for z in order]}

    # waterlines for all candidate levels are independent of the stock model:
    # prefetch them in a fork pool (workers load the STL once and cache it)
    wl_cache = {}
    if workers and workers > 1 and stl_path:
        if workers is True:
            workers = max(1, os.cpu_count() - 2)
        _POOL.update(stl=stl_path, wl_rho=0.05, wl_sampling=wl_sampling,
                    stock=stock_box)
        ctx = mp.get_context("fork")
        with ctx.Pool(workers) as pool:
            for z, loops, dt in pool.map(_wl_worker, order):
                wl_cache[z] = (loops, dt)
    else:
        for z in order:
            wl_cache[z] = waterline_islands(surf, z, 0.05,
                                           sampling=wl_sampling,
                                           threads=threads), 0.0

    moves = []
    prev = [None, None, clearance_z]

    def emit(mv):
        x0, y0, z0 = prev
        x0 = mv["x"] if x0 is None else x0
        y0 = mv["y"] if y0 is None else y0
        z0 = mv["z"] if z0 is None else z0
        if (mv.get("x") is not None and mv.get("y") is not None
                and mv.get("z") is not None
                and abs(mv["x"] - x0) < 1e-9 and abs(mv["y"] - y0) < 1e-9
                and abs(mv["z"] - z0) < 1e-9):
            return  # zero-length move
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
        # model and the exact waterline islands - the hf can miss steep walls)
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
        mask = stock.region_mask(z, axl, min_rest, leave_margin=leave + 0.4)
        area_mm2 = stock.region_area(mask)
        if area_mm2 < min_level_area:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1)})
            continue
        grown = stock.dilate(mask, tool_r + leave + 0.5)
        # stock-path outer contours must stay outside the islands' centre
        # limit (tool_r+leave around the part above Z): Adaptive2d offsets the
        # geometry outers inward by tool_r+leave, and an outer closer than
        # that to an island loop makes it emit centres ON the island loop
        # (43.815 violation: outer passed 3.2 mm from island #1)
        if stock.part is not None:
            pz = (stock.part > z) & stock.inb
            if pz.any():
                grown &= ~stock.dilate(pz, tool_r + leave + 0.3)
        outers, holes = stock.contours(grown)
        islands, t_wl = wl_cache[z]
        stats["t_waterline"] += t_wl
        # ground-truth clearance oracle for THIS level: exact waterline loops
        # (the hf model can under-report steep walls by ~1 cell)
        isl_ok = island_clear_fn(islands, tool_r + leave - 0.015)

        def corridor_ok(p0, p1):
            if not islands:
                return True
            L = math.dist(p0, p1)
            n = max(2, int(L / 0.4) + 1)
            pts = [(p0[0] + (p1[0] - p0[0]) * t / (n - 1),
                    p0[1] + (p1[1] - p0[1]) * t / (n - 1)) for t in range(n)]
            return all(isl_ok(pts))

        # drop clearance-ring outers: a territory component that passes within
        # tool_r+leave of an island loop has no room for the tool inside it,
        # and Adaptive2d answers by offsetting it right onto the island loop
        # (violations at 43.815 and 41.91). Its enclosed cells are island
        # clearance, not cutable stock.
        if islands and outers:
            import numpy as np
            ip = np.asarray([p for lp in islands for p in lp], dtype=float)
            min_d = tool_r + leave + 0.5
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
            outers = keep
        # keep only genuine cleared-pocket holes: a hole whose interior still
        # has stock above the level is a part footprint (excluded cells with
        # part > Z) - passing it next to the coincident waterline island loop
        # breaks Adaptive2d (probe_g_duploop: centres end up inside the hole)
        holes = [hp for hp in holes
                 if stock.top_at(sum(p[0] for p in hp) / len(hp),
                                sum(p[1] for p in hp) / len(hp))
                 <= z + axl + 0.05]
        if not outers:
            stats["levels"].append({"z": round(z, 3), "skipped": True,
                                   "region_mm2": round(area_mm2, 1)})
            continue
        t0 = time.time()
        regions = _run_a2d(outers, holes, islands, tool_r, leave, stepover,
                           tolerance, keep_tool_down)
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
                    while i < len(pts):
                        if not good[i]:
                            stats["n_clip_breaks"] += 1
                            i += 1
                            continue
                        if prev[2] is None or abs(prev[2] - z) > 1e-6:
                            # tool is up (after a notclear link or a clip
                            # break): re-enter at this point, don't dive
                            enter_at(round(pts[i][0], 4),
                                   round(pts[i][1], 4), z, None)
                            level_pts.append((round(pts[i][0], 4),
                                            round(pts[i][1], 4),
                                            "reentry r%d" % nreg))
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
            viol = allowance_violation([(p[0], p[1]) for p in level_pts],
                                      islands, tool_r, leave)
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
                    "%.3f mm from an island loop, need >= %.3f "
                    "(tool_r %.3f + leave %.3f - 0.02)"
                    % (z, viol[0], viol[1], viol[2],
                     tool_r + leave - 0.02, tool_r, leave))

        stock.refresh_tool()   # per-level tool-kernel refresh (cuts milled live)

        emit({"g": 0, "x": prev[0], "y": prev[1], "z": clearance_z})
        stats["levels"].append({"z": round(z, 3), "skipped": False,
                                 "region_mm2": round(area_mm2, 1),
                                 "n_islands": len(islands),
                                 "n_regions": nreg, "n_cl_pts": len(level_pts),
                                 "t_waterline_s": round(t_wl, 1),
                                 "t_adaptive_s": round(t_a2d, 1)})
        stats["n_regions"] += nreg
        zi += 1
        if progress:
            progress(zi, z, islands, nreg, stats)
    emit({"g": 0, "x": prev[0], "y": prev[1], "z": clearance_z})
    if stock_out:
        # S3b: the engine's own final stock heightfield (after all levels),
        # for finish --stock-from rapid verification
        save_stock_npy(stock, stock_out)
    return moves, stats
