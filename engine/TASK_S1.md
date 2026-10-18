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
