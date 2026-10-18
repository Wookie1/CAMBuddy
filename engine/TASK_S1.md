# Task S1 (track B): our own Steep & Shallow finishing, engine/finish.py, from OpenCAMLib CL points only
Rules: no MCP, no questions, do not commit, probes in engine/probe_*.py, spike/ untouched, long runs in the
foreground. Touch only engine/finish.py, engine/test_finish.py, the cli `finish` subcommand, and verify/ if zmap
needs a fix (with a test). Do not edit engine/rough.py or engine/stock.py (another track owns them).
Reuse engine/model.py (STL + ocl.STLSurf; cached out/core_front_setup.stl). OCL: `from opencamlib import ocl`, run
with /Applications/VibeCAD.app/Contents/Resources/bin/python. Context: VibeCAD's SteepShallow gouged because its
steep contours misplace the tool next to slots narrower than the ball (spike/DIAG_steepshallow.md).

1. Shallow: drop-cutter raster (ocl BatchDropCutter / PathDropCutter, 6 mm ball) along X at stepover 0.3 mm
   (param), sampled at 0.1 mm. Slope per CL point from the CL-surface gradient. Keep points with slope < threshold
   (param, default 40 deg) plus a 1 mm overlap band.
2. Steep: ocl AdaptiveWaterline at Z levels from part top to floor, stepdown param (default 0.3 mm). Keep loop
   segments where slope >= threshold - overlap.
3. Gouge-safe simplification: drop a point only if the chord stays >= the true CL surface within 0.005 mm
   (one-sided check against drop-cutter samples along the chord). Links within a row: stay down only if
   drop-cutter along the link stays below the link height; else retract to local max + 1 mm.
4. Synthetic tests (engine/test_finish.py, pure OCL on generated STLs, no FreeCAD): hemisphere on a plate;
   60-degree cone; vertical-walled boss with a slot narrower than the ball. zmap at 0.1 mm: 0 gouges on all three;
   report % of surface left > 0.05 mm per zone (steep / shallow).
5. Then on core_front_setup after the roughing out/core_front_roughF.ngc (chain zmap --stock-out/--stock-in;
   rough with bull 12.7/0.127, finish with ball 6). Report zmap gouges (0.1 mm heightfield out/core_front_setup_hf01
   near walls), leftover after finishing by slope zone, length and time. Write out/bench_finish_s1.json.
Run /opt/homebrew/bin/python3 -m pytest verify -q and the finish tests before finishing.

## Supervisor note (relaunch)
The previous session was aborted by the local oMLX memory guard (context too long), not by your code. Your
work is in the tree (engine/finish.py, engine/test_finish.py, cli.py changes): check git diff first. You were
investigating 10 tiny over-cuts (0.02-0.07 mm, ball surface 9.93-9.98 vs wall top 10.0) on the slot-boss test
around (-15, 12) at Z 7.6-9.4 - steep waterline points within the ball radius of the slot edge. Decide if they are
real (fix: the waterline must come from ocl with the same 6 mm ball, sampling fine enough) or a zmap sampling
artifact (prove with a finer sample). Keep messages short and avoid printing large outputs, to keep context small.
- Relaunch 3 (now on a different model): the previous session got the hemisphere test clean and changed
  test_finish.py to assert on tool-reachable cells (reporting raw and reachable fractions). Next: run the full
  finish suite, then item 5 on core_front_setup.

## Round S1b (supervisor)
The full core_front finishing run took > 70 min single-process and OpenCode ended your session for inactivity.
1. Add an ENGINE_WORKERS-capped pool (default 4) to engine/finish.py the way engine/cli.py/rough.py do it:
   split shallow raster rows and steep waterline Z levels across workers; keep output order deterministic.
2. Keep engine/test_finish.py passing (3 shapes, 0 gouges). Time it before/after.
3. Smoke test on core_front_setup: a 60 x 40 mm window around (-114.6, 56.9) only (add --window xmin xmax ymin ymax
   to the finish CLI), and report its runtime. Do NOT run the full part; the supervisor runs it.
4. Note in the report: plunge length exceeds cut length on slot-boss (9854 vs 7358 mm) - check that link/retract
   logic does not plunge at every row; reduce it if it's simple and safe.
Short outputs. Print timings and the smoke stats at the end.

## Round S1c (supervisor): fix the finishing bottleneck
Diagnosis (stack sample of the full core_front run, 80+ min single-core): almost all time is in
ocl::BatchDropCutter::setSTL -> Bbox::addTriangle. engine/finish.py batch_drop() builds a NEW BatchDropCutter and
calls setSTL (re-indexes all 248k triangles) on every call, and the gouge-safe simplification calls it once per
candidate chord (finish.py ~line 439), i.e. thousands of times.
Fix (keep it gouge-safe, same 0.005 mm one-sided chord rule):
1. Simplify in verify-and-split rounds instead of per-chord calls: propose a simplification (e.g. Douglas-Peucker
   on the CL polyline at the chord tolerance), then check ALL resulting chords' interior samples (line_ss spacing)
   in ONE batch_drop call; for each failing chord re-insert the original point(s) it skipped (e.g. the one with max
   deviation) and re-check only the failing ones in the next single call; repeat until none fail (cap rounds,
   fall back to keeping all points). Same for link checks: batch every link's samples into one call.
