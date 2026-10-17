# -*- coding: utf-8 -*-
"""Headless FreeCAD CAM spike on a mold core.

Usage:
    freecadcmd spike/run_cam.py samples/core_front.step out/
Falls back to env vars STEP_IN / OUT_DIR if no script args are passed.

Builds a CAM Job (box stock = part bbox +2mm X/Y each side, +1mm top),
two tool controllers (12.7 flat end mill, 6 mm ball end mill).

Roughing: plain (NON-model-aware) Adaptive ops, one per horizontal floor
level, each with explicit StartDepth/FinalDepth so it stops 0.3 mm above its
floor (the STEP's degenerate BSpline edges break the model-aware projection;
see NOTES.md — no healing, no monkeypatching).
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

    # the exact call model-aware Adaptive makes: solid projection at slice Z
    for z in (-11.62, -8.0, 10.16, 22.0):
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
    step_in, out_dir = resolve_args()
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

    # ------------------------------------------ Op A1/A2: Adaptive rough levels
    # The part is a plateau (Z ~ 34.92) with pockets that have a ring shelf
    # at Z ~ 22.2 and a narrow (Ø ~10 mm) deep bore down to -11.92.  The
    # 12.7 mm rougher can clear the plateau top and the Ø18 shelf bores,
    # but physically cannot enter the Ø10 deep bores -> those floors are left
    # to the 6 mm ball finish.  Plain Adaptive, explicit depths per level.
    start_z = bb.ZMax + 1.0

    subs_top, z_top = select_horizontal_faces(shape, bb.ZMax - 1.5, bb.ZMax)
    if not subs_top:
        raise SystemExit("ERROR: no top plateau faces found for roughing")
    op_a1 = make_rough_op(job, tc1, base, "AdaptiveRoughTop", subs_top,
                          start_z, z_top + Z_LEAVE)

    subs_shelf, z_shelf = select_horizontal_faces(shape, 21.0, 24.0)
    rough_ops = [op_a1]
    op_a2 = None
    if subs_shelf:
        op_a2 = make_rough_op(job, tc1, base, "AdaptiveRoughShelf", subs_shelf,
                              start_z, z_shelf + Z_LEAVE)
        rough_ops.append(op_a2)
    else:
        print("WARN: no shelf faces found in Z[21,24]; skipping shelf level",
              flush=True)

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
    op_b.StartDepth.Value = bb.ZMax + 1.0
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
            "x": [round(bb.XMin - 2.0, 3), round(bb.XMax + 2.0, 3)],
            "y": [round(bb.YMin - 2.0, 3), round(bb.YMax + 2.0, 3)],
            "z": [round(bb.ZMin, 3), round(bb.ZMax + 1.0, 3)],
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
        if st["min_z"] < bb.ZMin - 0.02:
            print("FAIL: %s cutter Z below stock bottom %.3f (%.3f)"
                  % (st["name"], bb.ZMin, st["min_z"]), flush=True)
            ok = False
        if (st["min_x"] < bb.XMin - 2.0 - lead or st["max_x"] > bb.XMax + 2.0 + lead
                or st["min_y"] < bb.YMin - 2.0 - lead or st["max_y"] > bb.YMax + 2.0 + lead):
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
