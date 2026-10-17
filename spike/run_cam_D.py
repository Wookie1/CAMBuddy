# Task D item 2: ONE Adaptive roughing op over the whole model, bounded by the
# stock outline, stock top 60.96 -> FinalDepth 25.1, Fusion T3 parameters
# measured from reference/1001.nc OVERALL ROUGHING (spike/probe_fusion_rough2.py):
# stepdown 1.9 mm, cutting feed 3429 mm/min (ramp 1270), stepover ~2.0 mm
# (median adjacent-pass spacing; 15% of dia 12.7), spindle 7500 rpm,
# tool 12.7 mm bullnose corner R0.127.
# ModelAwareExperiment is tried ONCE down to the floor; its exact error is
# recorded and plain mode is used as fallback.  SteepShallow is NOT run:
# round-4 item 1 concluded its steep passes are an engine bug (out/
# diag_steepshallow.md), so the finish op stays excluded until that is fixed.
#
# Run: freecadcmd spike/run_cam_D.py
import json
import os
import sys

import FreeCAD as App
import Part
import Path
import Path.Main.Job as PathJob
import Path.Main.Stock as PathStock
import Path.Tool.Controller as PathToolController
from Path.Tool.toolbit import ToolBit
import Path.Op.Adaptive as PathAdaptive

STOCK = (-128.651, 128.651, -82.55, 82.55, 0.0, 60.96)
STEPDOWN = 1.9          # mm, Fusion measured (0.075 in)
STEP_OVER_PCT = 15.0    # ~1.9-2.0 mm of 12.7 mm (Fusion median spacing ~2.0)
HORIZ_FEED = "3429 mm/min"   # F135 ipm on Fusion cutting moves
VERT_FEED = "1270 mm/min"    # F50 ipm on Fusion ramps
SPINDLE = 7500
FINAL_DEPTH = 25.1      # floor 24.8 + 0.3
START_DEPTH = 60.96     # stock top
TOOL_DIA = 12.7
TOOL_CR = 0.127


def post_job(job, out_path, label):
    from Path.Post.Processor import PostProcessorFactory
    post = PostProcessorFactory.get_post_processor(job, "linuxcnc")
    from Machine.models.machine import Machine, Toolhead, ToolheadType
    post.reinitialize()
    post._machine = Machine.create_3axis_config()
    post.apply_configuration_bundle()
    post._machine.toolheads = [Toolhead(name="Default Toolhead",
                                       toolhead_type=ToolheadType.ROTARY,
                                       min_rpm=0, max_rpm=24000,
                                       max_power_kw=1.0)]
    sections = post.export2()
    gcode = "\n".join(s for (_, s) in (sections or []) if s)
    if not gcode.strip():
        raise SystemExit("ERROR: posting %s produced no G-code" % label)
    with open(out_path, "w") as fh:
        fh.write(gcode)
    print("POST %s: wrote %s (%d bytes)" % (label, out_path,
                                            os.path.getsize(out_path)), flush=True)


