# Task C (round 3): setup coordinates, real stock, benchmark vs Fusion

Context: samples/core_front.step was in design coordinates; Fusion machines Core Front from design -Z.
Everything so far cut the back of the core. Fix the orientation first.

1. spike/orient.py (freecadcmd): write samples/core_front_setup.step and samples/cavity_front_setup.step.
   - Core Front: rotate 180 deg about X (y->-y, z->-z), then translate Z +34.925.
     Assert bbox X +-126.36, Y +-69.85, Z 0..46.84 (tol 0.05 mm).
   - Cavity Front: rotate 180 deg about Z (x->-x, y->-y), then translate Z +60.96.
     Assert bbox X +-126.36, Y +-69.85, Z 0..60.96 (tol 0.05).
   - Origin = Fusion WCS (bottom-centre of stock); reference/1001.nc lines up with core_front_setup exactly.
2. Real stock (box, not part bbox + margin):
   Core Front X +-128.651, Y +-82.55, Z 0..60.96. Cavity Front X +-127.762, Y +-76.2, Z 0..62.23.
   Make the stock and STEP path parameters of run_cam.py (env or args), defaulting to core_front_setup.
3. Rerun run_cam.py on core_front_setup.step: plain Adaptive from stock top down with explicit depths,
   floors +0.3 mm; then SteepShallow with the 6 mm ball. Also try ModelAwareExperiment ONCE on the
   reoriented shape and record the result in NOTES.md (exact error if it fails) - no healing loops.
   Regenerate the heightfield: verify/heightfield.py on core_front_setup.step -> out/core_front_setup_hf.npy.
   zmap targets: 0 gouges, 0 rapid collisions, roughing leftover ~0.3 mm on reachable areas.
4. Benchmark vs Fusion: run zmap on reference/1001.nc (G20, same WCS, same heightfield and stock). It has
   T3 = 0.5 in bull nose, 0.005 in corner radius (i.e. --tool bull --dia 12.7 --corner 0.127), Overall
   Roughing (adaptive) + INSERT CONTOUR. If it uses more than one tool, simulate each tool's section in order
   with --stock-in/--stock-out. Add to zmap's JSON: cutting length (mm), rapid length, and estimated cycle
   time from F words (feed moves at F; rapids at an assumed 15000 mm/min, say so), plus the fraction of
   reachable area within 0.5 mm of the part. Write out/bench.json with Fusion vs ours side by side:
   leftover mean/p95/max, fraction within 0.5 mm, cutting length, cycle time.
5. Gouges: re-check our finishing at 0.1 mm cells (heightfield.py CELL=0.1). If that is too slow, add a
   --window option to zmap that only simulates/evaluates cells within 2 mm of steep walls (|dZ| > 1 mm
   between neighbours). Report whether the 0.5 mm-grid gouges persist at 0.1 mm.
6. Trim spike/NOTES.md to <= 80 lines (keep the API notes, errors and the part ground truth).
Do not commit; the supervisor commits. Skip cavity toolpaths; only generate and verify its STEP.
Print out/bench.json and the zmap JSONs at the end. Run `/opt/homebrew/bin/python3 -m pytest verify -q` before finishing.
