# Spike notes: headless FreeCAD CAM (VibeCAD 26.3.1) on core_front.step

Run: `freecadcmd spike/run_cam.py samples/core_front.step out/` — exit 0 required.
(`sys.argv` DOES carry the extra args; freecadcmd additionally tries to load them as
documents, which is noisy but harmless. Env vars STEP_IN/OUT_DIR also supported.)

Outputs: out/core_front.ngc (combined), out/core_front_rough.ngc, out/core_front_finish.ngc,
out/core_front_job.FCStd (doc.saveAs), JSON summary between SUMMARY_JSON_START/END.

## Degenerate STEP geometry — healing exhausted, use plain Adaptive (Task B #2)

The STEP carries 3 BSpline faces (indices 202/212/215 in Part.read order) whose boundary
wires contain zero-length closed edges (point-sized, lengths 1e-14..2.3e-6 mm, collapsed
pole rows). Exact errors observed (repro: `freecadcmd spike/probe_degenerate_edges.py`):

- `Path.Geom.isVertical(face)` -> `TypeError: undefined curve type` on the 3 point-sized
  BSpline edges (via `Edge.Curve`); edges 537/556/563 at Z -7.0425, faces 202/212/215.
- Model-aware projection `_getSolidProjection(solid, z)` (Adaptive.py:1001 ->
  projectFacesToXY), live in run_cam.py on the RAW STEP: z=-11.62 and z=-8 ->
  `TypeError: undefined curve type`; z=10.16 and z=22 succeed (single face).
- During the healing rounds (probe_heal6/7/8, deleted), projecting the face-rebuilt
  shapes at z = -11.62 / -8 / 10.16 / 22 -> `OCCError: Invalid input shape for boolean
  CMN` (CMN = OCCT boolean common). Model-aware Adaptive swallows these tracebacks into
  an empty path — run_cam.py's `require_path()` turns that into a non-zero exit.

Healing attempts (rounds 1-2, all on out/probe_heal.log / run logs):
`shape.fix(1e-7,1e-7,1e-7)` (returns True, keeps all 3 edges), `removeSplitter()`,
self-`fuse()`, per-face `fix()`, `sewShape()`, `Part.Face(f.Surface)` +
`BSplineSurface.segment()` trim of the collapsed pole row reassembled via
`makeShell->makeSolid`: faces become `isVertical`-clean but the rebuilt solid is
`valid=False closed=False` (sewShape(0.05) cannot close it). Per supervisor round 2:
healing rounds used up — **no runtime monkeypatch and no shape healing**. run_cam.py
only *reports* the degeneracies at startup (`report_degeneracies`) and avoids the
model-aware code paths entirely.

