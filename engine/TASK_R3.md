# Task R3 (safety-critical): R2 islands still admit cutter centres next to pocket walls. engine/ only. Do not commit.
Repro (supervisor): connector/testdata/synth_pocket.step (bbox X/Y +-30, Z 0..12; pocket floor Z 4), prepared with
stock -31 31 -31 31 -1 12.4, then
  python -m engine.cli rough --step <synth_pocket> --stock -31 31 -31 31 -1 12.4 --tool flat:6.0:0.0 --floor 3.0
  --leave 0.381 --stepdown 4.0 --optimal-load-mm 2.0 --stepup 1.905 --hf <its part_hf.npy> --min-rest 0.5
fails with: "hf backstop at level Z=4.381: CL point (-6.400, 23.508) at Z=4.381 cuts to 7.619 mm below the part
heightfield". OCL CylCutter(6.0) drop-cutter at (-6.4, 23.508) gives CL 12.0 (the point is inside the pocket but closer
than the tool radius to the pocket wall), so the R2 island at Z 4.381 failed to exclude it. The backstop is right; the
island is wrong. Find why (candidates: CL grid extent/padding not covering the pocket wall region, NaN-as-air handling
treating the pocket rim as air, marching-squares sign/orientation inside nested loops (pocket = hole in island = the
part region outside the pocket?), refine/outward rounding inverted for holes) and fix it.
Tests: this exact repro must produce a program with 0 backstop/clcheck violations; add a synthetic pocket-in-block test
(narrow and wide pocket) asserting every cutter centre at a level is >= R + radial leave from the pocket walls.
Keep the test block and all engine tests passing. Do NOT run Core Front. Short outputs.
