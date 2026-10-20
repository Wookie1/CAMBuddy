# Task ZA: axial plunging into stock is a failing gate in zmap (flat/bull), reported for balls. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; verify/ must
NOT import engine/. This ADDS a gate; no existing gate or threshold changes.
Background: RT step 0 found the current Core Front T13 rough (flat 12.686) plunges its flat bottom straight into solid
stock 386 times (worst 25.65 mm in one move); zmap only had a report-only "plunge" warning, so the run passed.
1. Definition (verify/zmap.py): an AXIAL PLUNGE = a straight downward feed move (G1, |dXY| <= 1e-6, dz < 0) that removes
   stock under the tool's flat bottom (cells within the bottom disk: radius R for flat, R - corner for bull) by more
   than AXIAL_FLOOR mm (deepest removed column). Measure the distribution of removed depth over all straight descents
   on out/core_front_roughRT_before.ngc (judge part out/cf_hf01_z5b.npy, stock -128.651 128.651 -82.55 82.55 0 60.96,
   flat 12.686) and pick AXIAL_FLOOR as a small noise floor below the real plunges (expect a clear gap; document the
   histogram and the choice in a comment). It is a constant: never raise it later.
2. Report "axial_plunges": {count, max_depth_mm, first_line, worst_xy} for every tool. For tool flat/bull it is a
   FAILING gate (non-zero exit, like rapid collisions); for ball it is report-only (count + depths).
3. connector: _check_zmap_gates fails a run on axial_plunges.count > 0 for flat/bull (rough programs) - this covers
   adaptive_rough, slope_split_finish's rough and check_program (any flat/bull program). Ball programs: report only.
4. Tests (verify/test_zmap.py, connector/test_connector.py): synthetic straight flat plunge into a solid block FAILS;
   a straight descent into an already-cleared pocket PASSES; a helix entry into the solid block PASSES; ball plunge is
   counted but does not fail; check_program with a plunging flat program fails naming axial plunges. And the real one:
   zmap on out/core_front_roughRT_before.ngc FAILS with ~386 axial plunges (state the exact count).
Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q in the FOREGROUND until green. Short outputs.
