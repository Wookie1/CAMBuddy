# Spike notes: headless FreeCAD CAM (VibeCAD 26.3.1) — Core Front, setup coords
Run `freecadcmd spike/run_cam.py [step] [out/] [--stock XMIN XMAX YMIN YMAX ZMIN ZMAX]`
— exit 0 required; env STEP_IN/OUT_DIR/STOCK/MODEL_AWARE also work. Defaults:
samples/core_front_setup.step, out/, stock X±128.651 Y±82.55 Z 0..60.96. Outputs:
out/core_front.ngc + _rough/_finish.ngc, core_front_job.FCStd, JSON between
SUMMARY_JSON_START/END (freecadcmd buffers stdout — flush=True). Probes:
spike/probe_seat.py + probe_finish_gouge.py via freecadcmd (no heredoc stdin).
## Setup orientation (Task C #1, spike/orient.py)
- Core Front: rotate 180° about X then Z+34.925 -> bbox X±126.36 Y±69.85 Z 0..46.84
  (tol 0.05, optimalBoundingBox; plain BoundBox loose on BSplines); mapping z_setup = 34.925 − z_design, y_setup = −y_design.
- Cavity Front: samples/cavity_front_setup.step is delivered ALREADY in setup coords
  (round 3) -> orient.py verifies bbox X±126.36 Y±69.85 Z 0..60.96 only; old cavity_front.step was an empty export (null shape) — skip no-geometry sources.
## Part ground truth (setup Z; OCC column booleans + heightfield)
- Machined floor 24.76 (design face 9, area 20016); plateau top 46.84 (= design −11.92);
  seat floors 39.22; shelves 12.7; part bottom (design plateau top 34.925, area 33275) at Z≈0 = heightfield fill -> empty columns indistinguishable; zmap footprint `part > bottom` handles it. The 7 "deep bores" Ø~10 mm are THROUGH-holes (column boolean void over full Z) — bbox-bottom cells are empty, not floors.
- Insert seats: 37.4×37.4 mm rounded rects (corners R8.86), centres (±67, 0), floor
  39.22; wall faces vertical and sit ON the INSERT CONTOUR line (±0.1 mm probes).
## Degenerate STEP geometry (rounds 1–2; healing exhausted, none allowed)
- 3 BSpline faces carry zero-length closed edges (1e-14..2.3e-6 mm) at setup Z 41.9675
  (design −7.0425): `Path.Geom.isVertical(face)` -> `TypeError: undefined curve type`;
  `_getSolidProjection` fails at slices below (setup z 24.77, 12.93 -> TypeError;
  model-aware Adaptive swallows it into an empty path — require_path() exits non-zero);
  slices 46.55/42.92 project fine. fix(1e-7)/removeSplitter/fuse/sewShape/
  BSpline-pole-trim all fail to rebuild a valid closed solid; no monkeypatching —
  run_cam.py reports degeneracies and avoids model-aware paths.
- ModelAwareExperiment ONCE on reoriented shape (round 3, MODEL_AWARE=1): SUCCEEDED —
  "ModelAwareExperiment=True, 19827 cmds in 1.0 s" (depth range stayed above the failing
  slices). Kept OFF for production; plain Adaptive unchanged.
- Plain Adaptive is purely 2D (no floors; Base needs explicit face sub-names — [(obj,
  [])] -> "couldn't determine the boundary wire"). One op per reachable floor, FinalDepth = floor+0.3: top op 47.145 (plateau 46.84+0.3); shelf op skipped (annulus ~4 mm, unreachable by Ø12.7 — logged). `ZStockToLeave` is model-aware-gated (Adaptive.py:1669) — set but ignored in plain mode.
## What worked (API + property names)
- Job: Path.Main.Job.Create(name,[obj],createDefaultStock=False); controllers via
  job.Proxy.addToolController(tc). Stock: Path.Main.Stock.CreateBox(job, Vector(L,W,H),
  placement-at-corner) THEN job.Stock = obj (CreateBox does not link it).
