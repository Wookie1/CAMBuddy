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


def _log_table_fallback(tool_number, kind, dia, path, e):
    """SK1/M2: the exact tool number is not in the table - say which entry
    the type + diameter fallback took (or that none matched)."""
    print("warning: tool T%s not in %s; %s" % (
        tool_number, path,
        "using the %s %.3f mm entry T%s" % (kind, dia, e.get("number"))
        if isinstance(e, dict) else
        "no %s %.3f mm entry either" % (kind, dia)), file=sys.stderr)


def table_flute(kind, dia, tool_number=None, tools_json=None):
    """SK1: flute length (mm) for the rough air-column load check, read from
    the tool table the way finish reads it: by --tool-number when given,
    else by tool type + diameter. Returns None when no entry carries a
    flute_mm (the SK1 air-column class is then OFF)."""
    path = tools_json or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir,
        "tools", "x7_tools.json")
    try:
        with open(path) as fh:
            entries = json.load(fh).get("tools", [])
    except (IOError, OSError, ValueError):
        return None
    e = None
    if tool_number is not None:
        e = next((t for t in entries if t.get("number") == tool_number),
                 None)
    if e is None:
        e = next((t for t in entries
                  if t.get("type") == kind
                  and abs(float(t.get("diameter_mm", -1.0)) - dia) <= 0.001),
                 None)
        if tool_number is not None:
            _log_table_fallback(tool_number, kind, dia, path, e)
    fl = e.get("flute_mm") if isinstance(e, dict) else None
    try:
        return float(fl) if fl is not None else None
    except (TypeError, ValueError):
        return None


def table_holder(kind, dia, tool_number=None, tools_json=None):
    """M2: (holder max radius mm, stick-out mm) for the SK1 holder-clearance
    check, read from the same tool table entry and holder outline the
    judge's holder check reads ("holder" + "stickout_mm", holders[name]
    ["segments"] = [z_lo, z_hi, r_lo, r_hi] above the nose). None when the
    tool has no holder, stick-out or outline: SK1 then refuses side entry."""
    path = tools_json or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir,
        "tools", "x7_tools.json")
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError):
        return None
    entries = data.get("tools", [])
    e = None
    if tool_number is not None:
        e = next((t for t in entries if t.get("number") == tool_number),
                 None)
    if e is None:
        e = next((t for t in entries
                  if t.get("type") == kind
                  and abs(float(t.get("diameter_mm", -1.0)) - dia) <= 0.001),
                 None)
        if tool_number is not None:
            _log_table_fallback(tool_number, kind, dia, path, e)
    if not isinstance(e, dict) or not e.get("holder") \
            or e.get("stickout_mm") is None:
        return None
    h = data.get("holders", {}).get(e["holder"])
    if not isinstance(h, dict) or not h.get("segments"):
        return None
    try:
        r = max(max(float(sg[2]), float(sg[3])) for sg in h["segments"])
        return r, float(e["stickout_mm"])
    except (TypeError, ValueError, IndexError):
        return None


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


ORIGINS = ("stock_bottom_centre", "stock_top_centre", "model_origin")
# below this (mm, under every post's output resolution) no translation is
# applied: a model already in the chosen frame keeps today's exact STEP
ORIGIN_EPS = 1e-4
# rough Adaptive2d path tolerance (mm). 2026-10-30: 0.05 -> 0.1, about 2x faster a2d, gates re-proved on CF.
ROUGH_A2D_TOLERANCE = 0.1


def origin_offset(stock, origin):
    """Task (e): the translation (dx, dy, dz) mm that puts the chosen point
    of the stock box at (0, 0, 0): its XY centre at the bottom or the top
    face; model_origin keeps the model's own frame (0, 0, 0). Pure."""
    if origin == "model_origin":
        return (0.0, 0.0, 0.0)
    if origin not in ORIGINS:
        raise ValueError("unknown origin %r" % (origin,))
    x0, x1, y0, y1, z0, z1 = stock
    z = z0 if origin == "stock_bottom_centre" else z1
    return (-(x0 + x1) / 2.0, -(y0 + y1) / 2.0, -z)


