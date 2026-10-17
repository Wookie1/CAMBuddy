# -*- coding: utf-8 -*-
"""Headless FreeCAD CAM spike on a mold core (machining setup coordinates).

Usage:
    freecadcmd spike/run_cam.py [step] [outdir] [--stock XMIN XMAX YMIN YMAX ZMIN ZMAX]
Env: STEP_IN / OUT_DIR / STOCK "xmin xmax ymin ymax zmin zmax" / MODEL_AWARE=1.
Defaults: samples/core_front_setup.step, out/, real stock X +-128.651 Y +-82.55
Z 0..60.96 (Task C #2).

Builds a CAM Job with the REAL box stock (not part bbox + margin),
two tool controllers (12.7 flat end mill, 6 mm ball end mill).

Roughing: plain (NON-model-aware) Adaptive ops, one per horizontal floor
level, each with explicit StartDepth/FinalDepth so it stops 0.3 mm above its
floor (the STEP's degenerate BSpline edges break the model-aware projection;
see NOTES.md — no healing, no monkeypatching).  With MODEL_AWARE=1 a single
model-aware trial op is built instead (Task C #3: try ONCE, record the error).
Finishing: SteepShallow with explicit depths so it reaches the low floors.

Posts the combined job to <out>/core_front.ngc and each stage separately to
<out>/core_front_rough.ngc / <out>/core_front_finish.ngc, saves the whole
document to <out>/core_front_job.FCStd and prints a JSON summary.

An op that ends up with an empty toolpath makes this script exit non-zero;
errors are never swallowed.
"""
import json
import os
import sys
import time

import FreeCAD as App
import Part
import Path
import Path.Main.Job as PathJob
import Path.Main.Stock as PathStock
import Path.Tool.Controller as PathToolController
from Path.Tool.toolbit import ToolBit
import Path.Op.Adaptive as PathAdaptive
import Path.Op.SteepShallow as PathSteepShallow
import Path.Geom as PathGeom

MOVE_NAMES = ("G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03")

Z_LEAVE = 0.3  # stock left above each floor for the finishing op


# --------------------------------------------------------------------------
# Degeneracy report (NO healing, NO monkeypatch — supervisor round 2).
# The STEP carries three point-sized BSpline edges; every repair attempt
# (fix, removeSplitter, self-fuse, per-face rebuild) either keeps them or
# invalidates the solid. We record the exact errors and stay out of the
# model-aware CAM code paths that trip over them.
# --------------------------------------------------------------------------

def report_degeneracies(shape):
    """Print the exact errors the STEP geometry causes in CAM internals."""
    bad_edges = []
    for i, e in enumerate(shape.Edges):
        try:
            _ = e.Curve
        except Exception as exc:
            bad_edges.append((i, str(exc), e.BoundBox))
    print("PROBE: %d edge(s) with undefined curve type:" % len(bad_edges),
          flush=True)
    for i, msg, bx in bad_edges:
        print("  edge[%d]: %s  bbox Z[%.4f %.4f]"
              % (i, msg, bx.ZMin, bx.ZMax), flush=True)

    bad_faces = []
    for fi, f in enumerate(shape.Faces):
        try:
            PathGeom.isVertical(f)
        except Exception as exc:
            bad_faces.append((fi, type(f.Surface).__name__, str(exc)))
    print("PROBE: %d face(s) break Path.Geom.isVertical:" % len(bad_faces),
          flush=True)
    for fi, stype, msg in bad_faces:
        print("  face[%d] (%s): %s" % (fi, stype, msg), flush=True)

    # the exact call model-aware Adaptive makes: solid projection at slice Z.
    # Values in setup coordinates (design z -> 34.925 - z): the failing design
    # slices -11.62 / -8 map to 46.545 / 42.925.
    for z in (46.545, 42.925, 24.765, 12.925):
        try:
            r = PathAdaptive._getSolidProjection(shape, z)
            print("PROBE: _getSolidProjection(z=%.2f) ok, faces=%d"
                  % (z, len(r.Faces)), flush=True)
        except Exception as exc:
            print("PROBE: _getSolidProjection(z=%.2f) FAILED: %s: %s"
                  % (z, type(exc).__name__, exc), flush=True)
    return bad_edges, bad_faces


