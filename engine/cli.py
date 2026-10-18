"""CLI: python -m engine.cli rough --step S --stock xmin xmax ymin ymax zmin zmax
           --tool bull:12.7:0.127 --out F [--floor 24.765] [--leave 0.381]

Runs with VibeCAD python (opencamlib + area)."""
import argparse
import json
import os
import subprocess
import sys
import time

from engine.gcode import moves_to_gcode


def parse_tool(spec):
    parts = spec.split(":")
    kind = parts[0]
    dia = float(parts[1])
    corner = float(parts[2]) if len(parts) > 2 else 0.0
    return kind, dia, corner


def _run_post(a):
    """python -m engine.cli post --in <neutral/engine> --out F [options]"""
    from engine import post_lnc
    with open(a.inp, newline="") as fh:
        text = fh.read()
    kw = dict(metric=a.metric, program=a.program, op_name=a.op_name,
              wcs=a.wcs, dwell_ms=a.dwell_ms, dwell_p_ms=a.dwell_p_ms,
              comment_style=getattr(a, "comment_style", "paren"),
              tool_desc=a.tool_desc, crlf=not a.lf)
    if a.tool_number is not None:
        kw["tool_number"] = a.tool_number
    if a.rpm is not None:
        kw["rpm"] = a.rpm
    if a.dia is not None:
        kw["dia_mm"] = a.dia
    if a.corner is not None:
        kw["corner_mm"] = a.corner
    if a.tool_kind is not None:
        kw["tool_kind"] = a.tool_kind
    if a.clear is not None:
        kw["clear_mm"] = a.clear
    out = post_lnc.post_text(text, **kw)
    with open(a.out, "w", newline="") as fh:
        fh.write(out)
    print("wrote %s" % a.out, flush=True)
    return 0


