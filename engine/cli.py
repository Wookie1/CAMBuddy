"""CLI: python -m engine.cli rough --step S --stock xmin xmax ymin ymax zmin zmax
          --tool bull:12.7:0.127 --out F [--floor 24.765] [--leave 0.381]

Runs with VibeCAD python (opencamlib + area)."""
import argparse
import json
import os
import sys
import time

from engine import model, rough as roughmod
from engine.gcode import moves_to_gcode


def parse_tool(spec):
    parts = spec.split(":")
    kind = parts[0]
    dia = float(parts[1])
    corner = float(parts[2]) if len(parts) > 2 else 0.0
    return kind, dia, corner


def finish_main(a):
    """`engine.cli finish`: slope-split finishing (action:
    slope_split_finish), engine/finish.py."""
    from engine import finish as finishmod
    kind, dia, corner = parse_tool(a.tool)
    t0 = time.time()
    if a.stl:
        stl = a.stl
    elif a.step:
        stl = model.step_to_stl(a.step)
    else:
        raise SystemExit("finish needs --stl or --step")
    surf = model.load_surf(stl)
    print("STL %s: %d triangles" % (stl, surf.size()), flush=True)
    workers = a.workers if a.workers is not None else max(1, os.cpu_count() - 2)

    def prog(stats):
        print("raster %.1fs steep %.1fs (wl %.1fs) simplify %.1fs links %.1fs"
              " drop_calls=%d rounds=%d chords=%d"
              % (stats.get("t_raster_s", 0.0), stats.get("t_steep_s", 0.0),
                 stats.get("t_waterline_s", 0.0), stats.get("t_simplify_s", 0.0),
                 stats.get("t_link_s", 0.0), stats["n_drop_calls"],
                 stats["n_simplify_rounds"], stats["n_chords_checked"]),
              flush=True)

    moves, stats = finishmod.finish(
        surf, stl_path=stl, tool=(kind, dia, corner), stepover=a.stepover,
        sampling=a.sampling, slope_threshold=a.slope_threshold,
        overlap_mm=a.overlap_mm, stepdown=a.stepdown,
        overlap_deg=a.overlap_deg, floor_z=a.floor,
        wl_sampling=a.wl_sampling, wl_min_sampling=a.wl_min_sampling,
        max_chord=a.max_chord, cut_feed=a.cut_feed, ramp_feed=a.ramp_feed,
        clearance=a.clearance, workers=workers, window=a.window,
        progress=prog)
    text = finishmod.finish_to_gcode(
        moves, spindle_rpm=a.spindle,
        tool_comment="T1 %s D=%.3f CR=%.3f" % (kind, dia, corner))
    with open(a.out, "w") as fh:
        fh.write(text)
    stats["out"] = a.out
    stats["n_moves"] = len(moves)
    stats["t_total_s"] = round(time.time() - t0, 1)
    print("wrote %s (%d moves) in %.1f s" % (a.out, len(moves),
                                               stats.get("t_total_s", 0.0)), flush=True)
    if a.stats_json:
        with open(a.stats_json, "w") as fh:
            json.dump(stats, fh, indent=2)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="engine.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rough")
    r.add_argument("--step", required=True)
    r.add_argument("--stock", type=float, nargs=6, required=True,
                   metavar=("XMIN", "XMAX", "YMIN", "YMAX", "ZMIN", "ZMAX"))
    r.add_argument("--tool", required=True,
                   help="bull:DIA:CORNER | flat:DIA | ball:DIA")
    r.add_argument("--out", required=True, help="output .ngc file")
    r.add_argument("--floor", type=float, default=24.765,
                   help="main floor Z; last level = floor + axial leave")
    r.add_argument("--leave", type=float, default=0.381,
                   help="radial stock to leave mm")
    r.add_argument("--axial-leave", dest="axial_leave", type=float, default=None,
                   help="axial leave mm (default: --leave); used for the final "
                        "level and flat-area levels")
    r.add_argument("--final-zmin", dest="final_zmin", type=float, default=None,
                   help="explicit final level tip Z (overrides floor+axial "
                        "leave; e.g. 24.95 to match Fusion's ZMIN)")
    r.add_argument("--stepdown", type=float, default=19.05)
    r.add_argument("--stepover", type=float, default=None,
                   help="percent of tool diameter (ignored if "
                        "--optimal-load-mm given)")
    r.add_argument("--optimal-load-mm", dest="optimal_load_mm", type=float,
                   default=2.03,
                   help="adaptive optimal load mm -> stepover = load / dia")
    r.add_argument("--hf", default=None,
                   help="part heightfield .npy (+ .json sidecar) for flat-area "
                        "level detection")
    r.add_argument("--flat-min-area", dest="flat_min_area", type=float,
                   default=200.0,
                   help="min flat-floor area mm^2 for a flat-area level")
    r.add_argument("--no-flat-levels", dest="flat_levels", action="store_false",
                   default=True, help="disable flat-area levels")
    r.add_argument("--cut-feed", dest="cut_feed", type=float, default=3429.0)
    r.add_argument("--ramp-feed", dest="ramp_feed", type=float, default=1270.0)
    r.add_argument("--spindle", type=int, default=7500)
    r.add_argument("--workers", type=int, default=None,
                   help="parallel level workers (default os.cpu_count()-2)")
    r.add_argument("--tolerance", type=float, default=0.05,
                   help="Adaptive2d path tolerance mm")
    r.add_argument("--wl-sampling", dest="wl_sampling", type=float, default=0.1,
                   help="waterline sampling mm")
    r.add_argument("--stats-json", dest="stats_json", default=None)

    f = sub.add_parser("finish",
                       help="slope-split finishing (action: slope_split_finish) "
                            "from ocl CL points only")
    f.add_argument("--stl", default=None,
                   help="part STL (e.g. cached out/core_front_setup.stl)")
    f.add_argument("--step", default=None,
                   help="STEP to tessellate via engine.model if --stl is absent")
    f.add_argument("--tool", default="ball:6",
                   help="ball:DIA | bull:DIA:CORNER | flat:DIA (default ball:6)")
    f.add_argument("--out", required=True, help="output .ngc file")
    f.add_argument("--stepover", type=float, default=0.3,
                   help="shallow raster stepover mm")
    f.add_argument("--sampling", type=float, default=0.1,
                   help="CL sampling / raster X pitch mm")
    f.add_argument("--slope-threshold", dest="slope_threshold", type=float,
                   default=40.0, help="steep/shallow slope threshold deg")
    f.add_argument("--overlap-mm", dest="overlap_mm", type=float, default=1.0,
                   help="shallow overlap band into the steep zone mm")
    f.add_argument("--stepdown", type=float, default=0.3,
                   help="steep waterline Z stepdown mm")
    f.add_argument("--overlap-deg", dest="overlap_deg", type=float, default=5.0,
                   help="steep keeps slope >= threshold - overlap_deg")
    f.add_argument("--floor", type=float, default=None,
                   help="lowest steep waterline Z (default: part zmin)")
    f.add_argument("--wl-sampling", dest="wl_sampling", type=float, default=0.2)
    f.add_argument("--wl-min-sampling", dest="wl_min_sampling", type=float,
                   default=0.1)
    f.add_argument("--max-chord", dest="max_chord", type=float, default=5.0,
                   help="max gouge-safe simplification chord mm")
    f.add_argument("--cut-feed", dest="cut_feed", type=float, default=3429.0)
    f.add_argument("--ramp-feed", dest="ramp_feed", type=float, default=1270.0)
    f.add_argument("--clearance", type=float, default=None,
                   help="retract plane Z (default part top + 2)")
    f.add_argument("--window", type=float, nargs=4, default=None,
                   metavar=("XMIN", "XMAX", "YMIN", "YMAX"),
                   help="restrict raster + steep loops to this window "
                        "(smoke test)")
    f.add_argument("--spindle", type=int, default=7500)
    f.add_argument("--workers", type=int, default=None,
                   help="parallel waterline level workers (default cpu-2)")
    f.add_argument("--stats-json", dest="stats_json", default=None)

    a = p.parse_args(argv)

    if a.cmd == "finish":
        return finish_main(a)

    kind, dia, corner = parse_tool(a.tool)
    if a.optimal_load_mm is not None:
        stepover = a.optimal_load_mm / dia
    else:
        stepover = (a.stepover if a.stepover is not None else 15.0) / 100.0
    axial_leave = a.axial_leave if a.axial_leave is not None else a.leave
    t0 = time.time()
    stl = model.step_to_stl(a.step)
    surf = model.load_surf(stl)
    print("STL %s: %d triangles" % (stl, surf.size()), flush=True)

    flat_floors = []
    if a.hf and a.flat_levels:
        import numpy as np
        part = np.load(a.hf)
        sidecar = (a.hf[:-4] if a.hf.endswith(".npy") else a.hf) + ".json"
        with open(sidecar) as fh:
            meta = json.load(fh)
        cell = float(meta["cell"])
        z_lo = (a.final_zmin if a.final_zmin is not None
                else a.floor + axial_leave)
        z_hi = float(np.nanmax(part))
        flat_floors = roughmod.find_flat_floors(part, cell,
                                                float(meta["x0"]),
                                                float(meta["y0"]),
                                                tuple(a.stock), z_lo, z_hi,
                                                min_area_mm2=a.flat_min_area)
        print("flat floors (%.0f mm^2 min, %.3f < Z < %.3f): %s"
              % (a.flat_min_area, z_lo, z_hi, flat_floors), flush=True)

    levels = roughmod.plan_levels(a.stock[5], a.floor, a.leave, a.stepdown,
                                 flat_floors=flat_floors,
                                 axial_leave=axial_leave,
                                 final_zmin=a.final_zmin)
    print("levels (%d): %s" % (len(levels), levels), flush=True)

    def prog(zi, z, islands, nreg, stats):
        print("level %2d Z=%7.3f islands=%2d regions=%d (wl %.1fs a2d %.1fs)"
              % (zi, z, len(islands), nreg, stats.get("t_waterline", 0.0),
                 stats.get("t_adaptive", 0.0)), flush=True)

    workers = a.workers if a.workers is not None else max(1, os.cpu_count() - 2)
    moves, stats = roughmod.rough(surf, tuple(a.stock), dia / 2.0, a.floor,
                                  leave=a.leave, stepdown=a.stepdown,
                                  stepover=stepover,
                                  cut_feed=a.cut_feed, ramp_feed=a.ramp_feed,
                                  tolerance=a.tolerance,
                                  wl_sampling=a.wl_sampling, stl_path=stl,
                                  workers=workers, axial_leave=axial_leave,
                                  flat_floors=flat_floors,
                                  final_zmin=a.final_zmin, progress=prog)
    text = moves_to_gcode(moves, spindle_rpm=a.spindle,
                          tool_comment="T1 %s D=%.3f CR=%.3f" % (kind, dia, corner))
    with open(a.out, "w") as fh:
        fh.write(text)
    stats["out"] = a.out
    stats["n_moves"] = len(moves)
    stats["t_total"] = time.time() - t0
    print("wrote %s (%d moves) in %.1f s" % (a.out, len(moves),
                                               stats.get("t_total", 0.0)), flush=True)
    if a.stats_json:
        with open(a.stats_json, "w") as fh:
            json.dump(stats, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
