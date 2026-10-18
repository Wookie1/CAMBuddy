# Task R1: roughing must be safe with any combination of optional flags (engine/ only). Do not commit.
Bug (supervisor): `engine.cli rough` WITHOUT --hf (and without --final-zmin) produced a program that gouges the part
(~1.02 M zmap cells, up to 15.5 mm at (-108.7, 44.6)) on core_front_setup; with --hf + --final-zmin it is clean.
1. When --hf is missing, rough builds the part heightfield itself from the STEP/STL it already loads (same grid
   convention and cell as the engine's stock model; tessellation 0.01 mm), so the rest/step-up logic always has
   the part. --final-zmin defaults to floor + axial allowance (leave). Find WHY the missing hf let cuts below the part
   (the hard allowance post-check should have caught it) and close that hole too: e.g. the allowance/clip check must
   never be skipped or weakened when part_hf is None.
2. Tests (engine/test_engine.py, synthetic part): rough without --hf -> 0 gouges (use the engine's own drop-cutter /
   island check, not verify/zmap import) and output identical to passing --hf explicitly; a test that would have
   caught the original bug.
3. Run engine tests. Do NOT run the full part. Short outputs.
