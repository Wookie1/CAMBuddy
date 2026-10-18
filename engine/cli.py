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
                        "level and the stock-region clip")
    r.add_argument("--final-zmin", dest="final_zmin", type=float, default=None,
                  help="explicit final level tip Z (overrides floor+axial "
                     "leave; e.g. 24.95 to match Fusion's ZMIN)")
    r.add_argument("--stepdown", type=float, default=19.05)
    r.add_argument("--stepup", type=float, default=1.905,
                  help="step-up climb grid pitch mm above each big level")
    r.add_argument("--stepover", type=float, default=None,
                   help="percent of tool diameter (ignored if "
                       "--optimal-load-mm given)")
    r.add_argument("--optimal-load-mm", dest="optimal_load_mm", type=float,
                   default=2.03,
                   help="adaptive optimal load mm -> stepover = load / dia")
    r.add_argument("--hf", default=None,
                  help="part heightfield .npy (+ .json sidecar): clips step-up "
                       "levels to where remaining stock above the part is "
                       "> --min-rest mm")
    r.add_argument("--min-rest", dest="min_rest", type=float, default=1.0,
                  help="min remaining stock above the part mm for a cell to "
                       "stay in a level's region")
    r.add_argument("--min-level-area", dest="min_level_area", type=float,
                  default=20.0,
                  help="skip levels whose clipped stock region is smaller "
                       "than this mm^2")
    r.add_argument("--stock-cell", dest="stock_cell", type=float, default=0.5,
                  help="stock heightfield cell size mm")
    r.add_argument("--cut-feed", dest="cut_feed", type=float, default=3429.0)
    r.add_argument("--ramp-feed", dest="ramp_feed", type=float, default=1270.0)
    r.add_argument("--spindle", type=int, default=7500)
    r.add_argument("--workers", type=int, default=None,
                  help="parallel waterline workers (default $ENGINE_WORKERS or 4)")
    r.add_argument("--tolerance", type=float, default=0.05,
                  help="Adaptive2d path tolerance mm")
    r.add_argument("--wl-sampling", dest="wl_sampling", type=float, default=0.1,
                  help="waterline sampling mm")
    r.add_argument("--stats-json", dest="stats_json", default=None)
    a = p.parse_args(argv)

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

    part_hf = None
    if a.hf:
        import numpy as np
        part = np.load(a.hf)
        sidecar = (a.hf[:-4] if a.hf.endswith(".npy") else a.hf) + ".json"
        with open(sidecar) as fh:
            meta = json.load(fh)
        part_hf = (part, float(meta["x0"]), float(meta["y0"]),
                   float(meta["cell"]))

    final_zmin = a.final_zmin if a.final_zmin is not None else \
        a.floor + axial_leave
    order = roughmod.plan_stepup_levels(a.stock[5], final_zmin,
                                       stepdown=a.stepdown, stepup=a.stepup,
                                       axial_leave=axial_leave)
    print("candidate levels (%d): %s" % (len(order), order), flush=True)

    def prog(zi, z, islands, nreg, stats):
        lvl = next(l for l in reversed(stats["levels"]) if l["z"] == round(z, 3))
        print("level %2d Z=%7.3f area=%8.1f mm^2 islands=%2d regions=%d"
              " (wl %.1fs a2d %.1fs)"
              % (zi, z, lvl.get("region_mm2", 0.0), len(islands), nreg,
                 stats["t_waterline"], stats["t_adaptive"]), flush=True)

    workers = a.workers if a.workers is not None else int(os.environ.get("ENGINE_WORKERS", 4))  # 4: keeps local oMLX under its memory watermark
    moves, stats = roughmod.rough(surf, tuple(a.stock), dia / 2.0, a.floor,
                                  leave=a.leave, stepdown=a.stepdown,
                                  stepover=stepover,
                                  cut_feed=a.cut_feed, ramp_feed=a.ramp_feed,
                                  tolerance=a.tolerance,
                                  wl_sampling=a.wl_sampling, stl_path=stl,
                                  workers=workers, axial_leave=axial_leave,
                                  final_zmin=a.final_zmin, corner_r=corner,
                                  part_hf=part_hf, stock_cell=a.stock_cell,
                                  stepup=a.stepup, min_rest=a.min_rest,
                                  min_level_area=a.min_level_area,
                                  progress=prog)
    text = moves_to_gcode(moves, spindle_rpm=a.spindle,
                          tool_comment="T1 %s D=%.3f CR=%.3f" % (kind, dia, corner))
    with open(a.out, "w") as fh:
        fh.write(text)
    stats["out"] = a.out
    stats["n_moves"] = len(moves)
    stats["t_total"] = time.time() - t0
    print("wrote %s (%d moves) in %.1f s" % (a.out, len(moves),
                                               stats["t_total"]), flush=True)
    print("levels machined (Z / area mm^2):", flush=True)
    for lvl in stats["levels"]:
        print("  Z=%7.3f %10.1f %s" % (lvl["z"], lvl.get("region_mm2", 0.0),
                                       "SKIPPED" if lvl.get("skipped") else
                                       "%d regions, %d islands"
                                       % (lvl.get("n_regions", 0),
                                          lvl.get("n_islands", 0))), flush=True)
    if a.stats_json:
        with open(a.stats_json, "w") as fh:
            json.dump(stats, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
