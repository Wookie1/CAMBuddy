# Task F (round 6): match Fusion's adaptive settings, fix lost allowance, re-benchmark
Same rules: no MCP, no questions, do not commit, probes in engine/probe_*.py, spike/ untouched.
Fusion Overall Roughing (read from Fusion, authoritative): top = stock top 60.96, bottom 24.765, MAX STEPDOWN
19.05 mm (0.75 in), optimal load 2.03 mm (0.08 in), stock to leave 0.381 mm (0.015 in). Deep and light: ~1.5xD
axial, 2 mm radial. Fusion's "1.9 mm" was its stepover, not its stepdown.

1. Settings: stepdown 19.05, Adaptive2d optimal load / stepover 2.03 mm (stepOverFactor = 2.03/12.7), radial leave
   0.381, final floor 24.765 + axial leave (0.381; or match Fusion's ZMIN 24.95 if closer — report which).
   Flat-area levels: find flat floors in the part heightfield (large areas at one Z between stepdown levels) and add
   a level at each floor + axial leave (like Fusion's flat area detection). Print the final level list.
2. Lost allowance: round 5 lost the 0.3 mm radial allowance near (26.2, 6.65) at Z 41.96 (tool centre 6.277 mm from
   taller material vs 6.65 intended). Tighten OCL waterline sampling (try 0.1 mm) and Adaptive2d tolerance. Then a
   HARD post-check in engine/rough.py: per level, min distance from every CL point to that level's island loops
   >= tool_r + radial_leave - 0.02 mm; otherwise fail the run with the location. Add it to the synthetic test too.
3. zmap: add a flag for cutting moves deeper (axially, stock top above tool tip at that XY) than the flute length
   --flute 25.4 (default off), reported as count + first line. Test it. Do NOT add a >1xD flag.
4. Re-benchmark vs Fusion Overall Roughing (out/fusion_rough.ngc), same heightfield/stock: gouges (must be 0),
   rapid collisions, over-flute moves, leftover mean/p95/max, within_0p5mm, cutting length, est. time, and cutting
   length by 5 mm Z band for both. Write out/bench_engine_rough2.json and print it.
5. If our time is still far above Fusion's, list the top 3 reasons FROM THE DATA (air cutting %, retract count,
   link moves, region order) before changing anything else.
IMPORTANT: run long jobs in the foreground of your shell command (do not background them and exit); the session
must not end while a run is still going. Run both test suites before finishing.