def _run_post(a):
    """python -m engine.cli post --in <neutral/engine> --out F [options]"""
    from engine import post_lnc
    with open(a.inp, newline="") as fh:
        text = fh.read()
    kw = dict(metric=a.metric, program=a.program, op_name=a.op_name,
              wcs=a.wcs, dwell_ms=a.dwell_ms, dwell_p_ms=not getattr(a, "dwell_x_s", False),
              comment_style=getattr(a, "comment_style", "paren"),
              tool_desc=a.tool_desc, crlf=not a.lf, arcs=a.arcs,
              header_comments=a.header_comments)
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

    # task (e): work origin - move the oriented model so the chosen stock
    # point is (0, 0, 0), then rebuild the stock box from the moved bbox
    offset = origin_offset(stock, a.origin)
    if max(abs(v) for v in offset) > ORIGIN_EPS:
        moved = os.path.join(a.out_dir, "model_moved.step")
        env = dict(os.environ, STEP_IN=step_out, STEP_OUT=moved,
                   ORIENT="as_modeled", META_OUT=meta_out,
                   TRANSLATE="%.9f %.9f %.9f" % offset)
        os.remove(meta_out)
        r = subprocess.run([model.freecadcmd(),
                            os.path.join(here, "_orient.py")],
                           env=env, capture_output=True, text=True)
        if not os.path.exists(meta_out):
            raise SystemExit("origin move failed: %s\n%s"
                             % (r.stdout[-1500:], r.stderr[-1500:]))
        os.replace(moved, step_out)
        with open(meta_out) as fh:
            bbox = json.load(fh)["bbox"]
        stock = stock_box(bbox, sx, sy, a.stock_top, a.stock_bottom)
    else:
        offset = (0.0, 0.0, 0.0)

    prog(0.4, "rasterising part heightfield")
    # task HC: never accept a stale part_hf.npy from a reused out dir -
    # remove it (and its sidecar) first, then require both to exist and
    # match this run's STEP, cell and tessellation tolerance
    from engine import freshness
    freshness.remove_stale(hf_out)
    hf_tol = 0.01
    # SP-HF1: the grid covers the stock box + --tool-r + a 5 mm margin; it
    # was built over the part bbox only (the stock margins then copied the
    # grid's edge cells into the rough's part model). MARGIN is explicit:
    # heightfield.py's default grew for the JUDGE's grids (max(5, tool_r)),
    # and a different grid here re-aligns the cells the rough plans on
    # (cells past this edge clamp to the edge row, which is air).
    env = dict(os.environ, STEP_IN=step_out, HF_OUT=hf_out,
               CELL=str(a.cell), PAD="0", TESS_TOL=str(hf_tol),
               STOCK_BOX=" ".join("%.6f" % v for v in stock[:4]),
               TOOL_R="%.6f" % a.tool_r, MARGIN="5")
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
           "orient": a.orient, "origin": a.origin,
           "origin_offset": list(offset)}
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
        ramp_angle_deg=a.ramp_angle_deg,
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
    if a.stock_out:
        # RR-STOCK: after-finish stock = this program's own replay from
        # --stock-from (the rest pass plans on it, never on a judge stock)
        from engine import entry_depth
        if not a.stock_from:
            raise SystemExit("finish --stock-out needs --stock-from")
        entry_depth.replay_stock(
            moves, dia, dia / 2.0 if kind == "ball" else corner,
            a.stock_out, init=finishmod.load_heightfield(a.stock_from))
    if a.stats_json:
        with open(a.stats_json, "w") as fh:
            json.dump(stats, fh, indent=2)
    return 0


