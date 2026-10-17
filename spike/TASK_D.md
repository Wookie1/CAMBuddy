# Task D (round 4): is SteepShallow's gouge the engine or our setup? Then Fusion-style roughing.
Part: samples/core_front_setup.step (bbox X+-126.365 Y+-69.85 Z0..46.844; main floor Z 24.8). Stock X+-128.651
Y+-82.55 Z0..60.96. Heightfield out/core_front_setup_hf.npy (+ _hf01 at 0.1 mm). Use OpenCAMLib as
`import opencamlib` / `from opencamlib import ocl` (VibeCAD python, run under freecadcmd).
No MCP tools, no questions. Probe scripts go in spike/probe_*.py (gitignored). Do not commit.

## Item 1 FIRST - diagnose, do not tune. Write findings to out/diag_steepshallow.md.
The round-3 SteepShallow finish (out/core_front_finish.ngc, 6 mm ball) gouged 2411 cells up to 10.7 mm on the
outer rim wall near (-114.6, 56.9): ball tip at Z~8.1 where the part is 38-42.
a. Pick 20 XY points in that gouge area. For each: (1) correct 6 mm ball CL tip Z from OCL drop-cutter
   (ocl.BallCutter(6, length) on an STL of core_front_setup tessellated at 0.01 mm; ocl.CLPoint + BatchDropCutter or
   PointDropCutter), (2) the lowest Z the FreeCAD path commands within 0.25 mm XY of that point, (3) heightfield Z.
   Table them. Note: OCL BallCutter diameter arg is the full diameter; CL z is the tool TIP.
b. Check our inputs and report each: tool controller ball diameter + shape vs zmap's (--tool ball --dia 6);
   any negative stock-to-leave; BoundaryOverlap, BoundaryAdjustment, boundary shape; StartDepth at stock top
   (61.96) making it cut stock it treats as air; SlopeThreshold; whether the gouging moves belong to the steep
   or shallow pass (look at the G-code comments/sections).
c. Conclude: engine bug, or setup error (which property). If it is the engine, STOP item 1 there - do not tune.
   If setup, fix it and re-check with zmap at 0.1 mm.

## Item 2 - roughing like Fusion
Read reference/1001.nc OVERALL ROUGHING section (before "(INSERT CONTOUR)", G20 inches): T3 0.5 in bull nose
(corner 0.005 in), S7500. Measure its stepdown (distinct Z levels), cutting feed (F on cutting moves) and
stepover/engagement (spacing between adjacent passes) and record them. Then ONE Adaptive over the whole model,
bounded by the stock outline, from stock top 60.96 down to FinalDepth 25.1 (floor 24.8 + 0.3), including the
pockets, with that tool (12.7 bull, corner 0.127) and Fusion's measured stepdown/feed/engagement.
Try ModelAwareExperiment down to the floor once; if it errors or is empty, record the exact error and use plain.
Then SteepShallow only from the part top (StartDepth 46.84) down, after roughing (only if item 1 cleared it).

## Item 3 - like-for-like roughing benchmark
zmap ours vs Fusion OVERALL ROUGHING alone (split 1001.nc at "(INSERT CONTOUR)"), same tool, same heightfield and
stock: gouges, rapid collisions, leftover mean/p95/max, within_0p5mm_fraction, cutting length, cycle time.
Write out/bench_rough.json side by side and print it, plus a 5-line summary of out/diag_steepshallow.md.
Run `/opt/homebrew/bin/python3 -m pytest verify -q` before finishing.
