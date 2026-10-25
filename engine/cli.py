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


def stock_box(bbox, sx, sy, top, bottom):
    """Stock box = part bbox plus per-axis stock allowances (mm): the box
    is bbox extended by sx per side in X, sy per side in Y, top above and
    bottom below (origin = stock bottom centre). Pure (no FreeCAD) so it is
    unit-testable. A negative allowance is a mistake -> ValueError."""
    if sx < 0 or sy < 0:
        raise ValueError("stock allowance per side must be >= 0 mm "
                         "(got --stock-x=%s --stock-y=%s)" % (sx, sy))
    if top < 0 or bottom < 0:
        raise ValueError("stock allowance in Z must be >= 0 mm "
                         "(got --stock-top=%s --stock-bottom=%s)"
                         % (top, bottom))
    pxmin, pxmax, pymin, pymax, pzmin, pzmax = bbox
    return [pxmin - sx, pxmax + sx, pymin - sy, pymax + sy,
            pzmin - bottom, pzmax + top]


def _run_post(a):
    """python -m engine.cli post --in <neutral/engine> --out F [options]"""
    from engine import post_lnc
    with open(a.inp, newline="") as fh:
        text = fh.read()
    kw = dict(metric=a.metric, program=a.program, op_name=a.op_name,
              wcs=a.wcs, dwell_ms=a.dwell_ms, dwell_p_ms=not getattr(a, "dwell_x_s", False),
              comment_style=getattr(a, "comment_style", "paren"),
              tool_desc=a.tool_desc, crlf=not a.lf, arcs=a.arcs)
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

    # stock box first (bbox +- per-axis stock offsets): the heightfield grid
    # must cover the stock + tool radius, never just a tight part bbox (Z5b).
    # --stock-x / --stock-y default to --stock-xy when not given (task SX).
    sx = a.stock_x if a.stock_x is not None else a.stock_xy
    sy = a.stock_y if a.stock_y is not None else a.stock_xy
    try:
        stock = stock_box(bbox, sx, sy, a.stock_top, a.stock_bottom)
    except ValueError as e:
        raise SystemExit(str(e))

    prog(0.4, "rasterising part heightfield")
    # task HC: never accept a stale part_hf.npy from a reused out dir -
    # remove it (and its sidecar) first, then require both to exist and
    # match this run's STEP, cell and tessellation tolerance
    from engine import freshness
    freshness.remove_stale(hf_out)
    hf_tol = 0.01
    env = dict(os.environ, STEP_IN=step_out, HF_OUT=hf_out,
               CELL=str(a.cell), PAD="0", TESS_TOL=str(hf_tol))
    r = subprocess.run([model.freecadcmd(),
                       os.path.join(repo, "verify", "heightfield.py")],
                      env=env, capture_output=True, text=True)
    try:
        freshness.require_fresh(hf_out,
                                step_sha256=freshness.sha256_file(step_out),
                                cell=a.cell, tess_tol=hf_tol)
    except OSError as e:
        raise SystemExit("%s\n%s\n%s" % (e, r.stdout[-1500:],
                                          r.stderr[-1500:]))

    out = {"step": step_out, "hf": hf_out, "bbox": bbox, "stock": stock,
           "orient": a.orient}
    with open(os.path.join(a.out_dir, "prepare.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    prog(1.0, "prepared")
    print(json.dumps({"prepare": out}), flush=True)


def finish_main(a):
    """`engine.cli finish`: slope-split finishing (action:
    slope_split_finish), engine/finish.py."""
    from engine import finish as finishmod, model
    kind, dia, corner = parse_tool(a.tool)
    big = (kind, dia, corner)  # previous finish tool for the rest mask (S4)
    rest_kw = {}
    if getattr(a, "rest_from", None):
        # S3 item 3 / S4: corner rest pass; the leftover map is computed by
        # the engine itself from its own drop-cutter CL (finish tool vs the
        # rest tool) - see finish.compute_rest_mask.
        kind, dia, corner = parse_tool(a.rest_tool)
        rest_kw = dict(rest_from=a.rest_from, big_tool=big,
                       min_rest=a.min_rest)
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
        rapid_margin=(finishmod.RAPID_MARGIN if a.rapid_margin is None
                     else a.rapid_margin),
        use_rapids=not a.no_rapids, progress=prog,
        stock_from=a.stock_from,
        stock_allow=(finishmod.RAPID_STOCK_ALLOW if a.stock_allow is None
                    else a.stock_allow),
        flute_mm=getattr(a, "flute", None),
        shank_dia=getattr(a, "shank", None),
        stickout_mm=getattr(a, "stickout", None),
        holder=getattr(a, "holder", None),
        post_grid_mm=a.post_grid_mm,
        **rest_kw)
    # PQ: header corner radius = D/2 for a ball, the table corner radius for
    # a bull, 0 for a flat (the CLI spec carries only kind:dia for balls)
    cr_hdr = dia / 2.0 if kind == "ball" else (0.0 if kind == "flat"
                                               else corner)
    if rest_kw:
        if finishmod.tool_geometry(kind, dia) is None:
            # S4: placeholder marker stays only for tools not in the table
            tool_comment = ("PLACEHOLDER %s D=%.3f CR=%.3f (not in "
                            "tools/x7_tools.json - LNC post must refuse)"
                            % (a.rest_tool, dia, cr_hdr))
            stats["tool"] = "PLACEHOLDER %s" % a.rest_tool
        else:
            tool_comment = ("REST %s D=%.3f CR=%.3f (tools/x7_tools.json)"
                           % (a.rest_tool, dia, cr_hdr))
            stats["tool"] = a.rest_tool
    else:
        tool_comment = "T1 %s D=%.3f CR=%.3f" % (kind, dia, cr_hdr)
    text = finishmod.finish_to_gcode(
        moves, spindle_rpm=a.spindle, tool_comment=tool_comment,
        decimals=finishmod.grid_decimals(a.post_grid_mm))
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

    pr = sub.add_parser("prepare",
                       help="orient STEP, derive stock box, part heightfield")
    pr.add_argument("--step", required=True)
    pr.add_argument("--out-dir", dest="out_dir", required=True)
    pr.add_argument("--orient", default="as_modeled",
                    choices=("as_modeled", "flip_x_180", "flip_y_180",
                           "flip_z_180"))
    pr.add_argument("--stock-xy", dest="stock_xy", type=float, default=1.0,
                   help="XY stock offset per side mm")
    pr.add_argument("--stock-x", dest="stock_x", type=float, default=None,
                   help="X stock offset per side mm (default: --stock-xy)")
    pr.add_argument("--stock-y", dest="stock_y", type=float, default=None,
                   help="Y stock offset per side mm (default: --stock-xy)")
    pr.add_argument("--stock-top", dest="stock_top", type=float, default=1.0)
    pr.add_argument("--stock-bottom", dest="stock_bottom", type=float,
                   default=1.0)
    pr.add_argument("--cell", type=float, default=0.5,
                   help="part heightfield cell size mm")
    pr.add_argument("--tool-r", dest="tool_r", type=float, default=0.0,
                   help="largest tool radius mm the grid will judge; the "
                        "heightfield grid covers stock + this + 5 mm margin")

    r = sub.add_parser("rough")
    r.add_argument("--step", required=True)
    r.add_argument("--stock", type=float, nargs=6, required=True,
                   metavar=("XMIN", "XMAX", "YMIN", "YMAX", "ZMIN", "ZMAX"))
    r.add_argument("--tool", required=True,
                  help="bull:DIA:CORNER | flat:DIA (any other kind, e.g. "
                       "ball, is refused: rough would silently run it flat)")
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
                       "> --min-rest mm. When omitted the engine rasterises it "
                       "itself from the STEP (same clips always apply).")
    r.add_argument("--min-rest", dest="min_rest", type=float, default=1.0,
                  help="min remaining stock above the part mm for a cell to "
                       "stay in a level's region")
    r.add_argument("--min-level-area", dest="min_level_area", type=float,
                  default=20.0,
                  help="skip levels whose clipped stock region is smaller "
                       "than this mm^2")
    r.add_argument("--stock-cell", dest="stock_cell", type=float, default=0.5,
                  help="stock heightfield cell size mm")
    r.add_argument("--rapid-margin", dest="rapid_margin", type=float,
                   default=1.0,
                   help="R5: every G0 must clear max(live stock top, part) "
                        "within tool radius + this margin along the swept "
                        "path by this margin (mm)")
    r.add_argument("--cut-feed", dest="cut_feed", type=float, default=3429.0,
                   help="cutting feed mm/min (James's cutting data)")
    r.add_argument("--ramp-feed", dest="ramp_feed", type=float, default=1270.0,
                   help="ramp/plunge feed mm/min (James's cutting data)")
    r.add_argument("--ramp-angle-deg", dest="ramp_angle_deg", type=float,
                   default=2.0,
                   help="max descent angle into stock in deg (helix pitch and "
                        "straight ramps); default 2.0, clamped [0.5, 15], "
                        "<= 0 rejected")
    r.add_argument("--spindle", type=int, default=7500,
                   help="spindle rpm (James's cutting data)")
    r.add_argument("--workers", type=int, default=None,
                  help="parallel waterline workers (default $ENGINE_WORKERS or 4)")
    r.add_argument("--tolerance", type=float, default=0.05,
                  help="Adaptive2d path tolerance mm")
    r.add_argument("--keep-tool-down", dest="keep_tool_down", type=float,
                   default=3.0,
                   help="a2d keepToolDownDistRatio: max link length (x tool "
                        "diameter) Adaptive2d keeps the tool down between paths")
    r.add_argument("--wl-sampling", dest="wl_sampling", type=float, default=0.1,
                  help="(legacy, unused: R2 islands come from a drop-cutter "
                       "CL grid, no waterlines)")
    r.add_argument("--stats-json", dest="stats_json", default=None)
    r.add_argument("--stock-out", dest="stock_out", default=None,
                   help="write the engine's final stock heightfield to this "
                        ".npy (+ x0/y0/cell .json sidecar) for finish "
                        "--stock-from rapid verification (S3b)")
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
    pp.add_argument("--dwell-x-s", dest="dwell_x_s", action="store_true",
                   help="emit the P8 dwell as G04 X<seconds>. instead of "
                        "the default G04 P<milliseconds> (James's X7)")
    pp.add_argument("--tool-desc", dest="tool_desc", default=None)
    pp.add_argument("--lf", action="store_true", help="use LF instead of CRLF")
    pp.add_argument("--arcs", action="store_true",
                   help="fit G17 G02/G03 arcs (I/J) to G01 runs within 0.002 mm "
                        "(spec A1-A8); default off: lines only")

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
    f.add_argument("--rapid-margin", dest="rapid_margin", type=float,
                   default=None,
                   help="safety margin mm above max CL along a link path for "
                        "a verified G0 rapid link (default 1.0; + 1.0 mm "
                        "roughing-stock allowance)")
    f.add_argument("--no-rapids", dest="no_rapids", action="store_true",
                   help="disable verified G0 links (feed lift links only)")
    f.add_argument("--stock-from", dest="stock_from", default=None,
                   help="post-roughing stock heightfield .npy (+ x0/y0/cell "
                        ".json sidecar, engine.cli rough --stock-out): "
                        "rapid/lift heights must clear max(CL, stock within "
                        "the tool radius) + margin along the swept path (S3b)")
    f.add_argument("--stock-allow", dest="stock_allow", type=float,
                   default=None,
                   help="stock allowance mm added on top of max CL + margin "
                        "for rapids when no --stock-from model is given "
                        "(default 1.0)")
    f.add_argument("--rest-from", dest="rest_from", default=None,
                   help="stock/zmap heightfield .npy (+ x0/y0/cell .json "
                        "sidecar): corner rest pass - cut only where the 6 mm "
                        "ball CL surface exceeds the 3 mm ball reach by "
                        "> --min-rest mm (PLACEHOLDER tool)")
    f.add_argument("--rest-tool", dest="rest_tool", default="ball:3",
                   help="tool spec for --rest-from passes (default ball:3; "
                        "tools listed in tools/x7_tools.json, e.g. "
                        "ball:3.142, are real rest tools - only unlisted "
                        "tools get the PLACEHOLDER marker)")
    f.add_argument("--min-rest", dest="min_rest", type=float, default=0.5,
                   help="rest-pass threshold mm (default 0.5)")
    f.add_argument("--flute", type=float, default=None,
                   help="flute length mm (S4 shank safety); default: read "
                        "from tools/x7_tools.json by tool diameter (flute = "
                        "2.5 x D, James); no table entry -> shank rule off")
    f.add_argument("--shank", type=float, default=None,
                   help="shank diameter mm (S4 shank safety); default: read "
                        "from tools/x7_tools.json (assumed = D, not necked)")
    f.add_argument("--stickout", type=float, default=None,
                   help="tool stick-out mm, holder nose at tip + stick-out "
                        "(S5 holder safety); default: read from "
                        "tools/x7_tools.json by tool diameter")
    f.add_argument("--holder", default=None,
                   help="holder name in the tools/x7_tools.json \"holders\" "
                        "map (S5 holder safety); default: read from the tool "
                        "entry; needs a stick-out (table or --stickout)")
    f.add_argument("--post-grid-mm", dest="post_grid_mm", type=float,
                   default=0.001,
                   help="PQ: output grid mm the emitted points are snapped to "
                        "(0.001 for a metric post, 0.00254 for inch output; "
                        "the caller passes the grid matching its post units)")

    a = p.parse_args(argv)

    if a.cmd == "finish":
        return finish_main(a)


    if a.cmd == "post":
        return _run_post(a)
    if a.cmd == "prepare":
        return _run_prepare(a)

    from engine import model, rough as roughmod
    kind, dia, corner = parse_tool(a.tool)
    # RR1a: rough fails CLOSED on any tool kind it cannot honour. It cuts
    # with CylCutter (flat) or BullCutter (bull, corner carried); a ball
    # spec would silently become a FLAT rough (corner defaults to 0).
    if kind not in ("flat", "bull"):
        raise SystemExit("rough: tool kind %r refused (%s): adaptive rough "
                         "cuts flat or bull end mills only - a ball request "
                         "would silently run as a flat rough; use `finish` "
                         "for ball tools" % (kind, a.tool))
    if kind == "bull" and corner <= 0.0:
        raise SystemExit("rough: bull tool needs a corner radius "
                         "(--tool bull:DIA:CORNER, got %s) - without one it "
                         "would silently run as a flat rough" % a.tool)
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
              " (isl %.1fs a2d %.1fs)"
              % (zi, z, lvl.get("region_mm2", 0.0), len(islands), nreg,
                 stats["t_islands"], stats["t_adaptive"]), flush=True)
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
                                  rapid_margin=a.rapid_margin,
                                  keep_tool_down=a.keep_tool_down,
                                   progress=prog, stock_out=a.stock_out,
                                    ramp_angle_deg=a.ramp_angle_deg)
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