Consequence for Adaptive (Task B #3): `ZStockToLeave` (App::PropertyDistance,
"How much stock to leave along the Z axis... **only used if the ModelAwareExperiment is
enabled**", Adaptive.py:1669; editor-hidden when off, line 1868) is the per-floor Z
stock-to-leave property — but it is gated behind model-aware mode, which is unusable on
this STEP. So roughing uses **plain (non-model-aware) Adaptive** with explicit depths:
plain mode is purely 2D (`_get_working_edges` + `TechDraw.findShapeOutline` of stock;
one pocket region swept from StartDepth to FinalDepth, Adaptive.py:1294/447), it has no
notion of floors. The part is a plateau at Z 34.92 with pockets that have ring shelves
at Z ~22.2 and Ø~10 mm deep bores down to −11.92; the 12.7 mm rougher cannot even enter
the Ø10 bores. Therefore: one plain Adaptive op per reachable floor level, each with
`FinalDepth = floor_z + 0.3` (top plateau op -> 35.22, shelf op -> ~22.5); the deep
−11.92 floors are left entirely to the 6 mm ball finish. `ZStockToLeave=0.3` is still
set on the ops (documented intent) but plain mode ignores it.


## Part ground truth — the "floors" at Z 10.16 / -11.92 are not top-accessible

Measured on the STEP directly (booleans + distToShape + OCL drop-cutter) and on the
heightfield (out/core_front_hf.npy; regenerating reproduces it bit-identically):

- Plateau top Z 34.925 (face 242, area 33275); ring shelves Z 22.22 (6×, ~Ø18 outer);
  downward-facing bottom face Z 10.16 (face 9, area 20016) — the core's underside.
- The 7 "deep bores" are Ø ~10 mm THROUGH-holes: sampling points along three bore axes
  and the centre axis with `Part.Vertex(...).distToShape(solid)` returns void (>6 mm to
  any material) over the full Z range; a 0.4×0.4 mm column boolean returns no solids.
- In the heightfield, empty columns (through-bores + outside any face) hold the fill
  value = bbox ZMin (-11.9185 tight / -12.1374 loose OCCT bbox). So hf cells at
  "-11.92" are EMPTY, not floors — zmap's `footprint = part > bottom` already excludes
  them from gouge/leftover stats.
- Lowest top-accessible machined surface: bore-mouth fillets (toroid/cone) just below the
  shelves; OCL BatchDropCutter with the 6 mm ball gives CL min 19.546. SteepShallow's
  observed min Z 19.60 is therefore correct behaviour, not a stall: with 3-axis access
  from above there is nothing to cut below ~19.5 (no floor — the bores go through).
- Consequence: SteepShallow cannot and must not reach -11.92; run_cam.py acceptance
  checks it reaches the shelf floor (lowest reachable floor) instead. The through-bores
  would need a drill/bore op — out of scope for this spike.

## What worked (API + property names)
- Import: `Part.read(path)` -> `doc.addObject("Part::Feature").Shape`.
- Job: `Path.Main.Job.Create(name, [baseObj], createDefaultStock=False)`; add controllers via
  `job.Proxy.addToolController(tc)`. SetupSheet/VarsTable are created automatically.
- Stock: `Path.Main.Stock.CreateBox(job, App.Vector(L,W,H), App.Placement(origin,...))` then
  assign `job.Stock = obj` (CreateBox does NOT link it itself). Extents are Length/Width/Height
  + Placement origin (corner, not center).
- Tools: `Path.Tool.Controller.Create(name, toolNumber=n, document=doc)` auto-creates a flat
  endmill bit; ball mill via `ToolBit.from_shape_id("ballend.fcstd")` +
  `.attach_to_doc(doc=doc)`, passed as `tool=`. Set `tc.Tool.Diameter`, `tc.SpindleSpeed`,
  `tc.HorizFeed/VertFeed` (Quantity "mm/min").
- Adaptive: `Path.Op.Adaptive.Create(name, parentJob=job, toolController=tc)`; geometry via
  `op.Base = [(baseObj, ["FaceN", ...])]` — **plain mode needs explicit face sub-names**;
  `[(baseObj, [])]` yields "Adaptive operation couldn't determine the boundary wire. Did
  you select base geometry?" and an empty path (Adaptive.py:434-441). Properties:
  `ModelAwareExperiment` (True = 3D/model-aware — unusable here, see above),
  `UseOutline=True` (machine each selected face's OuterWire; turns ring/shelf faces into
  solid discs), `StepDown.Value`, `StockToLeave.Value`, `ZStockToLeave.Value` (all
  Distance), `StepOverPercent=15`, `FinishingProfile=False`. Clear setup expressions
  before numeric assignment: `op.setExpression("StepDown", None)` etc.
- Adaptive Z/floor stock-to-leave (Task B #3): `ZStockToLeave` (App::PropertyDistance,
  "How much stock to leave along the Z axis... only used if ModelAwareExperiment is enabled",
  Adaptive.py:1669). Mechanism (Adaptive.py:1049-1054/1219): the model+stock are sliced at
  `depth - ZStockToLeave` per stepdown, so pockets stop >= ZStockToLeave above each floor.
  Set `op.setExpression("ZStockToLeave", None); op.ZStockToLeave.Value = 0.3`. Because it
  is model-aware-only and model-aware fails on this STEP (see above), the practical floor
  leave in plain mode is `FinalDepth = floor_z + 0.3`, one op per floor level.
- SteepShallow: `Path.Op.SteepShallow.Create(name, parentJob=job, toolController=tc)`.
  NO `Base` property (uses job model geometry; setting op.Base raises AttributeError).
  Depth props are Distance (assign `.Value` AFTER `setExpression(prop, None)`; the default
  FinalDepth expression otherwise resolves to the part top and clamps every pass high):
  `StartDepth`, `FinalDepth`, `StepDown`. Classification/coverage props
  (opPropertyDefinitions in Path/Op/SteepShallow.py): `SlopeThreshold` (Angle; steep >=
  angle gets constant-Z waterlines, shallow gets surface-following parallels), `StepOver`,
  `BoundaryOverlap` (shallow grows into steep by this distance), `CutMode` Climb/
  Conventional, `SampleInterval` (drop-cutter grid spacing), `UseRestMachining` +
  `RestReferenceToolDiameter`, `LinearDeflection`/`AngularDeflection` (tessellation).
  opExecute clamps the CL heightfield to `max(hf, FinalDepth)`; contours step from
  z_max down to the clamped min; shallow passes follow the CL surface, so with an
  explicit FinalDepth = stock bottom the passes reach the part floors.
- Posting: `PostProcessorFactory.get_post_processor(job, "linuxcnc")`, then mimic
  CAMTests/TestLinuxCNCPost: `post.reinitialize(); post._machine =
  Machine.create_3axis_config(); post.apply_configuration_bundle();` plus one `Toolhead`
  (`Machine.models.machine`), then `post.export2()` -> [(sectionname, gcode_str)]. No GUI.
- Per-op G-code files: export2 posts the whole job; to get one tool per file, toggle
  `op.Active = False` on the other op, re-create the post processor and export2 again
  (each file then carries its own header + tool change). Restore Active afterwards.
- Save: `doc.saveAs(out/core_front_job.FCStd)` works headless with the Job + stock +
  tools + op paths persisted.

## zmap chaining (verify/zmap.py)
`--stock-out X.npy` saves the final stock heightfield; `--stock-in X.npy` starts a run
from it (same grid as --part; cells outside --stock still -inf). `--stock` may be omitted
with `--stock-in` (box derived from the saved state's finite cells). Chain rough ->
finish to judge one op at a time; chained result == single combined sim (tested).

## Gotchas
- Default `FinalDepth` expression resolved to the PART top (34.9 mm), not stock bottom, when
  stock is assigned after Job.Create -> adaptive cut one layer. Fix: clear expressions and set
  StartDepth/FinalDepth explicitly from the stock bbox (`.Value = mm`).
- Adaptive lead-in/out overtravel puts cutter centers up to ~1 tool radius (5.7 mm) outside the
  stock box — expected, cuts only air; acceptance margin uses tool radius + 1 mm.
- An op that swallows an internal error yields `len(op.Path.Commands) == 0`; run_cam.py
  checks this after every recompute (`require_path`) and exits non-zero — never silent.
- freecadcmd buffers Python stdout; a hard crash loses prints — use flush=True / PYTHONUNBUFFERED.
- SetupSheet logs "has no support for SteepShallowFinish" — informational only.

## Results (final run, exit 0, ACCEPTANCE: PASS)

- AdaptiveRoughTop   (T1 flat 12.7): 22474 cmds, min Z 35.225 = plateau 34.925 + 0.3 ✓
- AdaptiveRoughShelf (T1 flat 12.7):  2874 cmds, min Z 22.525 = shelf 22.22 + 0.3 ✓
- SteepShallowFinish (T2 ball 6):   281862 cmds, min Z 19.604 — reaches the shelves and
  bore-mouth fillets, i.e. every top-accessible surface (see ground truth above; the
  -11.92 "floor" is through-holes, not a floor).
- Files: out/core_front.ngc (combined, T1+T2), out/core_front_rough.ngc (T1 only),
  out/core_front_finish.ngc (T2 only), out/core_front_job.FCStd (doc.saveAs).
- zmap: out/zmap_rough.json (flat 12.7, stock box from summary JSON) and
  out/zmap_finish.json (ball 6, chained via --stock-in out/stock_after_rough.npy).
