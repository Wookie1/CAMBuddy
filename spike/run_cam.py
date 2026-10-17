# -*- coding: utf-8 -*-
"""Headless FreeCAD CAM spike on a mold core.

Usage:
    freecadcmd spike/run_cam.py samples/core_front.step out/
Falls back to env vars STEP_IN / OUT_DIR if no script args are passed.

Builds a CAM Job (box stock = part bbox +2mm X/Y each side, +1mm top),
two tool controllers (12.7 flat end mill, 6 mm ball end mill),
Op A: Adaptive roughing (model-aware), Op B: SteepShallow finishing,
posts both ops to <out>/core_front.ngc and prints a JSON summary.
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


# --------------------------------------------------------------------------
# Compatibility shim: this STEP carries three degenerate point-sized edges on
# BSpline faces (OCCT "undefined curve type"). Path.Geom.isVertical() and the
# model-aware projection in Adaptive trip over them. Skip such geometry; the
# degenerate faces are zero-area pole caps whose neighbours cover the
# projection.
_orig_isVertical = PathGeom.isVertical


def _safe_is_vertical(obj):
    try:
        return _orig_isVertical(obj)
    except TypeError:
        return False


PathGeom.isVertical = _safe_is_vertical


def _has_degenerate_curve(shape):
    for e in shape.Edges:
        try:
            _ = e.Curve
        except TypeError:
            return True
    return False


_orig_projectFacesToXY = PathAdaptive.projectFacesToXY


def _safe_project_faces_to_xy(faces, minEdgeLength=1e-10):
    try:
        return _orig_projectFacesToXY(faces, minEdgeLength)
    except TypeError:
        good = [f for f in faces if not _has_degenerate_curve(f)]
        print("shim: skipped %d face(s) with degenerate curves"
              % (len(faces) - len(good)), flush=True)
        return _orig_projectFacesToXY(good, minEdgeLength)


PathAdaptive.projectFacesToXY = _safe_project_faces_to_xy


def resolve_args():
    args = sys.argv[1:]
    # freecadcmd may or may not pass script arguments through; support env too.
    step = os.environ.get("STEP_IN")
    outdir = os.environ.get("OUT_DIR", "out")
    positional = [a for a in args if not a.startswith("-")]
    # drop the script path itself if it is present
    if positional and os.path.basename(positional[0]) == "run_cam.py":
        positional = positional[1:]
    if len(positional) >= 1:
        step = positional[0]
    if len(positional) >= 2:
        outdir = positional[1]
    if not step:
        raise SystemExit("usage: freecadcmd spike/run_cam.py <step> [outdir]")
    return step, outdir


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


def main():
    step_in, out_dir = resolve_args()
    os.makedirs(out_dir, exist_ok=True)

    doc = App.newDocument("CoreCAM")
    shape = Part.read(step_in)
    base = doc.addObject("Part::Feature", "Core")
    base.Shape = shape
    bb = shape.BoundBox
    print("STEP bbox: X[%.2f %.2f] Y[%.2f %.2f] Z[%.2f %.2f]"
          % (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax), flush=True)

    # ---------------------------------------------------------------- Job
    job = PathJob.Create("Job", [base], createDefaultStock=False)

    # Box stock: bbox + 2 mm each X/Y side, +1 mm on top.
    extent = App.Vector(bb.XLength + 4.0, bb.YLength + 4.0, bb.ZLength + 1.0)
    placement = App.Placement(App.Vector(bb.XMin - 2.0, bb.YMin - 2.0, bb.ZMin),
                             App.Rotation())
    stock = PathStock.CreateBox(job, extent, placement)
    job.Stock = stock

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

    # ------------------------------------------------- Op A: Adaptive rough
    op_a = PathAdaptive.Create("AdaptiveRoughing", parentJob=job,
                               toolController=tc1)
    op_a.Base = [(base, [])]
    op_a.ModelAwareExperiment = True
    op_a.setExpression("StartDepth", None)
    op_a.StartDepth.Value = bb.ZMax + 1.0  # top of stock
    op_a.setExpression("FinalDepth", None)
    op_a.FinalDepth.Value = bb.ZMin + 0.3  # stock bottom, Z stock to leave
    op_a.setExpression("StepDown", None)
    op_a.StepDown.Value = 3.0
    op_a.setExpression("StockToLeave", None)
    op_a.StockToLeave.Value = 0.3
    op_a.setExpression("ZStockToLeave", None)
    op_a.ZStockToLeave.Value = 0.3
    op_a.StepOverPercent = 15  # optimal load ~15% of diameter
    op_a.FinishingProfile = False

    t0 = time.time()
    doc.recompute()
    t_a = time.time() - t0
    print("ADAPT: StartDepth=%s FinalDepth=%s StepDown=%s StockToLeave=%s ZStockToLeave=%s"
          % (op_a.StartDepth, op_a.FinalDepth, op_a.StepDown, op_a.StockToLeave,
             op_a.ZStockToLeave), flush=True)

    # ------------------------------------------- Op B: Steep/Shallow finishing
    op_b = PathSteepShallow.Create("SteepShallowFinish", parentJob=job,
                                  toolController=tc2)
    for prop in ("StartDepth", "FinalDepth", "StepDown"):
        op_b.setExpression(prop, None)
    op_b.StartDepth = bb.ZMax + 1.0
    op_b.FinalDepth = bb.ZMin
    op_b.StepDown = 0.3
    op_b.SlopeThreshold = 45.0
    op_b.StepOver = 0.3
    op_b.SampleInterval = 1.0
    op_b.LinearDeflection = 0.1

    t0 = time.time()
    doc.recompute()
    t_b = time.time() - t0
    print("SETUP: SteepShallowFinish done in %.1f s, %d commands"
          % (t_b, len(op_b.Path.Commands)), flush=True)

    # ------------------------------------------------------------ Summary
    stats_a = op_stats(op_a, t_a)
    stats_b = op_stats(op_b, t_b)

    # --------------------------------------------------------------- Posting
    post_name = "linuxcnc"
    try:
        from Path.Post.Processor import PostProcessorFactory
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
        print("POST: %s export2 done, %d sections" % (post_name, len(sections or [])),
              flush=True)
    except Exception as exc:
        print("linuxcnc post failed (%s); falling back to generic post" % exc)
        post_name = "generic"
        from Path.Post.Processor import PostProcessorFactory
        post = PostProcessorFactory.get_post_processor(job, post_name)
        post.reinitialize()
        sections = post.export2()

    print("POST: joining gcode, section types: %s" % [type(s).__name__ for (_, s) in (sections or [])], flush=True)
    gcode = "\n".join(s for (_, s) in (sections or []) if s)
    ngc_path = os.path.join(out_dir, "core_front.ngc")
    with open(ngc_path, "w") as fh:
        fh.write(gcode)
    print("POST: wrote %s (%d bytes)" % (ngc_path, os.path.getsize(ngc_path)), flush=True)

    summary = {
        "step_file": step_in,
        "stock": {
            "x": [round(bb.XMin - 2.0, 3), round(bb.XMax + 2.0, 3)],
            "y": [round(bb.YMin - 2.0, 3), round(bb.YMax + 2.0, 3)],
            "z": [round(bb.ZMin, 3), round(bb.ZMax + 1.0, 3)],
        },
        "ops": [stats_a, stats_b],
        "post": {
            "postprocessor": post_name,
            "file": ngc_path,
            "size_bytes": os.path.getsize(ngc_path),
        },
    }
    print("SUMMARY_JSON_START", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print("SUMMARY_JSON_END", flush=True)

    # ----------------------------------------------------------- Acceptance
    ok = True
    for st, tc in ((stats_a, tc1), (stats_b, tc2)):
        # Allow cutter-center overtravel of tool radius + 1 mm for lead-in/out.
        lead = float(tc.Tool.Diameter) / 2.0 + 1.0
        if st["path_commands"] <= 100:
            print("FAIL: %s has only %d path commands" % (st["name"], st["path_commands"]), flush=True)
            ok = False
        if st["min_z"] < -12.0:
            print("FAIL: %s cutter Z below -12 mm (%.3f)" % (st["name"], st["min_z"]), flush=True)
            ok = False
        if (st["min_x"] < bb.XMin - 2.0 - lead or st["max_x"] > bb.XMax + 2.0 + lead
                or st["min_y"] < bb.YMin - 2.0 - lead or st["max_y"] > bb.YMax + 2.0 + lead):
            print("FAIL: %s leaves stock bounds (+lead)" % st["name"], flush=True)
            ok = False
    if os.path.getsize(ngc_path) == 0:
        print("FAIL: %s is empty" % ngc_path, flush=True)
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
