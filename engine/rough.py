"""2.5D adaptive roughing: ocl waterline islands per Z level + area.Adaptive2d.

Boundary convention (proven in engine/test_engine.py):
  area.Adaptive2d offsets every geometry loop (outer boundary AND island
  loops) by tool_radius + stockToLeave, in cutter-centre space.
So we feed it:
  * outer boundary = stock box grown by tool_r + leave  -> centres reach the
    stock edge exactly and the tool breaks cleanly through the stock edge;
  * islands = raw material silhouettes at level Z (ocl waterline loops with a
    near-zero-radius cylinder cutter, radius wl_rho) -> Adaptive2d's own
    offset puts centres at rho + tool_r + leave from the part, i.e. the
    radial leave is `leave` (+rho, a 0.05 mm safety margin).

Levels are independent: waterline + Adaptive2d per level run in a fork pool
(workers load the STL once and cache it); move emission stays sequential so
levels appear top-down in the output.
"""
import math
import multiprocessing as mp
import os
import time

from opencamlib import ocl
import area


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


def waterline_islands(surf, z, radius, sampling=0.5, min_sampling=0.05,
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
        pts = decimate([(p.x, p.y) for p in loop], 0.1)
        if len(pts) < 3:
            continue
        per = sum(math.dist(pts[i], pts[(i + 1) % len(pts)])
                 for i in range(len(pts)))
        if per < min_perimeter:
            continue
        loops.append([[round(x, 4), round(y, 4)] for (x, y) in pts])
    return loops


def plan_levels(stock_zmax, floor_z, leave, stepdown):
    """Z levels (tip depths) top-down; last level = floor_z + leave."""
    final = floor_z + leave
    zs = []
    z = stock_zmax
    while z > final + 1e-9:
        zs.append(z)
        z -= stepdown
    zs.append(final)
    # first level at stock top removes nothing (tip flush with stock surface)
    if len(zs) > 1 and zs[0] >= stock_zmax - 1e-9:
        zs = zs[1:]
    return zs


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


def _run_a2d(outer, islands, tool_r, leave, stepover, tolerance,
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
    results = a2d.Execute([outer], [outer] + islands, [], lambda tp: False)
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


def _level_worker(idx):
    """Waterline + Adaptive2d for one level, in a pool worker process."""
    g = _POOL
    surf = g.get("surf")
    if surf is None:
        surf = ocl.STLSurf()
        ocl.STLReader(g["stl"], surf)
        g["surf"] = surf
    z = g["levels"][idx]
    sxmin, sxmax, symin, symax = g["stock"][:4]
    t0 = time.time()
    islands = waterline_islands(surf, z, g["wl_rho"],
                                sampling=g["wl_sampling"], threads=1)
    islands = [lp for lp in islands
               if sxmin - 1 <= min(p[0] for p in lp)
               and max(p[0] for p in lp) <= sxmax + 1
               and symin - 1 <= min(p[1] for p in lp)
               and max(p[1] for p in lp) <= symax + 1]
    t_wl = time.time() - t0
    t0 = time.time()
    regions = _run_a2d(g["outer"], islands, g["tool_r"], g["leave"],
                       g["stepover"], g["tolerance"], g["keep_tool_down"])
    return {"idx": idx, "z": z, "islands": islands, "regions": regions,
            "t_wl": t_wl, "t_a2d": time.time() - t0}


def rough(surf, stock_box, tool_r, floor_z, leave=0.3, stepdown=1.9,
          stepover=0.15, cut_feed=3429.0, ramp_feed=1270.0,
          clearance_z=None, lift=1.9, wl_sampling=0.5, threads=8,
          tolerance=0.1, keep_tool_down=3.0, stl_path=None, workers=None,
          progress=None):
    """Plan the roughing toolpath. Returns (moves, stats).

    moves: neutral dicts {g:0|1, x,y,z, f (mm/min or None)}.
    stock_box: (xmin,xmax,ymin,ymax,zmin,zmax) of the raw stock.
    workers>1 with stl_path: run waterline+Adaptive2d per level in a fork
    pool (levels are independent); output levels stay ordered top-down.
    """
    sxmin, sxmax, symin, symax, szmin, szmax = stock_box
    if clearance_z is None:
        clearance_z = szmax + 2.0
    a2d_offset = tool_r + leave          # what Adaptive2d shrinks loops by
    outer = rect_loop(sxmin - a2d_offset, symin - a2d_offset,
                      sxmax + a2d_offset, symax + a2d_offset)
    wl_rho = 0.05                       # near-zero cutter radius: silhouette

    levels = plan_levels(szmax, floor_z, leave, stepdown)
    stats = {"levels": [], "n_regions": 0, "cut_len": 0.0, "plunge_len": 0.0,
             "rapid_len": 0.0, "t_waterline": 0.0, "t_adaptive": 0.0}

    if workers and workers > 1 and stl_path:
        if workers is True:
            workers = max(1, os.cpu_count() - 2)
        _POOL.update(stl=stl_path, levels=levels, stock=stock_box,
                    outer=outer, tool_r=tool_r, leave=leave,
                    stepover=stepover, tolerance=tolerance,
                    keep_tool_down=keep_tool_down, wl_rho=wl_rho,
                    wl_sampling=wl_sampling)
        ctx = mp.get_context("fork")
        with ctx.Pool(workers) as pool:
            planned = pool.map(_level_worker, range(len(levels)))
        planned.sort(key=lambda p: p["idx"])
        level_plans = [(p["z"], p["islands"], p["regions"], p["t_wl"],
                       p["t_a2d"]) for p in planned]
    else:
        level_plans = []
        for z in levels:
            t0 = time.time()
            islands = waterline_islands(surf, z, wl_rho,
                                       sampling=wl_sampling, threads=threads)
            islands = [lp for lp in islands
                      if sxmin - 1 <= min(p[0] for p in lp)
                      and max(p[0] for p in lp) <= sxmax + 1
                      and symin - 1 <= min(p[1] for p in lp)
                      and max(p[1] for p in lp) <= symax + 1]
            t_wl = time.time() - t0
            t0 = time.time()
            regions = _run_a2d(outer, islands, tool_r, leave, stepover,
                               tolerance, keep_tool_down)
            level_plans.append((z, islands, regions, t_wl, time.time() - t0))

    moves = []
    prev = [None, None, clearance_z]

    def emit(mv):
        x0, y0, z0 = prev
        x0 = mv["x"] if x0 is None else x0
        y0 = mv["y"] if y0 is None else y0
        z0 = mv["z"] if z0 is None else z0
        length = math.dist((x0, y0, z0), (mv["x"], mv["y"], mv["z"]))
        if mv["g"] == 0:
            stats["rapid_len"] += length
        elif abs(mv["z"] - z0) > 1e-6:
            stats["plunge_len"] += length
        else:
            stats["cut_len"] += length
        moves.append(mv)
        prev[0], prev[1], prev[2] = mv["x"], mv["y"], mv["z"]

    for zi, (z, islands, regions, t_wl, t_a2d) in enumerate(level_plans):
        stats["t_waterline"] += t_wl
        stats["t_adaptive"] += t_a2d
        nreg = 0
        for res in regions:
            nreg += 1
            sp = res["start"]
            hc = res["helix"]
            if sp is None:
                sp = res["paths"][0][1][0]
            # entry: rapid to clearance, XY to start, helix or straight plunge
            emit({"g": 0, "x": prev[0] if prev[0] is not None else sp[0],
                  "y": prev[1] if prev[1] is not None else sp[1],
                  "z": clearance_z})
            emit({"g": 0, "x": sp[0], "y": sp[1], "z": clearance_z})
            helix_r = math.dist((hc[0], hc[1]), (sp[0], sp[1])) \
                if hc is not None else 0.0
            z_top = z + stepdown if zi > 0 else clearance_z
            if helix_r > 0.05:
                emit({"g": 1, "x": sp[0], "y": sp[1], "z": z_top,
                      "f": ramp_feed})
                for hv in _helix_moves(hc[0], hc[1], sp[0], sp[1], z_top, z,
                                       ramp_feed):
                    emit(hv)
            else:
                emit({"g": 1, "x": sp[0], "y": sp[1], "z": z,
                      "f": ramp_feed})
            # paths
            for (kind, pts) in res["paths"]:
                if kind == "cutting":
                    for (x, y) in pts:
                        emit({"g": 1, "x": round(x, 4), "y": round(y, 4),
                              "z": z, "f": cut_feed})
                elif kind == "linkclear":
                    emit({"g": 0, "x": prev[0], "y": prev[1], "z": z + lift})
                    for (x, y) in pts[:-1]:
                        emit({"g": 0, "x": round(x, 4), "y": round(y, 4),
                              "z": z + lift})
                    emit({"g": 0, "x": round(pts[-1][0], 4),
                          "y": round(pts[-1][1], 4), "z": z + lift})
                    emit({"g": 1, "x": round(pts[-1][0], 4),
                          "y": round(pts[-1][1], 4), "z": z, "f": ramp_feed})
                else:  # notclear -> clear of everything, re-plunge at end
                    emit({"g": 0, "x": prev[0], "y": prev[1],
                          "z": clearance_z})
                    for (x, y) in pts:
                        emit({"g": 0, "x": round(x, 4), "y": round(y, 4),
                              "z": clearance_z})
        emit({"g": 0, "x": prev[0], "y": prev[1], "z": clearance_z})
        stats["levels"].append({"z": round(z, 3), "n_islands": len(islands),
                                 "n_regions": nreg,
                                 "t_waterline_s": round(t_wl, 1),
                                 "t_adaptive_s": round(t_a2d, 1)})
        stats["n_regions"] += nreg
        if progress:
            progress(zi, z, islands, nreg, stats)
    emit({"g": 0, "x": prev[0], "y": prev[1], "z": clearance_z})
    return moves, stats
