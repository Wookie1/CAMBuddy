# Task R4: pocket-corner reach on the test block (quality, not safety). engine/ only. Do not commit.
After R2/R3 on samples/test_block.step (T13 flat 12.686, James's cutting data): in the 4 R6 corner zones of the Z27
pocket (30x22 at (12,-2)), 78 of 113 mm2 of floor stays > 0.5 mm high, up to the full 8.381 mm. A tool of radius
6.343 (+0.381 radial leave) in an R6 corner must only leave the crescent between the R6 corner arc and the tool arc;
everything else in the pocket must end at the allowance. Find why the pocket clearing stops short (candidates: Adaptive2d
region/territory dropping small pocket areas, clearance-ring heuristics, min_level_area / min_rest gates on the pocket
level, helix entry unable to fit -> region skipped), fix it without weakening any safety gate (rough clcheck, backstop,
island clearance must stay). Test: pocket floor cells outside the analytic crescent end within 0.381 +- 0.05 mm;
crescent area ~ the analytic value. Run the test block end to end and report leftover in the corner zones.