2. Count batch_drop calls (log them) and assert in the tests that a run makes O(rounds) calls, not O(chords).
3. Keep engine/test_finish.py passing (0 gouges on hemisphere, cone60, slot-boss) and time it before/after.
4. Rename user-facing "steep & shallow" wording to "slope-split finishing" / action name slope_split_finish in
   finish.py docstrings, CLI help and logs (keep internal function names if you like).
5. Then run the window smoke test (--window -144.6 -84.6 36.9 76.9) and report its runtime. Do NOT run the full part.
Short outputs.
6. (Added) Index the STL as few times as possible: OCL's BatchDropCutter has no clear/replace-points method
   (methods: appendPoint, getCLPoints, run, setSTL, setCutter, setThreads, setBucketSize), so one instance cannot be
   reused across batches without re-running old points. Therefore: make every phase gather its points and call
   batch_drop once per round; add a module-level counter of setSTL calls and a test that asserts the count per
   finish() run is bounded by a small constant times the number of verify rounds (print it).

## Round S1d (supervisor): full Core Front run gouges - fix first
Full run (S1c code, ball 6, --floor 24.765, after round-7 roughing) at zmap 0.1 mm: 10,815 gouge cells, max 12.08 mm
at (116.8, 50.8); rapids 0, leftover p95 0.44 mm. Supervisor diagnosis with OCL drop-cutter: the worst moves are steep
waterline moves at exactly Z 24.765 (the --floor value; 15,502 such lines, G-code lines ~183k-305k), where the true
ball CL is ~36.85 (e.g. line 209170, x 119.655 y 50.785). The floor level coincides with the part's main flat floor
(~24.76-24.8), so the waterline at that Z is degenerate (coplanar with flat faces) and runs across raised areas.
1. Gouge-safe by construction: before emitting, run a ONE-SIDED CL check on EVERY cutting point and every segment's
   interior samples (line_ss) of the steep pass too (batched, one or a few batch_drop calls): any point whose Z is
   below the drop-cutter CL by > 0.005 mm is dropped/split out of its run (never moved down). Count and log removals.
2. Never place a waterline level within 0.05 mm of a flat face Z (detect flat-face Zs from the STL, triangles with
   normal z ~ 1); shift that level up by 0.05 mm or skip it (the shallow raster covers flats).
3. Synthetic regression test: plate with a raised boss whose plate top equals the requested floor; zmap 0.1 mm must
   show 0 gouges; also assert the check in 1 removes the bad points if item 2 is disabled.
4. Then (only after 1-3 pass): clipped waterline per level - pass only triangles whose z-range overlaps
   [level - margin, level + ball radius + margin], clipped to the region; test clipped vs unclipped loops equal on
   a synthetic shape. Do NOT change the 0.3 mm wall stepdown.
5. Do not run the full part; run the 3+1 synthetic tests and the window smoke (--window 96.8 136.8 30.8 70.8, which
   contains the worst gouge) with --floor 24.765, then zmap that window output at 0.1 mm against
   out/core_front_setup_hf01.npy starting from out/stock_roughG_01.npy, and report gouges.
Short outputs.
6. (Added) When the one-sided check removes points, SPLIT the run there; rejoin the pieces only through the checked
   link logic (retract or a short lift verified clear by drop-cutter along the link). Never bridge a gap at cutting
   depth. Raising a point up to its CL is also acceptable; never lower one. Add a test where removal creates a gap and
   assert the resulting link is verified clear (no sample below CL).
7. (Supervisor, IMPORTANT) The floor level is NOT the main problem. An exact OCL check of the whole S1c output
   (engine/probe_clcheck.py: every cutting move sampled at 0.25 mm, BallCutter(6) drop-cutter, one-sided) found
   76,543 points below CL by > 0.005 mm: only 1,281 at Z 24.765; 75,262 elsewhere, max 11.9 mm, depth histogram
   [0.005-0.02: 19485, -0.1: 3588, -0.5: 9002, -2: 15612, >2: 27575]. Most common Zs of bad points: 31.92 (9290),
   43.84 (5909), 31.84, 31.24, 30.04, 30.34, 30.94, 27.64 (~1630 each) - i.e. STEEP WATERLINE LOOPS at many levels
   pass where the ball does not fit (worst x=+-94.975 y=50.761 z=24.944, lines 207636/91349). Find why before
   relying on item 1 alone: e.g. AdaptiveWaterline sampling/min_sampling too coarse for narrow features, a cutter
   mismatch between waterline and drop-cutter (diameter/length/BallCutter vs CylCutter), loops of the wrong
   side/nesting, or simplification bridging loop points. Run probe_clcheck.py on your outputs as the acceptance
   check (it must report 0 points below CL by > 0.005 mm), in addition to zmap.
