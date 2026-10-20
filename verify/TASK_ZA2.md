# Task ZA2: make the test fixtures honest under the axial-plunge gate; add the gate's must-pass/must-fail tests.
Do not commit. HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete
tests or assertions; do NOT edit the gate in verify/zmap.py (the supervisor set it: MAX_RAMP_DEG = 15, AXIAL_FLOOR =
0.2, angle from arc length for G17 helical G2/G3) - only fixtures and tests. verify/ must NOT import engine/.
The gate: a descending feed move steeper than 15 deg that removes > 0.2 mm of stock under the flat bottom disk is an
axial plunge; flat/bull fail (non-zero exit), ball is report-only.
1. Fixtures: several existing tests plunge straight (or via steep diagonals) into the solid block only to set up a cut
   for some OTHER check (gouges, engagement, Z5 grid, strict CLI ...). Make each such fixture enter honestly: descend
   at a point OUTSIDE the stock/part (or in an already-cleared area) and feed in sideways at depth. Keep each test's
   purpose and every assertion; if an assertion's expected number changes because the entry changed, explain why in a
   one-line comment and keep it at least as strict. Revert the earlier disguised steep-diagonal entries (e.g. G0 X5 Y0
   Z20 / G1 X0 Y0 Z5) to side entries.
2. Gate tests (verify/test_zmap.py), flat tool unless stated:
   - straight vertical plunge into the solid block -> FAILS;
   - 71 deg straight diagonal into the block (G0 X5 Y0 Z20 then G1 X0 Y0 Z5) -> FAILS;
   - descent into an already-cleared pocket (cleared by an earlier side-entry pass) -> PASSES;
   - 2 deg helical G2 full circle (I/J form, Z drop over one turn) into the block -> PASSES;
   - 30 deg helical arc into the block -> FAILS;
   - 2 deg helix made of short G1 segments into the block -> PASSES;
   - ball straight plunge into the block -> counted (axial_plunges.count > 0) but exit 0;
   - real file: out/core_front_roughRT_before.ngc (part out/cf_hf01_z5b.npy, stock -128.651 128.651 -82.55 82.55 0
     60.96, flat 12.686) FAILS; assert the exact count you measure (expect >= 475; the 1.1-1.6 mm re-entries now count).
3. connector tests that run the REAL engine rough will fail the new gate until the RT round lands (the current engine
   plunges): do NOT weaken them; list them in verify/ZA2_NOTES.md with their failure message. Unit tests (fake _spawn)
   must pass.
Run /opt/homebrew/bin/python3 -m pytest verify -q until green; then pytest connector -q and record which e2e tests fail
only because of real engine plunges. FOREGROUND only. Short outputs.