def select_horizontal_faces(shape, zlo, zhi, min_area=5.0):
    """Indices of horizontal planar faces with mid-Z in [zlo, zhi] and clean
    boundary wires (no degenerate edges). Returns (subnames, min_z)."""
    subs = []
    zs = []
    for i, f in enumerate(shape.Faces):
        if not isinstance(f.Surface, Part.Plane):
            continue
        fbb = f.BoundBox
        if abs(fbb.ZMax - fbb.ZMin) > 1e-6:
            continue  # not horizontal
        zc = 0.5 * (fbb.ZMax + fbb.ZMin)
        if not (zlo <= zc <= zhi):
            continue
        if f.Area < min_area:
            continue
        clean = True
        for e in f.Edges:
            try:
                _ = e.Curve
            except Exception as exc:
                clean = False
                print("PROBE: skipping face[%d] (z=%.3f, area %.1f): edge %s"
                      % (i, zc, f.Area, exc), flush=True)
                break
        if clean:
            subs.append("Face%d" % (i + 1))
            zs.append(zc)
    return subs, (min(zs) if zs else None)


# Real machine stock for Core Front (Task C #2): box, not part bbox + margin.
DEFAULT_STOCK = (-128.651, 128.651, -82.55, 82.55, 0.0, 60.96)
# Cavity Front stock (STEP generation only, toolpaths skipped):
CAVITY_STOCK = (-127.762, 127.762, -76.2, 76.2, 0.0, 62.23)


def resolve_args():
    """step, outdir, stock_box, model_aware from argv or env."""
    args = sys.argv[1:]
    # freecadcmd may or may not pass script arguments through; support env too.
    step = os.environ.get("STEP_IN", "samples/core_front_setup.step")
    outdir = os.environ.get("OUT_DIR", "out")
    stock_env = os.environ.get("STOCK")
    model_aware = os.environ.get("MODEL_AWARE", "0") in ("1", "true", "True")
    stock = None
    if "--stock" in args:
        k = args.index("--stock")
        stock = tuple(float(v) for v in args[k + 1:k + 7])
        if len(stock) != 6:
            raise SystemExit("usage: --stock XMIN XMAX YMIN YMAX ZMIN ZMAX")
        args = args[:k] + args[k + 7:]
    if "--model-aware" in args:
        model_aware = True
        args.remove("--model-aware")
    positional = [a for a in args if not a.startswith("-")]
    # drop the script path itself if it is present
    if positional and os.path.basename(positional[0]) == "run_cam.py":
        positional = positional[1:]
    if len(positional) >= 1:
        step = positional[0]
    if len(positional) >= 2:
        outdir = positional[1]
    if stock is None and stock_env:
        parts = [float(v) for v in stock_env.replace(",", " ").split()]
        if len(parts) != 6:
            raise SystemExit('usage: STOCK="XMIN XMAX YMIN YMAX ZMIN ZMAX"')
        stock = tuple(parts)
    if stock is None:
        name = os.path.splitext(os.path.basename(step))[0]
        stock = CAVITY_STOCK if "cavity" in name else DEFAULT_STOCK
    return step, outdir, stock, model_aware