8. (Supervisor, ROOT CAUSE) Stage 1 is the culprit: RAW OCL waterline loops already violate the CL. At Z 31.92 on
   core_front_setup.stl with BallCutter(6.0, 50): AdaptiveWaterline -> 9 loops, 11,962 pts, 666 below drop-cutter CL
   by > 0.005 (max 7.625); plain ocl.Waterline -> 655 (max 7.625). Many sit exactly ~3.07 mm under (about the ball
   radius). Cutter object and Z-as-tip are correct. OCL waterline traces where the cutter at height z touches the mesh
   from ANY side (incl. material above the cutter / overhangs), which 3-axis-from-above cannot use. Fix: after
   computing loops, drop-cutter every loop point (batched) and keep only points with CL - z <= 0.005 mm; split loops
   at removed points; relink pieces through the verified link logic. This is item 1 applied at the source; then the
   final probe_clcheck must report 0.

## Round S2 (supervisor): PLAN B - steep passes from a drop-cutter CL grid (replaces OCL waterline). Supersedes S1d.
Root cause (S1d items 7-8): raw OCL Waterline/AdaptiveWaterline loops with BallCutter(6) are wrong by ~r in places
(Z 31.92: ~660 loop points below drop-cutter CL, max 7.6 mm; same after re-meshing). Filtering would leave walls
uncut, so do not use OCL waterline for steep passes.
1. ONE batched drop-cutter CL grid (batch_drop, BallCutter same as everywhere) over the steep-region mask dilated by
   the ball radius: 0.1 mm pitch in steep regions, coarser elsewhere is fine. Computed once per run, not per level.
2. Per Z level (keep 0.3 mm stepdown, shift levels within 0.05 mm of a flat-face Z up by 0.05 mm, keep the slope
   split): marching squares on that grid for the iso-contour CL = Z, with {CL >= Z} as material side.
3. Refine each contour point by batched bisection along the grid gradient to |CL - Z| <= 0.002 mm (one batch_drop per
   bisection round for all points of all levels).
4. Final safety net: one-sided check of every emitted cutting point and segment sample (CL - z <= 0.005 mm); remove
   violators, SPLIT runs there, rejoin only through verified links (retract or short lift checked clear). Never bridge
   at cutting depth; raising to CL is ok, never lower.
5. Tests (engine/test_finish.py): hemisphere and 60-degree cone contours vs analytic circles (CL radius for a ball on
   a hemisphere/cone at height Z), slot-boss and a plate-at-floor case 0 gouges at zmap 0.1 mm, a gap-split test whose
   link is verified clear, and engine/probe_clcheck.py == 0 on every synthetic output.
6. Smoke: --window 96.8 136.8 30.8 70.8 on core_front_setup with --floor 24.765; probe_clcheck on it must report 0.
   Report timings. Do NOT run the full part (supervisor does). Report per level: contour points, removed points.
Keep outputs short. Long jobs in the foreground of your shell command.

## Round S2b (supervisor): keep the wall contours at CL jumps
The "spurious rings" are the REAL wall contours. Next to a vertical wall (top T, floor F) the ball CL jumps from F
to T - r at distance r from the wall, so every level between F and T - r lies exactly on that jump: the correct
waterline is the jump line at offset r. Bisection can never reach |CL - Z| <= 0.002 across a jump, so those points
were wrongly rejected (slot-boss steep runs 35 -> 2, window removed 32,759 / 50,741).
1. Bisection converges on the bracket's XY width (<= 0.002 mm), not on |CL - Z|. Emit the LOW-side endpoint
   (CL <= Z + 0.005): gouge-safe and touching the wall. Reject a point only if no sign change can be bracketed.
2. Keep the one-sided nets (vertex + segment + rounded coords) unchanged; they must still pass.
3. New test: vertical cylinder boss (radius R, height H > r + several stepdowns) on a floor: expect one circle of
   radius R + r (+-0.01) at every level from floor up to H - r; probe_clcheck == 0; zmap 0 gouges at 0.1 mm.
4. Assert slot-boss steep run count and wall leftover are back near S1b's (S1b: steep_runs=35, cut ~7.6 m).
5. Re-run the window smoke (--window 96.8 136.8 30.8 70.8 --floor 24.765): report removed points per level,
   probe_clcheck (must be 0) and timing. Do NOT run the full part. Do not commit (the supervisor commits).
