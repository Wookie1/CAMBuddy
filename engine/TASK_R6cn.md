# Task R6c-n: one source of truth for the helix entry diameter. Do not commit. SMALL: diff under ~150 lines.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do not edit
verify/; keep programmed engagement = optimal load 2.032 (no derate). NO post-pass that edits, converts or replays
moves after Adaptive2d - only change how the entry is specified and generated.
Diagnosis: engine/rough.py tells Adaptive2d helixRampTargetDiameter = 0.8 * D (10.15 mm for 12.686), and Adaptive2d
plans its first loops against that bore. Our _helix_moves cuts radius = distance(helix centre, region start point)
(~3.15 mm on the test block), a smaller bore - so the first loops after each entry cut stock Adaptive2d thinks is gone
(full-width engagement right after entries).
Fix: ONE value (helix entry diameter) feeds both a2d.helixRampTargetDiameter/MinDiameter and our entry generator, so
the bore we cut equals the bore Adaptive2d assumed (same centre, same diameter; finish the helix with one full circle
at depth). If the region's start point is not on that circle, move along a straight feed at depth onto the circle only
through already-cleared bore. Report helix diameter in stats.
Measure with verify/zmap.py --engage-max 2.438 (zmap is the judge; its horizontal/entry report):
- test block: engine.cli rough --step samples/test_block.step --stock -50 50 -40 40 0 38 --tool flat:12.686
  --floor 20 --leave 0.381 --final-zmin 20.381 --stepdown 19.05 --optimal-load-mm 2.032 --hf out/test_block_hf_0.5.npy
  then zmap with --part out/test_block_hf_0.1.npy --tool flat --dia 12.686 --stock -50 50 -40 40 0 38.
- before AND after: horizontal p50/p95/p99/max, entry stats, gouges, rapid collisions (must be 0).
Target: horizontal p99 <= 2.438 with all gates 0. If matching the diameter alone does NOT get there, STOP and report
the numbers in engine/R6cn_RESULTS.md - do not add workarounds. Engine suites (VibeCAD python engine/test_engine.py,
engine/test_finish.py) must stay green. FOREGROUND jobs only. Short outputs.