- Tools: Path.Tool.Controller.Create(name, toolNumber=n, document=doc) = flat endmill;
  ball via ToolBit.from_shape_id("ballend.fcstd")+attach_to_doc as tool=; set tc.Tool.Diameter, tc.SpindleSpeed, tc.HorizFeed/VertFeed (Quantity "mm/min").
- Adaptive: Path.Op.Adaptive.Create(name, parentJob, toolController); op.Base =
  [(baseObj, ["FaceN",...])]; props ModelAwareExperiment, UseOutline (face OuterWire),
  StepDown/StockToLeave/ZStockToLeave (Distance), StepOverPercent, FinishingProfile. Clear setup expressions first (op.setExpression("StepDown", None)): the default FinalDepth expression resolves to PART top when stock is assigned after Job.Create (adaptive then cuts one layer); always set Start/FinalDepth numerically.
- SteepShallow: Path.Op.SteepShallow.Create(...); NO Base property (uses job model).
  Distance props via setExpression(prop,None) then .Value: StartDepth/FinalDepth/
  StepDown; SlopeThreshold (Angle), StepOver, BoundaryOverlap, CutMode, SampleInterval,
  UseRestMachining+RestReferenceToolDiameter, Linear/AngularDeflection. opExecute
  clamps CL to max(hf, FinalDepth); shallow passes follow the CL surface — explicit FinalDepth = stock bottom reaches all floors (and can overcut, see Results). SetupSheet "no support for SteepShallowFinish" = informational.
- Posting: PostProcessorFactory.get_post_processor(job, "linuxcnc"); mimic
  CAMTests/TestLinuxCNCPost (reinitialize, _machine = Machine.create_3axis_config(), apply_configuration_bundle, one Toolhead from Machine.models.machine), post.export2(). Per-op files: op.Active=False on others, re-create post, export2 again. doc.saveAs(FCStd) persists everything headless.
## verify/zmap.py (round 3)
- Plane-aware arcs: G17 XY(I,J), G18 ZX(I,K), G19 YZ(J,K); interpolated in-plane
  (helical axis linear); K parsed; bare G17 no longer emits a phantom modal arc move.
- G41/G42 default = Fusion "wear" model: simulate as programmed (D value unknown) and
  count comp-active moves -> JSON cutter_comp {active_moves, first/last_line,
  d_registers}. --comp-radius R = registry-style diagnostic: activation (G41) and cancel (G40) blocks run as programmed, interior offset perpendicular/concentric with miter joins. Gouge tol 0.02 mm; footprint = part > grid bottom. Chaining --stock-out/--stock-in (exact); --window = cells within 2 mm of steep walls (|dZ|>1 mm); --jobs N: stock/stats exact, rapid-collision counts approximate.
## Results (details in out/bench.json + zmap JSONs)
- run_cam_C (setup STEP, ACCEPTANCE: PASS): AdaptiveRoughTop 19606 cmds minZ 47.144;
  SteepShallowFinish ball-6 395943 cmds minZ 8.144; zmap rough: 0 gouges, 0 rapids.
- Fusion wear sim of 1001.nc = 7778 gouge cells, ALL inside INSERT CONTOUR (lines
  40330–40361, G41 D03): the programmed contour sits on the seat wall face, so as tool centre it cuts ~6.2 mm into the wall = comp-model artifact, not misalignment (floor 24.76 vs ZMIN 24.95). --comp-radius 6.223 -> 136 cells (single-cell slivers at R8.86 corners, ≤0.13 mm past the wall = quantization) = clean at model res. Cycle: Fusion ~1067 s vs ours ~19707 s (ball finish dominates).
- Ours, finish chained: 2411 gouge cells @0.5 mm (603 mm²), max depth 10.69 at
  (−114.6, 56.9) — SteepShallow drives the ball into the outer rim wall (surface 38–42 mm there). Item 5: persists at 0.1 mm — 63599 cells (636 mm²), 100 % of the 0.5 mm cells reproduced within 0.25 mm -> real toolpath issue, not grid artifact; --window finds the same. Leftover mean 0.137/p95 0.977; within-0.5 mm 0.917 (Fusion: 0.626).
