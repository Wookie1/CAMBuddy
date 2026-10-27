# Task ZB: the axial-plunge gate also fails ball tools, at a fixed 0.5 mm ball floor. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; verify/ must
NOT import engine/. This ADDS a gate; the flat/bull gate (MAX_RAMP_DEG = 15, AXIAL_FLOOR = 0.2) is unchanged.
1. verify/zmap.py: BALL_AXIAL_FLOOR = 0.5 mm (James's 0.381 leave + noise) - a fixed constant, NOT tied to any per-program
   leave parameter, documented, never raised. A ball axial plunge = the same rule (descending feed steeper than 15 deg,
   angle from arc length for helical arcs) that removes stock deeper than BALL_AXIAL_FLOOR under the ball (deepest
   removed column within the ball's contact disk at the end point - define it in a comment). Ball plunges now FAIL
   (non-zero exit) exactly like flat/bull ones. Report floor_mm per tool type.
2. connector: _check_zmap_gates fails finish and rest programs on ball axial plunges too; check_program the same.
3. Tests (verify/test_zmap.py): must-fail - a 1.0 mm straight ball plunge into a block; the real interim finish
   (out/interim_finish.DO_NOT_RUN.nc, chained: out/interim_rough.DO_NOT_RUN.nc from full stock -128.651 128.651 -82.55
   82.55 0 60.96 with flat 12.686, then the finish as ball 9.525, on part out/interim_part_hf01.npy; see out/ball_axial.py)
   fails with about 199 entries deeper than 2 mm (assert the exact count you measure). Must-pass - a ball descending onto
   0.381 mm of leave, and a ramped (<= 15 deg) ball entry into the block. Ball fixtures in existing tests that plunge
   only to set up another check: enter honestly (as ZA2 did), keep every assertion.
4. Connector e2e tests that run the REAL finish/rest may now fail (the engine's finish entries plunge until task FE):
   list them with their messages in verify/ZB_NOTES.md; do not weaken anything.
Run /opt/homebrew/bin/python3 -m pytest verify -q until green, then pytest connector -q and record. FOREGROUND only.