def rest_rough_main(a):
    """`engine.cli rest-rough`: z-level ball rest-rough from a live-stock
    map (engine/rest_rough.py). Fails closed: any emitted feed point below
    the exact ball CL (probe_clcheck rule, 0.005 mm) aborts with exit 1."""
    from engine import model, rest_rough as rrmod
    kind, dia, _corner = parse_tool(a.tool)
    if kind != "ball":
        raise SystemExit("rest-rough: tool kind %r refused (%s): the rest "
                         "generator cuts a ball only" % (kind, a.tool))
    stock = rrmod.fin.load_heightfield(a.stock_from)
    t0 = time.time()
    stl = model.step_to_stl(a.step)
    surf = model.load_surf(stl)
    print("STL %s: %d triangles" % (stl, surf.size()), flush=True)
    workers = a.workers if a.workers is not None else \
        int(os.environ.get("ENGINE_WORKERS", 4))

    def prog(stats):
        print("rest-rough: zones entered=%d no-entry=%d cut=%.0fmm "
              "ramp=%.0fmm rapid=%.0fmm" % (len(stats["zones"]),
                                            len(stats["no_entry"]),
                                            stats["cut_len"],
                                            stats["ramp_len"],
                                            stats["rapid_len"]), flush=True)

    moves, stats = rrmod.rest_rough(
        surf, stock, (kind, dia), floor_z=a.floor, stepdown=a.stepdown,
        ae=a.ae, rest_leave=a.rest_leave, min_excess=a.min_excess,
        min_helix_r=a.min_helix_r, ramp_angle_deg=a.ramp_angle_deg,
        cut_feed=a.cut_feed, ramp_feed=a.ramp_feed, clearance=a.clearance,
        zb_floor=a.zb_floor, workers=workers, shallow=a.shallow,
        progress=prog)

    below_cl, worst = rrmod.validate_exact(surf, dia, moves, a.rest_leave,
                                           workers=workers)
    stats["exact_cl_below"] = below_cl
    stats["exact_cl_worst_mm"] = round(worst, 4)
    if below_cl:
        raise SystemExit("rest-rough: %d emitted CL point(s) below the exact "
                         "ball CL by >0.005 mm (worst %.3f) - refusing to "
                         "post" % (below_cl, worst))
    if a.post == "lnc":
        from engine import post_lnc
        text = post_lnc.post(moves, metric=a.metric, program=a.program,
                             op_name=a.op_name, tool_number=a.tool_number,
                             rpm=a.spindle, dia_mm=dia, corner_mm=dia / 2.0,
                             tool_kind="ball")
    else:
        text = moves_to_gcode(
            moves, spindle_rpm=a.spindle,
            tool_comment="T %s D=%.3f CR=%.3f (rest-rough)"
                       % (kind, dia, dia / 2.0))
    with open(a.out, "w", newline="") as fh:
        fh.write(text)
    stats["out"] = a.out
    stats["n_moves"] = len(moves)
    stats["t_total_s"] = round(time.time() - t0, 1)
    print("wrote %s (%d moves) in %.1f s" % (a.out, len(moves),
                                             stats["t_total_s"]), flush=True)
    if a.stock_out:
        # RR-STOCK2: after-rest-rough stock = this program's own replay from
        # --stock-from (the finish after it plans on it, never on a judge map)
        from engine import entry_depth
        entry_depth.replay_stock(
            moves, dia, dia / 2.0, a.stock_out,
            init=rrmod.fin.load_heightfield(a.stock_from))
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
                           "flip_z_180", "rot_x_90", "rot_x_270",
                           "rot_y_90", "rot_y_270"))
    pr.add_argument("--origin", default="model_origin", choices=ORIGINS,
                    help="work origin: the stock point moved to (0,0,0) "
                         "(default model_origin: the model's own frame)")
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
    r.add_argument("--tolerance", type=float, default=ROUGH_A2D_TOLERANCE,
                  help="Adaptive2d path tolerance mm")
    r.add_argument("--air-descent-g0", dest="air_descent_g0", type=int,
                   default=None,
                   help="helix entries start at their own column's clear "
                        "height (G0 down to it) instead of the link plane: 1 "
                        "on (default), 0 off (also --no-air-descent-g0 or env "
                        "ENGINE_AIR_G0=0); needs a known holder")
    r.add_argument("--no-air-descent-g0", dest="air_descent_g0",
                   action="store_const", const=0,
                   help="same as --air-descent-g0 0")
    r.add_argument("--gap-relink", dest="gap_relink", type=int, default=None,
                   help="GR: before a link lifts the tool or a clip break "
                        "re-bores, try a straight at-depth link under the "
                        "deep-link checks: 1 on (default), 0 off (also "
                        "--no-gap-relink or env ENGINE_GAP_RELINK=0)")
    r.add_argument("--lr1", dest="lr1", type=int, default=None,
                   help="LR1: helix starts take the swept-disk stock top "
                        "from fine (0.1 mm) point heights instead of the "
                        "0.5 mm grid: 1 on, 0 off (default; env "
                        "CAMBUDDY_LR1)")
    r.add_argument("--air-feed", dest="air_feed", type=int, default=None,
                   help="AF: helix moves above the fine stock top over the "
                        "swept disk + 0.25 mm run at the cutting feed: 1 on, "
                        "0 off (default; env CAMBUDDY_AIR_FEED)")
    r.add_argument("--no-gap-relink", dest="gap_relink",
                   action="store_const", const=0,
                   help="same as --gap-relink 0")
    r.add_argument("--ll-overlap", dest="ll_overlap", type=int, default=None,
                   help="run the --load-limit feed limiter in a worker while "
                        "rough's closing clcheck runs: 0 off (all-inline), 1 "
                        "on (default; env ENGINE_LL_OVERLAP=0 also turns it "
                        "off); the program is identical either way")
    r.add_argument("--a2d-pool", dest="a2d_pool", type=int, default=None,
                   help="pass-opener Adaptive2d pre-run pool: 0 off "
                        "(byte-identical all-inline path), 1 on (default; "
                        "env ENGINE_A2D_POOL=0 also turns it off)")
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
    r.add_argument("--load-limit", dest="load_limit", default=True,
                   action=argparse.BooleanOptionalAction,
                   help="FL-LOAD: replay the emitted moves into the engine's "
                        "own 0.1 mm stock and slow the feed (never raise it, "
                        "floor 25%% of --cut-feed) on ZE2 windows whose load "
                        "ae*a*F/(2.032*19.05*Fcut) exceeds 1.2; the XYZ path "
                        "is unchanged (default on; --no-load-limit turns "
                        "it off)")
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
    r.add_argument("--header-comment", dest="header_comments",
                   action="append", default=None,
                   help="extra LNC header comment line (P3 form); repeatable")
    r.add_argument("--json-progress", dest="json_progress", action="store_true",
                   help='emit JSON progress lines '
                       '{"progress":0.4,"message":"level 3/7"} for callers')
    r.add_argument("--tools-json", dest="tools_json", default=None,
                   help="tool table JSON for every tool lookup of this call")
    r.add_argument("--side-entry-clear", dest="side_entry_clear", default=None,
                   help="SK1: comma list of OPEN faces (xneg,xpos,yneg,ypos) "
                        "allowing thin side-skin entries that descend in the "
                        "air outside the stock; default NONE: the class is "
                        "OFF (workholding: vise jaws and clamps sit outside "
                        "the stock and the engine has no fixture model)")
    r.add_argument("--side-entry-min-z", dest="side_entry_min_z", type=float,
                   default=None,
                   help="SK1: lowest Z at which an air-column descent may "
                        "start (default none = down to the floor)")
    r.add_argument("--flute", type=float, default=None,
                   help="SK1: flute length mm for the air-column feed-in "
                        "load check; default: read from --tools-json (or "
                        "tools/x7_tools.json) by --tool-number / tool type + "
                        "diameter; no flute known -> the class is OFF")

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
    pp.add_argument("--header-comment", dest="header_comments",
                    action="append", default=None,
                    help="extra LNC header comment line (P3 form); repeatable")
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
    pp.add_argument("--tools-json", dest="tools_json", default=None,
                   help="tool table JSON for every tool lookup of this call")

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
    f.add_argument("--stock-out", dest="stock_out", default=None,
                   help="RR-STOCK: write this program's own 0.1 mm replay "
                        "(moves x tool) from --stock-from (+ sidecar)")
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
    f.add_argument("--tools-json", dest="tools_json", default=None,
                   help="tool table JSON for every tool lookup of this call")
    f.add_argument("--ramp-angle-deg", dest="ramp_angle_deg", type=float,
                   default=2.0,
                   help="FE5: entry ramp angle deg - entries where the live "
                        "stock depth exceeds 0.25 mm enter on a vertex-raise "
                        "ramp along the pass's own vertices; default 2.0, "
                        "clamped [0.5, 15], <= 0 rejected")

    rr = sub.add_parser("rest-rough",
                       help="z-level ball rest-rough restricted to zones where "
                            "live stock (--stock-from) exceeds the tool CL by "
                            "--min-excess mm")
    rr.add_argument("--step", required=True, help="part STEP")
    rr.add_argument("--stock-from", dest="stock_from", required=True,
                   help="live stock heightfield .npy (+ x0/y0/cell .json): "
                        "the previous op's stock (engine.cli rough --stock-out "
                        "or zmap --stock-out); the rest-rough starts from it")
    rr.add_argument("--out", required=True, help="output .ngc file")
    rr.add_argument("--tool", required=True,
                   help="ball:DIA (only a ball is accepted)")
    rr.add_argument("--floor", type=float, required=True,
                   help="setup floor Z; levels = floor + leave + k*stepdown")
    rr.add_argument("--stepdown", type=float, required=True,
                   help="max level stepdown mm")
    rr.add_argument("--ae", type=float, required=True,
                   help="max radial engagement / stepover mm")
    rr.add_argument("--rest-leave", dest="rest_leave", type=float, required=True,
                   help="stock to leave on the part mm")
    rr.add_argument("--min-excess", dest="min_excess", type=float, required=True,
                   help="zone threshold mm: stock above the tool CL surface")
    rr.add_argument("--min-helix-r", dest="min_helix_r", type=float, required=True,
                   help="smallest largest-CL-circle radius that earns a helix "
                        "entry; pockets below it are reported, not entered")
    rr.add_argument("--ramp-angle-deg", dest="ramp_angle_deg", type=float,
                   default=2.0, help="helix ramp angle deg (default 2.0)")
    rr.add_argument("--cut-feed", dest="cut_feed", type=float, required=True)
    rr.add_argument("--ramp-feed", dest="ramp_feed", type=float, required=True)
    rr.add_argument("--spindle", type=int, required=True)
    rr.add_argument("--clearance", type=float, default=None,
                   help="retract plane Z (default: stock/part top + 2)")
    rr.add_argument("--zb-floor", dest="zb_floor", type=float, default=0.5,
                   help="entry-depth floor mm (FE5/ZB): no descent after a G0 "
                        "may exceed it against live stock (default 0.5)")
    rr.add_argument("--shallow", type=float, default=0.25,
                   help="RR1c step-1 live-depth limit mm: a pass start whose "
                        "FE5 disk depth against live stock is at or below this "
                        "is entered by a straight feed descent (no helix); it "
                        "also sizes the in-pass-ramp top-clear rule and the "
                        "SE2 descent column (default 0.25)")
    rr.add_argument("--workers", type=int, default=None)
    rr.add_argument("--stats-json", dest="stats_json", default=None)
    rr.add_argument("--stock-out", dest="stock_out", default=None,
                    help="RR-STOCK2: replay this rest-rough's own emitted "
                         "ball moves into its --stock-from stock and write "
                         "the .npy (+ x0/y0/cell .json sidecar): the finish "
                         "after a rest-rough plans on THIS, never on a zmap "
                         "rest stock")
    rr.add_argument("--post", choices=("neutral", "lnc"), default="neutral")
    rr.add_argument("--program", type=int, default=1003)
    rr.add_argument("--op-name", dest="op_name", default="REST ROUGH")
    rr.add_argument("--metric", action="store_true")
    rr.add_argument("--tool-number", dest="tool_number", type=int, default=None)

    a = p.parse_args(argv)

    # TLG1: --tools-json redirects BOTH table constants (finish.py
    # geometry/holder, post_lnc lookup_tool; both read at call time), so no
    # call can read two tables. Unset: nothing is changed (byte-identical).
    if getattr(a, "tools_json", None):
        from engine import post_lnc as _pl
        _pl.TOOL_TABLE_PATH = a.tools_json
        try:
            from engine import finish as _fin
            _fin.TOOL_TABLE_PATH = a.tools_json
        except ImportError:   # no opencamlib: no finish lookup can run here
            pass

    if a.cmd == "finish":
        return finish_main(a)

    if a.cmd == "rest-rough":
        return rest_rough_main(a)


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
            # rough's own plan: it can insert mandatory levels past `order`
            n = max(1, len(stats.get("levels_planned") or order))
            print(json.dumps({
                "progress": round(0.05 + 0.9 * min(zi, n) / n, 3),
                "message": "level %d/%d" % (zi, n)}), flush=True)

    workers = a.workers if a.workers is not None else int(os.environ.get("ENGINE_WORKERS", 4))  # 4: keeps local oMLX under its memory watermark
    # SK1: flute length for the air-column feed-in load check: --flute
    # override, else the tools-json/--tool-number entry the way finish does;
    # with no flute known the air-column class is OFF.
    flute = a.flute if a.flute is not None else \
        table_flute(kind, dia, a.tool_number, a.tools_json)
    # OV1: the limiter only rewrites F words and the closing clcheck only
    # reads XYZ, so the limiter can start on the final moves (on_moves) in a
    # spawn worker while rough's gates run. Its result is used only if the
    # returned moves pickle to the same bytes as the moves it was given;
    # otherwise (or on any worker error) it runs inline as before.
    one = bool(a.stock_out) and \
        os.environ.get("CAMBUDDY_FORCE_REPLAY") != "1"
    if a.ll_overlap is not None:
        ov_on = bool(a.ll_overlap)
    else:
        ov_on = int(os.environ.get("ENGINE_LL_OVERLAP", "1")) != 0
    ov = {}
    stats_ov = {"started": 0, "used": 0, "fallback": 0, "error": 0}

    def _ll_start(mv):
        import multiprocessing as mp
        import pickle
        from concurrent.futures import ProcessPoolExecutor
        from engine import load_limit
        ov["data"] = pickle.dumps(mv, protocol=pickle.HIGHEST_PROTOCOL)
        ov["ex"] = ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"))
        ov["fut"] = ov["ex"].submit(
            load_limit.limit_feeds_pickled, ov["data"], dia, corner, a.stock,
            a.stock[5], a.cut_feed, return_stock=one)
        stats_ov["started"] = 1

    def _ll_start_safe(mv):
        try:
            _ll_start(mv)
        except Exception:   # noqa: BLE001  OV1: never fails the rough
            if "ex" in ov:
                ov["ex"].shutdown(wait=False, cancel_futures=True)
            ov.clear()
            stats_ov["error"] += 1
    # ponytail: a rough that raises after on_moves leaves the limiter worker
    # to finish (<= ~70 s on CF) before the process exits
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
                                    ramp_angle_deg=a.ramp_angle_deg,
                                    side_entry_faces=a.side_entry_clear,
                                    side_entry_min_z=a.side_entry_min_z,
                                    flute_mm=flute,
                                    a2d_pool=a.a2d_pool,
                                    air_descent_g0=a.air_descent_g0,
                                    gap_relink=a.gap_relink,
                                    lr1=a.lr1, air_feed=a.air_feed,
                                    side_entry_holder=table_holder(
                                        kind, dia, a.tool_number,
                                        a.tools_json),
                                    on_moves=(_ll_start_safe if a.load_limit
                                              and ov_on else None))
    # SK1: report the air-column feed-in maxima (absent when the class is off)
    if stats.get("sk1_feedin"):
        print("sk1: air-column feed-ins=%d max_ae=%.3f mm max_load=%.3f "
              "max_a=%.3f mm" % (len(stats["sk1_feedin"]),
                                 stats["sk1_max_ae"], stats["sk1_max_load"],
                                 stats["sk1_max_a"]), flush=True)
    # SP-K1B: which stamping kernel the load-limit replay will use
    from engine import load_limit as _load_limit
    stats["stamp_kernel"] = ("c" if _load_limit._CKERN is not None
                             and not os.environ.get("CAMBUDDY_NO_CKERN")
                             else "python")
    print("stamp_kernel: %s" % stats["stamp_kernel"], flush=True)
    if a.load_limit:
        # FL-LOAD: slow the feed on over-loaded windows ONLY (flag OFF: this
        # post-pass never runs and the emitted program is untouched)
        from engine import load_limit
        # SP-P1A: limit_feeds already replays the final stock; reuse it
        # (CAMBUDDY_FORCE_REPLAY=1 keeps the separate replay, for proofs)
        res = None
        if "fut" in ov:
            import pickle
            try:
                if pickle.dumps(moves, protocol=pickle.HIGHEST_PROTOCOL) \
                        == ov["data"]:
                    res = ov["fut"].result(timeout=roughmod._pool_timeout())
                    stats_ov["used"] = 1
                else:
                    stats_ov["fallback"] = 1
            except Exception as e:   # noqa: BLE001  OV1: worker failure -> inline
                print("load_limit overlap: worker failed (%s: %s); limiter "
                      "runs inline" % (type(e).__name__, e), file=sys.stderr)
                stats_ov["error"] += 1
                if isinstance(e, TimeoutError):   # FU2: a hung worker
                    roughmod._pool_kill(ov["ex"])
            ov["ex"].shutdown(wait=True, cancel_futures=True)
        if res is None:
            res = load_limit.limit_feeds(
                moves, dia, corner, a.stock, a.stock[5], a.cut_feed,
                return_stock=one)
        moves, lst, *ll_stock = res
        stats["ll_overlap"] = stats_ov
        stats["load_limit"] = lst  # TP1: reduced_feed_windows for toolpath runs
        print("load_limit: windows_slowed=%d mm_slowed=%.1f min_feed=%.0f "
              "floor_bound=%d" % (lst["windows_slowed"], lst["mm_slowed"],
                                  lst["min_feed"] or 0.0,
                                  lst["floor_bound"]), flush=True)
    if a.stock_out and a.load_limit and ll_stock:
        from engine import entry_depth
        entry_depth.save_stock(a.stock_out, *ll_stock[0])
        print("stock_out: %s from load_limit's replay (no second replay)"
              % a.stock_out, flush=True)
    elif a.stock_out:
        # RR-STOCK: hand downstream the replay of the EMITTED moves (never
        # lower than what they remove); overwrites rough's coarse file
        from engine import entry_depth
        entry_depth.replay_stock(moves, dia, corner, a.stock_out,
                                 box=a.stock, top_z=a.stock[5])
    if a.post == "lnc":
        from engine import post_lnc
        text = post_lnc.post(moves, metric=a.metric, program=a.program,
                             op_name=a.op_name, tool_number=a.tool_number,
                             rpm=a.spindle, dia_mm=dia, corner_mm=corner,
                             tool_kind=kind, header_comments=a.header_comments)
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