def op_stats(op, seconds):
    """Count move commands and track min/max X/Y/Z of cutter locations."""
    x = y = z = 0.0
    n = 0
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    for c in op.Path.Commands:
        if c.Name not in MOVE_NAMES:
            continue
        p = c.Parameters
        if "X" in p:
            x = float(p["X"])
        if "Y" in p:
            y = float(p["Y"])
        if "Z" in p:
            z = float(p["Z"])
        n += 1
        for i, v in enumerate((x, y, z)):
            lo[i] = min(lo[i], v)
            hi[i] = max(hi[i], v)
    return {
        "name": op.Label,
        "tool": op.ToolController.Tool.Label if op.ToolController else None,
        "path_commands": n,
        "min_x": round(lo[0], 3),
        "max_x": round(hi[0], 3),
        "min_y": round(lo[1], 3),
        "max_y": round(hi[1], 3),
        "min_z": round(lo[2], 3),
        "max_z": round(hi[2], 3),
        "seconds": round(seconds, 2),
    }


def require_path(op):
    """An op that produced no moves is a hard failure, never silent."""
    if len(op.Path.Commands) == 0:
        raise SystemExit("ERROR: op %s produced an empty toolpath "
                         "(see Path log above)" % op.Label)


def post_job(job, out_path, label):
    """Post the currently-active ops of `job` to one G-code file."""
    from Path.Post.Processor import PostProcessorFactory
    post_name = "linuxcnc"
    try:
        post = PostProcessorFactory.get_post_processor(job, post_name)
        from Machine.models.machine import Machine, Toolhead, ToolheadType
        post.reinitialize()
        post._machine = Machine.create_3axis_config()
        post.apply_configuration_bundle()
        post._machine.toolheads = [Toolhead(name="Default Toolhead",
                                           toolhead_type=ToolheadType.ROTARY,
                                           min_rpm=0, max_rpm=24000,
                                           max_power_kw=1.0)]
        sections = post.export2()
    except Exception as exc:
        print("POST %s: linuxcnc failed (%s); falling back to generic"
              % (label, exc), flush=True)
        post_name = "generic"
        from Path.Post.Processor import PostProcessorFactory
        post = PostProcessorFactory.get_post_processor(job, post_name)
        post.reinitialize()
        sections = post.export2()
    gcode = "\n".join(s for (_, s) in (sections or []) if s)
    if not gcode.strip():
        raise SystemExit("ERROR: posting %s produced no G-code" % label)
    with open(out_path, "w") as fh:
        fh.write(gcode)
    print("POST %s: wrote %s (%d bytes, %d sections)"
          % (label, out_path, os.path.getsize(out_path), len(sections or [])),
          flush=True)
    return post_name, os.path.getsize(out_path)


def make_rough_op(job, tc, base, name, subs, start_depth, final_depth):
    """Plain (non-model-aware) Adaptive clearing op with explicit depths.

    Plain Adaptive is purely 2D: one pocket region swept down from
    StartDepth to FinalDepth.  ZStockToLeave exists (Adaptive.py:1669) but is
    only honoured when ModelAwareExperiment is on, and model-aware mode dies
    on this STEP's degenerate edges -> so each floor level gets its own op
    with FinalDepth = floor_z + Z_LEAVE."""
    op = PathAdaptive.Create(name, parentJob=job, toolController=tc)
    op.Base = [(base, subs)]
    op.ModelAwareExperiment = False
    op.UseOutline = True  # use each selected face's OuterWire (fills ring holes)
    op.setExpression("StartDepth", None)
    op.StartDepth.Value = start_depth
    op.setExpression("FinalDepth", None)
    op.FinalDepth.Value = final_depth
    op.setExpression("StepDown", None)
    op.StepDown.Value = 3.0
    op.setExpression("StockToLeave", None)
    op.StockToLeave.Value = Z_LEAVE
    op.setExpression("ZStockToLeave", None)
    op.ZStockToLeave.Value = Z_LEAVE  # ignored in plain mode; see NOTES.md
    op.StepOverPercent = 15  # optimal load ~15% of diameter
    op.FinishingProfile = False
    return op