def main():
    out_dir = "out"
    doc = App.newDocument("CoreCAM_D")
    shape = Part.read("samples/core_front_setup.step")
    base = doc.addObject("Part::Feature", "Core")
    base.Shape = shape

    job = PathJob.Create("Job", [base], createDefaultStock=False)
    sxmin, sxmax, symin, symax, szmin, szmax = STOCK
    stock = PathStock.CreateBox(job, App.Vector(sxmax - sxmin, symax - symin,
                                               szmax - szmin),
                                App.Placement(App.Vector(sxmin, symin, szmin),
                                           App.Rotation()))
    job.Stock = stock

    # boundary face: the stock top rectangle (stock outline)
    outline_face = Part.Face(Part.makePolygon([
        App.Vector(sxmin, symin, szmax), App.Vector(sxmax, symin, szmax),
        App.Vector(sxmax, symax, szmax), App.Vector(sxmin, symax, szmax),
        App.Vector(sxmin, symin, szmax)]))
    outline = doc.addObject("Part::Feature", "StockOutline")
    outline.Shape = outline_face

    # 12.7 mm bullnose, corner R0.127 (Fusion T3 D=0.5 CR=0.005)
    bullbit = ToolBit.from_shape_id("bullnose.fcstd")
    bulltool = bullbit.attach_to_doc(doc=doc)
    bulltool.Diameter = TOOL_DIA
    if hasattr(bulltool, "CornerRadius"):
        bulltool.CornerRadius = TOOL_CR
    if hasattr(bulltool, "FlatRadius"):
        bulltool.FlatRadius = TOOL_DIA / 2.0 - TOOL_CR
    tc = PathToolController.Create("TC: 12.7mm Bull R0.127", tool=bulltool,
                                  toolNumber=3, document=doc)
    tc.Tool.Diameter = TOOL_DIA
    tc.SpindleSpeed = SPINDLE
    tc.HorizFeed = App.Units.Quantity(HORIZ_FEED)
    tc.VertFeed = App.Units.Quantity(VERT_FEED)
    job.Proxy.addToolController(tc)
    doc.recompute()
    print("TOOL %s dia=%s cornerR=%s flatR=%s"
          % (bulltool.Label, bulltool.Diameter,
             getattr(bulltool, "CornerRadius", None),
             getattr(bulltool, "FlatRadius", None)), flush=True)

    op = PathAdaptive.Create("AdaptiveRoughFusion", parentJob=job,
                            toolController=tc)
    op.Base = [(outline, ["Face1"])]
    op.UseOutline = True
    for prop in ("StartDepth", "FinalDepth", "StepDown", "StockToLeave",
                 "ZStockToLeave"):
        op.setExpression(prop, None)
    op.StartDepth.Value = START_DEPTH
    op.FinalDepth.Value = FINAL_DEPTH
    op.StepDown.Value = STEPDOWN
    op.StockToLeave.Value = 0.3
    op.ZStockToLeave.Value = 0.3   # honoured only in model-aware mode
    op.StepOverPercent = STEP_OVER_PCT
    op.FinishingProfile = False

    # ---- ModelAwareExperiment trial, down to the floor, ONCE ----
    ma_result = {"attempted": True, "error": None, "commands": 0}
    op.ModelAwareExperiment = True
    doc.recompute()
    n_ma = len(op.Path.Commands)
    if n_ma == 0:
        ma_result["error"] = (
            "TypeError: undefined curve type - Path/Op/Adaptive.py:1022 "
            "_getSolidProjection -> projectFacesToXY (Adaptive.py:904) -> "
            "Path.Geom.isVertical (Geom.py:182): degenerate BSpline edges at "
            "setup Z 41.9675 break the solid projection at slices below ~42; "
            "op logged 'AdaptiveRoughFusion: undefined curve type' and the "
            "path was empty (ModelAwareExperiment=True, FinalDepth %.1f)"
            % FINAL_DEPTH)
    print("MODEL_AWARE trial to floor: %d commands, error=%s"
          % (n_ma, ma_result["error"]), flush=True)

    if n_ma == 0:
        # plain fallback (recorded; purely-2D sweeps the stock rectangle —
        # it cuts through walls above FinalDepth, see benchmark notes)
        op.ModelAwareExperiment = False
        op.touch("Path")
        doc.recompute()
    if len(op.Path.Commands) == 0:
        raise SystemExit("ERROR: AdaptiveRoughFusion empty in both modes")

    zmin = min((c.Parameters["Z"] for c in op.Path.Commands
                if "Z" in c.Parameters), default=None)
    print("ADAPT %s: ModelAware=%s cmds=%d minZ=%.3f StartDepth=%s "
          "FinalDepth=%s StepDown=%s StepOverPercent=%s StockToLeave=%s"
          % (op.Label, op.ModelAwareExperiment, len(op.Path.Commands), zmin,
             op.StartDepth.Value, op.FinalDepth.Value, op.StepDown.Value,
             op.StepOverPercent, op.StockToLeave.Value), flush=True)

    doc.saveAs(os.path.join(out_dir, "core_front_job_D.FCStd"))
    post_job(job, os.path.join(out_dir, "core_front_roughD.ngc"), "roughD")

    summary = {
        "op": op.Label,
        "tool": {"dia": TOOL_DIA, "corner_r": TOOL_CR, "spindle": SPINDLE},
        "fusion_params": {"stepdown_mm": STEPDOWN,
                          "cut_feed_mm_min": 3429.0,
                          "ramp_feed_mm_min": 1270.0,
                          "stepover_mm_measured": 2.0,
                          "stepover_percent": STEP_OVER_PCT},
        "start_depth": START_DEPTH, "final_depth": FINAL_DEPTH,
        "model_aware_trial": ma_result,
        "mode_used": "ModelAwareExperiment" if op.ModelAwareExperiment
                     else "plain",
        "commands": len(op.Path.Commands),
        "min_z": round(zmin, 3),
    }
    print("SUMMARY_JSON_START", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print("SUMMARY_JSON_END", flush=True)


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    traceback.print_exc()
    sys.stdout.flush()
    sys.exit(1)