def _run_prepare(a):
    """python -m engine.cli prepare --step S --out-dir D [--orient ...]
    [--stock-xy N --stock-top N --stock-bottom N] [--cell 0.5]

    Orient the STEP (180 deg flips), derive the stock box from mm offsets
    (origin = stock bottom centre) and rasterise the part heightfield.
    Emits JSON progress lines and writes prepare.json in --out-dir."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    from engine import model
    os.makedirs(a.out_dir, exist_ok=True)
    step_out = os.path.join(a.out_dir, "model.step")
    meta_out = os.path.join(a.out_dir, "orient.json")
    hf_out = os.path.join(a.out_dir, "part_hf.npy")

    def prog(p, m):
        print(json.dumps({"progress": p, "message": m}), flush=True)

    prog(0.05, "orienting STEP")
    env = dict(os.environ, STEP_IN=a.step, STEP_OUT=step_out,
               ORIENT=a.orient, META_OUT=meta_out)
    r = subprocess.run([model.freecadcmd(), os.path.join(here, "_orient.py")],
                      env=env, capture_output=True, text=True)
    if not os.path.exists(meta_out):
        raise SystemExit("orient failed: %s\n%s" % (r.stdout[-1500:],
                                                    r.stderr[-1500:]))
    with open(meta_out) as fh:
        bbox = json.load(fh)["bbox"]

    prog(0.4, "rasterising part heightfield")
    env = dict(os.environ, STEP_IN=step_out, HF_OUT=hf_out,
               CELL=str(a.cell), PAD="0")
    r = subprocess.run([model.freecadcmd(),
                       os.path.join(repo, "verify", "heightfield.py")],
                      env=env, capture_output=True, text=True)
    if not os.path.exists(hf_out):
        raise SystemExit("heightfield failed: %s\n%s" % (r.stdout[-1500:],
                                                         r.stderr[-1500:]))

    pxmin, pxmax, pymin, pymax, pzmin, pzmax = bbox
    stock = [pxmin - a.stock_xy, pxmax + a.stock_xy,
             pymin - a.stock_xy, pymax + a.stock_xy,
             pzmin - a.stock_bottom, pzmax + a.stock_top]
    out = {"step": step_out, "hf": hf_out, "bbox": bbox, "stock": stock,
           "orient": a.orient}
    with open(os.path.join(a.out_dir, "prepare.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    prog(1.0, "prepared")
    print(json.dumps({"prepare": out}), flush=True)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="engine.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("prepare",
                       help="orient STEP, derive stock box, part heightfield")
    pr.add_argument("--step", required=True)
    pr.add_argument("--out-dir", dest="out_dir", required=True)
    pr.add_argument("--orient", default="as_modeled",
                    choices=("as_modeled", "flip_x_180", "flip_y_180",
                           "flip_z_180"))
    pr.add_argument("--stock-xy", dest="stock_xy", type=float, default=1.0,
                   help="XY stock offset per side mm")
    pr.add_argument("--stock-top", dest="stock_top", type=float, default=1.0)
    pr.add_argument("--stock-bottom", dest="stock_bottom", type=float,
                   default=1.0)
    pr.add_argument("--cell", type=float, default=0.5,
                   help="part heightfield cell size mm")

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
                  help="radial stock to leave mm (James's cutting data)")
    r.add_argument("--axial-leave", dest="axial_leave", type=float, default=None,
                   help="axial leave mm (default: --leave); used for the final "
                        "level and the stock-region clip")
    r.add_argument("--final-zmin", dest="final_zmin", type=float, default=None,
                  help="explicit final level tip Z (overrides floor+axial "
                     "leave; e.g. 24.95 from James's cutting data)")
    r.add_argument("--stepdown", type=float, default=19.05,
                   help="max stepdown mm (James's cutting data)")
    r.add_argument("--stepup", type=float, default=1.905,
                  help="step-up climb grid pitch mm above each big level")
    r.add_argument("--stepover", type=float, default=None,
                   help="percent of tool diameter (ignored if "
                       "--optimal-load-mm given)")
    r.add_argument("--optimal-load-mm", dest="optimal_load_mm", type=float,
                   default=2.03,
                   help="adaptive optimal load mm -> stepover = load / dia "
                        "(James's cutting data)")
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
    r.add_argument("--cut-feed", dest="cut_feed", type=float, default=3429.0,
                   help="cutting feed mm/min (James's cutting data)")
    r.add_argument("--ramp-feed", dest="ramp_feed", type=float, default=1270.0,
                   help="ramp/plunge feed mm/min (James's cutting data)")
    r.add_argument("--spindle", type=int, default=7500,
                   help="spindle rpm (James's cutting data)")
    r.add_argument("--workers", type=int, default=None,
                  help="parallel waterline workers (default $ENGINE_WORKERS or 4)")
    r.add_argument("--tolerance", type=float, default=0.05,
                  help="Adaptive2d path tolerance mm")
    r.add_argument("--wl-sampling", dest="wl_sampling", type=float, default=0.1,
                  help="waterline sampling mm")
    r.add_argument("--stats-json", dest="stats_json", default=None)
    r.add_argument("--post", choices=("neutral", "lnc"), default="neutral",
                   help="writer: neutral G21 (default) or SyilCNC LNCv2")
    r.add_argument("--program", type=int, default=1001,
                   help="LNC program number (with --post lnc)")
    r.add_argument("--op-name", dest="op_name", default="OVERALL ROUGHING",
                   help="LNC op-name comment (with --post lnc)")
    r.add_argument("--metric", action="store_true",
                   help="emit G21 mm instead of the default G20 inch")
    r.add_argument("--tool-number", dest="tool_number", type=int, default=None,
                   help="LNC tool number (T/H) with --post lnc; default: look "
                        "the tool up in tools/x7_tools.json")
    r.add_argument("--json-progress", dest="json_progress", action="store_true",
                   help='emit JSON progress lines '
                       '{"progress":0.4,"message":"level 3/7"} for callers')

    pp = sub.add_parser("post", help="post neutral/engine moves to LNC G-code")
    pp.add_argument("--in", dest="inp", required=True,
                   help="neutral or engine-output G-code file")
    pp.add_argument("--out", required=True, help="output .nc file")
    pp.add_argument("--metric", action="store_true",
                   help="emit G21 mm instead of the default G20 inch")
    pp.add_argument("--program", type=int, default=1001)
    pp.add_argument("--op-name", dest="op_name", default="ENGINE ROUGH")
    pp.add_argument("--tool-number", dest="tool_number", type=int, default=None,
                   help="LNC tool number (T/H); default: look the tool up in "
                        "tools/x7_tools.json (refuses if not listed)")
    pp.add_argument("--rpm", type=int, default=None)
    pp.add_argument("--dia", type=float, default=None, help="tool dia mm")
    pp.add_argument("--corner", type=float, default=None, help="corner radius mm")
    pp.add_argument("--tool-kind", dest="tool_kind", default=None,
                   choices=("bull", "flat", "ball", "endmill"))
    pp.add_argument("--clear", type=float, default=None,
                   help="clearance/retract height mm (default: max Z of path)")
    pp.add_argument("--wcs", type=int, default=54, help="work offset G-code (54)")
    pp.add_argument("--comment-style", choices=("paren", "slashstar"), default="paren",
                   help="P3: ( ) comments need LNC parameter 42 = 1; slashstar emits /*...*/")
    pp.add_argument("--dwell-ms", dest="dwell_ms", type=int, default=3000)
    pp.add_argument("--dwell-p-ms", dest="dwell_p_ms", action="store_true",
                   help="emit the P8 dwell as G04 P<milliseconds> instead of "
                        "the default G04 X<seconds>")
    pp.add_argument("--tool-desc", dest="tool_desc", default=None)
    pp.add_argument("--lf", action="store_true", help="use LF instead of CRLF")
    a = p.parse_args(argv)

    if a.cmd == "post":
        return _run_post(a)
    if a.cmd == "prepare":
        return _run_prepare(a)

    from engine import model, rough as roughmod
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
    if a.json_progress:
        print(json.dumps({"progress": 0.02, "message": "model loaded"}),
              flush=True)

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
        if a.json_progress:
            print(json.dumps({
                "progress": round(0.05 + 0.9 * zi / max(1, len(order)), 3),
                "message": "level %d/%d" % (zi, len(order))}), flush=True)

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
    if a.post == "lnc":
        from engine import post_lnc
        text = post_lnc.post(moves, metric=a.metric, program=a.program,
                             op_name=a.op_name, tool_number=a.tool_number,
                             rpm=a.spindle, dia_mm=dia, corner_mm=corner,
                             tool_kind=kind)
    else:
        text = moves_to_gcode(moves, spindle_rpm=a.spindle,
                              tool_comment="T1 %s D=%.3f CR=%.3f" % (kind, dia, corner))
    with open(a.out, "w", newline="") as fh:
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
    if a.json_progress:
        print(json.dumps({"progress": 1.0, "message": "paths done"}),
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
