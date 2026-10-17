"""CLI: python -m engine.cli rough --step S --stock xmin xmax ymin ymax zmin zmax
          --tool bull:12.7:0.127 --out F [--floor 24.8] [--leave 0.3]

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
    r.add_argument("--floor", type=float, default=24.8,
                   help="main floor Z; last level = floor + leave")
    r.add_argument("--leave", type=float, default=0.3)
    r.add_argument("--stepdown", type=float, default=1.9)
    r.add_argument("--stepover", type=float, default=15.0,
                   help="percent of tool diameter")
    r.add_argument("--cut-feed", dest="cut_feed", type=float, default=3429.0)
    r.add_argument("--ramp-feed", dest="ramp_feed", type=float, default=1270.0)
    r.add_argument("--spindle", type=int, default=7500)
    r.add_argument("--workers", type=int, default=None,
                   help="parallel level workers (default os.cpu_count()-2)")
    r.add_argument("--tolerance", type=float, default=0.1,
                   help="Adaptive2d path tolerance mm")
    r.add_argument("--stats-json", dest="stats_json", default=None)
    a = p.parse_args(argv)

    kind, dia, corner = parse_tool(a.tool)
    t0 = time.time()
    stl = model.step_to_stl(a.step)
    surf = model.load_surf(stl)
    print("STL %s: %d triangles" % (stl, surf.size()), flush=True)

    def prog(zi, z, islands, nreg, stats):
        print("level %2d Z=%7.3f islands=%2d regions=%d (wl %.1fs a2d %.1fs)"
              % (zi, z, len(islands), nreg, stats["t_waterline"],
                 stats["t_adaptive"]), flush=True)

    workers = a.workers if a.workers is not None else max(1, os.cpu_count() - 2)
    moves, stats = roughmod.rough(surf, tuple(a.stock), dia / 2.0, a.floor,
                                  leave=a.leave, stepdown=a.stepdown,
                                  stepover=a.stepover / 100.0,
                                  cut_feed=a.cut_feed, ramp_feed=a.ramp_feed,
                                  tolerance=a.tolerance, stl_path=stl,
                                  workers=workers, progress=prog)
    text = moves_to_gcode(moves, spindle_rpm=a.spindle,
                          tool_comment="T1 %s D=%.3f CR=%.3f" % (kind, dia, corner))
    with open(a.out, "w") as fh:
        fh.write(text)
    stats["out"] = a.out
    stats["n_moves"] = len(moves)
    stats["t_total"] = time.time() - t0
    print("wrote %s (%d moves) in %.1f s" % (a.out, len(moves),
                                               stats["t_total"]), flush=True)
    if a.stats_json:
        with open(a.stats_json, "w") as fh:
            json.dump(stats, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
