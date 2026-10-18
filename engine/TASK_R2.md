# Task R2 (safety-critical): roughing islands must not come from OCL waterline. engine/ only. Do not commit.
Evidence (supervisor): on samples/test_block.step (flat 12.686 mm, James's cutting data) our rough gouged 176 zmap
cells up to 3.70 mm; OCL CylCutter(12.686) drop-cutter shows the level-29.906 path at (-17.56, 13.87) (G-code line
20741) 3.72 mm below the true CL, beside the boss R8 vertical corner where the R3 top fillet starts. Islands come
from OCL Waterline and the hard allowance check validates against those same islands, so it cannot catch it.
(Finishing already moved off OCL waterline for the same reason: see finish.py cl_grid / march_level / refine.)
1. Build every level's island from a batched drop-cutter CL grid with the ACTUAL cutter (CylCutter for flat,
   BullCutter for bull; diameter + 2x radial allowance, CL compared against Z - axial allowance): island at level Z =
   {CL > Z - axial_leave}, marching squares, boundary refined by bisection to < 0.005 mm, never under-covering
   (round outward). Reuse finish.py's grid/march/refine helpers where possible. No ocl.Waterline/AdaptiveWaterline
   anywhere in rough.py.
2. Independent ROUGH CLCHECK gate (separate code path from the islands, e.g. engine/probe_rough_clcheck.py and a
   function called at the end of rough()): exact OCL one-sided drop-cutter with the actual cutter on every rough
   cutting move sampled <= 0.1 mm; a point more than 0.005 mm below (CL + axial allowance... i.e. tip must stay >=
   CL_part + axial_leave - 0.005) FAILS the run (non-zero exit, clear message with line and XY).
3. Mandatory flat-floor levels: every up-facing flat floor (pockets, plateaus; from flat-face Zs of the STL) gets a
   level at floor + axial_leave that the rest/skip logic can never drop.
4. Tests (engine/test_engine.py): test block -> 0 gouges (engine's own drop-cutter check) and rough clcheck 0, Z27
   pocket level present and its floor ends 0.381 +- 0.02 mm high (measure with the engine's own stock model);
   regression for a fillet meeting a vertical corner (boss with R8 corners + R3 top fillet), checking (-17.56, 13.87).
5. Do NOT run Core Front; run the test block end to end (rough CLI with --hf out/test_block_hf_0.5.npy, stock
   -50 50 -40 40 0 38, tool flat:12.686:0, floor 20, leave 0.381, final-zmin 20.381, stepdown 19.05,
   optimal-load-mm 2.032) and report compute time, levels, rough clcheck.
