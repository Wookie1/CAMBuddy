# Task E (round 5): engine skeleton + 3D adaptive roughing on OpenCAMLib + libarea Adaptive2d
Decision: no more VibeCAD SteepShallow / model-aware Adaptive ops. Mesh-based engine. spike/ is an archive: do not
edit it (read it for reference). No MCP tools, no questions, do not commit, probes go in engine/probe_*.py.
Run ocl/area code with /Applications/VibeCAD.app/Contents/Resources/bin/python (3.11) or freecadcmd; zmap with
/opt/homebrew/bin/python3. OpenCAMLib: `from opencamlib import ocl`. libarea: `import area; a2d = area.Adaptive2d()`.
Reference usage of Adaptive2d (properties, Execute(stockPaths, paths, clearedArea, progressFn), result format,
helix/keep-tool-down): /Applications/VibeCAD.app/Contents/Resources/Mod/CAM/Path/Op/Adaptive.py lines ~470-580.
Part samples/core_front_setup.step (Z 0..46.844, main floor 24.8). Stock X+-128.651 Y+-82.55 Z0..60.96.

0. Package engine/: model.py (STEP -> STL at 0.01 mm via freecadcmd, cached in out/; load into ocl.STLSurf; reusable
   by the next round's finishing), rough.py, gcode.py (neutral move list -> G21 G90 G-code; LNC post later),
   cli.py: `python -m engine.cli rough --step S --stock xmin xmax ymin ymax zmin zmax --tool bull:12.7:0.127 --out F`.
1. Per-level islands: Z levels from stock top down, stepdown 1.9 mm, last level = 24.8 + 0.3. At each Z get the
   cutter-centre boundary the tool must not cross: ocl.Waterline (or AdaptiveWaterline) with a cutter of radius
   tool_r + 0.3 radial allowance (cylinder/bull) at that Z. Those loops = islands in cutter-centre space.
2. Clearing region per level = stock outline (cutter-centre space, grown so the tool clears the stock edge) minus
   islands -> area.Adaptive2d, stepover ~15% D (Fusion ~2.0 mm), helix entry when it cannot enter from outside,
   keep-tool-down linking. Adaptive2d offsets boundaries by tool radius itself: PROVE the convention with a tiny
   synthetic test (square boss in a box: tool centre stays exactly tool_r + allowance from the boss) in
   engine/test_engine.py before using it on the part.
3. Feeds: S7500, cut 3429 mm/min, ramp 1270 mm/min. Levels top down; retract to a clearance plane between
   disconnected regions.
4. Judge with zmap on out/core_front_setup_hf.npy, same stock, tool bull 12.7/0.127: gouges MUST be 0. Write
   out/bench_engine_rough.json with ours vs spike/bench_rough.json "fusion": rapid collisions, leftover mean/p95/max,
   within_0p5mm_fraction, cutting length, est. time.
5. zmap rapid check: zmap reports 41 rapid collisions in Fusion's roughing (out/fusion_rough.ngc). Find out if they
   are an artifact (stock thinner than a cell, footprint rounding, rapid sampling). If artifact: fix zmap (e.g.
   ignore < one cell depth, or sample rapids at 0.25 cell) + a test. If real: show one (line, XY, depth).
Run `/opt/homebrew/bin/python3 -m pytest verify -q` and the engine tests before finishing. Print the bench JSON.

## Supervisor note (relaunch after an OpenCode hang)
Your previous session hung right after: "a2d is the bottleneck (52-255 s/level, serial). Testing keepToolDown/
tolerance impact and then parallelizing levels". Levels are independent: run Adaptive2d per level in a
multiprocessing pool (this Mac has many cores; use os.cpu_count()-2 workers), keep levels ordered top-down in the
output. Keep tolerance sane (FreeCAD default ~0.1) and log per-level timing. Check git diff/out/engine_rough_run.log
for where you were, then finish items 1-5.
