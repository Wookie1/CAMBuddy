# Spike notes: headless FreeCAD CAM (VibeCAD 26.3.1) on core_front.step

Run: `freecadcmd spike/run_cam.py samples/core_front.step out/` — exit 0, both ops > 100 moves,
min Z -11.84, ngc ~6 MB. (`sys.argv` DOES carry the extra args; freecadcmd additionally tries to
load them as documents, which is noisy but harmless. Env vars STEP_IN/OUT_DIR also supported.)

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
  `op.Base = [(baseObj, [])]`. Properties: `ModelAwareExperiment=True` (3D/model-aware),
  `StepDown.Value`, `StockToLeave.Value`, `ZStockToLeave.Value` (all Distance),
  `StepOverPercent=15`, `FinishingProfile=False`. Clear setup expressions before numeric
  assignment: `op.setExpression("StepDown", None)` etc.
- SteepShallow: `Path.Op.SteepShallow.Create(name, parentJob=job, toolController=tc)`.
  NO `Base` property (uses job model geometry; setting op.Base raises AttributeError).
  Plain float properties: `StartDepth`, `FinalDepth`, `StepDown`, `SlopeThreshold=45`,
  `StepOver`, `SampleInterval`, `LinearDeflection`. Needs `opencamlib` (present).
- Posting: `PostProcessorFactory.get_post_processor(job, "linuxcnc")`, then mimic
  CAMTests/TestLinuxCNCPost: `post.reinitialize(); post._machine =
  Machine.create_3axis_config(); post.apply_configuration_bundle();` plus one `Toolhead`
  (`Machine.models.machine`), then `post.export2()` -> [(jobname, gcode_str)]. No GUI needed.

## Gotchas / experimental bits
- Default `FinalDepth` expression resolved to the PART top (34.9 mm), not stock bottom, when
  stock is assigned after Job.Create -> adaptive cut one layer. Fix: clear expressions and set
  StartDepth/FinalDepth explicitly from the stock bbox.
- `ModelAwareExperiment` crashed on this STEP: 3 degenerate point-sized edges on BSpline faces
  raise OCCT "undefined curve type" inside `Path.Geom.isVertical` / `projectFacesToXY`, and the
  op swallows the traceback into an empty path. Workaround in run_cam.py: monkeypatch shim that
  skips faces with degenerate curves (zero-area pole caps). See probe_degenerate_edges.py.
- Adaptive lead-in/out overtravel puts cutter centers up to ~1 tool radius (5.7 mm) outside the
  stock box — expected, cuts only air; acceptance margin uses tool radius + 1 mm.
- SteepShallow finished only Z >= 19.86 on this part: the low, drafted walls are classified
  shallow but the heightfield only emits passes over top-facing regions. May need slope tuning.
- freecadcmd buffers Python stdout; a hard crash loses prints — use flush=True / PYTHONUNBUFFERED.
- SetupSheet logs "has no support for SteepShallowFinish" — informational only.