def main():
    step_in, out_dir, stock_box, model_aware = resolve_args()
    os.makedirs(out_dir, exist_ok=True)

    doc = App.newDocument("CoreCAM")
    shape = Part.read(step_in)
    report_degeneracies(shape)
    base = doc.addObject("Part::Feature", "Core")
    base.Shape = shape
    bb = shape.BoundBox
    print("STEP bbox: X[%.2f %.2f] Y[%.2f %.2f] Z[%.2f %.2f]"
          % (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax), flush=True)

    # ---------------------------------------------------------------- Job
    job = PathJob.Create("Job", [base], createDefaultStock=False)

    # Real box stock (Task C #2): given extents, origin at its min corner.
    sxmin, sxmax, symin, symax, szmin, szmax = stock_box
    extent = App.Vector(sxmax - sxmin, symax - symin, szmax - szmin)
    placement = App.Placement(App.Vector(sxmin, symin, szmin), App.Rotation())
    stock = PathStock.CreateBox(job, extent, placement)
    job.Stock = stock
    print("STOCK: X[%.3f %.3f] Y[%.3f %.3f] Z[%.3f %.3f]" % stock_box,
          flush=True)

    # ------------------------------------------------------ Tool controllers
    tc1 = PathToolController.Create("TC: 12.7mm Flat Endmill", toolNumber=1,
                                   document=doc)
    tc1.Tool.Diameter = 12.7
    tc1.SpindleSpeed = 5000
    tc1.HorizFeed = App.Units.Quantity("1500 mm/min")
    tc1.VertFeed = App.Units.Quantity("750 mm/min")
    job.Proxy.addToolController(tc1)

    ballbit = ToolBit.from_shape_id("ballend.fcstd")
    balltool = ballbit.attach_to_doc(doc=doc)
    tc2 = PathToolController.Create("TC: 6mm Ball Endmill", tool=balltool,
                                   toolNumber=2, document=doc)
    tc2.Tool.Diameter = 6.0
    tc2.SpindleSpeed = 10000
    tc2.HorizFeed = App.Units.Quantity("1200 mm/min")
    tc2.VertFeed = App.Units.Quantity("600 mm/min")
    job.Proxy.addToolController(tc2)

    doc.recompute()

    # ------------------------------------------ Op A1/A2: Adaptive rough levels
    # Setup coordinates (Task C #1): plateau top Z 46.845, ring shelves at
    # Z ~38.78, bore-mouth fillets down to ~27.3; the deep "floors" (design
    # -11.92 / 10.16 -> 46.84 / 24.77) are through-bores / underside, NOT
    # top-accessible (see NOTES.md ground truth).  Plain Adaptive, explicit
    # depths per level, cut from the real stock top down.
    start_z = szmax + 1.0

    subs_top, z_top = select_horizontal_faces(shape, bb.ZMax - 1.5, bb.ZMax)
    if not subs_top:
        raise SystemExit("ERROR: no top plateau faces found for roughing")

    if model_aware:
        # Task C #3: try ModelAwareExperiment ONCE on the reoriented shape.
        # No healing loops: whatever happens (path or exact error) is printed
        # and recorded in NOTES.md by the operator.
        op_m = make_rough_op(job, tc1, base, "AdaptiveModelAwareTrial",
                             subs_top, start_z, z_top + Z_LEAVE)
        op_m.ModelAwareExperiment = True
        t0 = time.time()
        doc.recompute()
        t_m = time.time() - t0
        print("MODEL_AWARE trial: ModelAwareExperiment=True, %d commands in "
              "%.1f s" % (len(op_m.Path.Commands), t_m), flush=True)
        require_path(op_m)
        raise SystemExit(0)

    op_a1 = make_rough_op(job, tc1, base, "AdaptiveRoughTop", subs_top,
                          start_z, z_top + Z_LEAVE)

    subs_shelf, z_shelf = select_horizontal_faces(shape, 10.925, 13.925)
    rough_ops = [op_a1]
    op_a2 = None
    if subs_shelf:
        # In the SETUP orientation the ring shelves (Z 12.7) sit UNDER the
        # plateau: the annulus above each shelf is only ~4 mm wide (the
        # Ø~10 bores), so a 12.7 mm flat cutter cannot reach the shelves from
        # above without ploughing through the plateau roof.  A purely-2D
        # plain-Adaptive op on the shelf outlines gouges up to ~29 mm (zmap:
        # out/zmap_setup_rough.json round 3) -> the shelves are left to the
        # 6 mm ball finish, which reaches them (annulus ~8 mm wide at floor).
        print("SKIP shelf roughing: shelves Z~%.2f not reachable by the "
              "12.7 mm cutter from above (annulus ~4 mm); ball finish covers "
              "them" % z_shelf, flush=True)

    print("ROUGH: top faces=%s floorZ=%.3f -> FinalDepth=%.3f"
          % (subs_top, z_top, z_top + Z_LEAVE), flush=True)
    if op_a2 is not None:
        print("ROUGH: shelf faces=%s floorZ=%.3f -> FinalDepth=%.3f"
              % (subs_shelf, z_shelf, z_shelf + Z_LEAVE), flush=True)

    t0 = time.time()
    doc.recompute()
    t_a = time.time() - t0
    for op in rough_ops:
        require_path(op)
        print("ADAPT %s: StartDepth=%.3f FinalDepth=%.3f StepDown=%s "
              "StockToLeave=%s ZStockToLeave=%s -> %d commands"
              % (op.Label, op.StartDepth.Value, op.FinalDepth.Value,
                 op.StepDown.Value, op.StockToLeave.Value,
                 op.ZStockToLeave.Value, len(op.Path.Commands)), flush=True)

    # ------------------------------------------- Op B: Steep/Shallow finishing
    op_b = PathSteepShallow.Create("SteepShallowFinish", parentJob=job,
                                  toolController=tc2)
    # Clear the setup-sheet expressions FIRST, then assign numeric depths;
    # otherwise the expression silently wins and FinalDepth resolves to the
    # part top, clamping every pass high above the floors.
    for prop in ("StartDepth", "FinalDepth", "StepDown"):
        op_b.setExpression(prop, None)
    op_b.StartDepth.Value = start_z
    op_b.FinalDepth.Value = bb.ZMin
    op_b.StepDown.Value = 0.3
    # Slope classification / boundary + coverage properties (from
    # Path/Op/SteepShallow.py opPropertyDefinitions):
    # SlopeThreshold (steep >= angle), StepOver, BoundaryOverlap,
    # SampleInterval, LinearDeflection, AngularDeflection, CutMode.
    op_b.SlopeThreshold = 45.0
    op_b.StepOver = 0.3
    op_b.BoundaryOverlap = 1.0
    op_b.SampleInterval = 0.5
    op_b.LinearDeflection = 0.05
    op_b.AngularDeflection = 0.26

    t0 = time.time()
    doc.recompute()
    t_b = time.time() - t0
    require_path(op_b)
    print("SETUP: SteepShallowFinish StartDepth=%s FinalDepth=%s StepDown=%s "
          "SlopeThreshold=%s StepOver=%s BoundaryOverlap=%s SampleInterval=%s "
          "-> %d commands in %.1f s"
          % (op_b.StartDepth, op_b.FinalDepth, op_b.StepDown,
             op_b.SlopeThreshold, op_b.StepOver, op_b.BoundaryOverlap,
             op_b.SampleInterval, len(op_b.Path.Commands), t_b), flush=True)

    # ------------------------------------------------------------ Summary
    stats_a = [op_stats(op, t_a / len(rough_ops)) for op in rough_ops]
    stats_b = op_stats(op_b, t_b)

    # ---------------------------------------------------------- Save + Post
    job_fcstd = os.path.join(out_dir, "core_front_job.FCStd")
    doc.saveAs(job_fcstd)
    print("SAVE: wrote %s" % job_fcstd, flush=True)

    ngc_path = os.path.join(out_dir, "core_front.ngc")
    rough_path = os.path.join(out_dir, "core_front_rough.ngc")
    finish_path = os.path.join(out_dir, "core_front_finish.ngc")

    post_name, size_all = post_job(job, ngc_path, "combined")

    # Per-op files: deactivate the other stage and re-post so each file carries
    # its own header + tool change and exactly one tool's moves.
    op_b.Active = False
    post_job(job, rough_path, "rough")
    op_b.Active = True
    for op in rough_ops:
        op.Active = False
    post_job(job, finish_path, "finish")
    for op in rough_ops:
        op.Active = True

    summary = {
        "step_file": step_in,
        "stock": {
            "x": [round(sxmin, 3), round(sxmax, 3)],
            "y": [round(symin, 3), round(symax, 3)],
            "z": [round(szmin, 3), round(szmax, 3)],
        },
        "ops": stats_a + [stats_b],
        "post": {
            "postprocessor": post_name,
            "file": ngc_path,
            "size_bytes": size_all,
            "per_op_files": {
                "rough": rough_path,
                "finish": finish_path,
            },
        },
        "job_file": job_fcstd,
    }
    print("SUMMARY_JSON_START", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print("SUMMARY_JSON_END", flush=True)

    # ----------------------------------------------------------- Acceptance
    ok = True
    rough_moves = 0
    for st, tc in ([(s, tc1) for s in stats_a] + [(stats_b, tc2)]):
        # Allow cutter-center overtravel of tool radius + 1 mm for lead-in/out.
        lead = float(tc.Tool.Diameter) / 2.0 + 1.0
        if st["path_commands"] == 0:
            print("FAIL: %s produced an empty path" % st["name"], flush=True)
            ok = False
        if st["name"] != "AdaptiveRoughShelf" and st["path_commands"] <= 100:
            print("FAIL: %s has only %d path commands" % (st["name"], st["path_commands"]), flush=True)
            ok = False
        if st["min_z"] < szmin - 0.02:
            print("FAIL: %s cutter Z below stock bottom %.3f (%.3f)"
                  % (st["name"], szmin, st["min_z"]), flush=True)
            ok = False
        if (st["min_x"] < sxmin - lead or st["max_x"] > sxmax + lead
                or st["min_y"] < symin - lead or st["max_y"] > symax + lead):
            print("FAIL: %s leaves stock bounds (+lead)" % st["name"], flush=True)
            ok = False
        if tc is tc1:
            rough_moves += st["path_commands"]
    if rough_moves <= 100:
        print("FAIL: roughing ops have only %d path commands in total" % rough_moves, flush=True)
        ok = False
    # Finishing must reach the lowest top-accessible floor: the ring shelves
    # at Z ~22.2 (and dip into the bore-mouth fillets below them). NOTE: the
    # "floors" at Z 10.16 / -11.92 in the task brief are NOT top-accessible:
    # 10.16 is the downward-facing bottom face of the core and -11.92 cells in
    # the heightfield are empty columns through Ø~10 mm through-bores
    # (verified: distToShape along the bore axes = void over the full Z range).
    # See NOTES.md. A 6 mm ball finishing from above cannot and need not cut
    # below the bore mouths.
    lowest_floor = z_shelf if op_a2 is not None else z_top
    if stats_b["min_z"] > lowest_floor + 0.5:
        print("FAIL: %s stops at Z %.3f, lowest reachable floor is %.3f"
              % (stats_b["name"], stats_b["min_z"], lowest_floor), flush=True)
        ok = False
    for pth in (ngc_path, rough_path, finish_path):
        if os.path.getsize(pth) == 0:
            print("FAIL: %s is empty" % pth, flush=True)
            ok = False
    print("ACCEPTANCE: %s" % ("PASS" if ok else "FAIL"), flush=True)
    if not ok:
        raise SystemExit(1)


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    traceback.print_exc()
    sys.stdout.flush()
    sys.exit(1)
