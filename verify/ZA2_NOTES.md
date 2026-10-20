# Task ZA2 notes (do not commit)

## Status
- `pytest verify -q`: **90 passed** (green).
- `pytest connector -q`: **85 passed, 9 failed**. Every failure is an
  end-to-end test that runs the REAL engine rough; the current engine
  plunges its flat bottom into stock, so the ZA axial-plunge gate
  (MAX_RAMP_DEG=15, AXIAL_FLOOR=0.2 in verify/zmap.py) fails the run.
  These tests are NOT weakened - they turn green when the RT round lands
  (honest helix/ramp entries in the engine rough). All connector unit
  tests (fake `_spawn`) pass.

## Connector e2e failures - real engine plunges (expected until RT round)
Failure cause for every entry: the engine-posted rough program drives the
flat bottom (T13, D=12.686) straight down into stock; zmap exits 1 and the
runner fails the run with the message below.

1. `TestEndToEnd::test_enroll_confirm_run` (run 501) -
   `engine failed (rc=1): error: 2 axial plunge(s): straight feed descents driving the flat bottom deeper than 0.200 mm into stock under the flat bottom (max 8.019 mm at XY -16.724, -17.240, first line 18)`
2. `TestPostedUnitsE2E::test_rough_posts_mm_when_requested` (run 510) -
   same as (1): `...max 8.019 mm at XY -16.724, -17.240, first line 18`
3. `TestPostedUnitsE2E::test_rough_posts_inch_when_requested` (run 511) -
   `...max 8.018 mm at XY -16.731, -17.231, first line 18`
4. `TestSlopeSplitFinish::test_e2e_chain_rough_then_finish` (run 801) -
   `...max 4.000 mm at XY -16.724, -17.240, first line 2708` (the
   slope-split rough program plunges at line 2708)
5. `TestRestPass::test_e2e_rest_pass` (run 920) -
   `...max 4.000 mm at XY -16.724, -17.240, first line 2708`
6. `TestWarningsInCheckJson::test_rough_check_json_has_warnings` (run 850) -
   `...max 8.019 mm at XY -16.724, -17.240, first line 18`
7. `TestWarningsInCheckJson::test_slope_check_json_has_warnings` (run 851) -
   `...max 4.000 mm at XY -16.724, -17.240, first line 2708`
8. `TestHolderUnknownGate::test_holder_unknown_fails_run_no_nc` (run 860) -
   fails with the axial-plunge message BEFORE the holder gate is reached:
   `assert 'holder unknown' in 'engine failed (rc=1): error: 2 axial plunge(s): ... max 8.019 mm at XY -16.724, -17.240, first line 18)'`
   (the run still fails without an .nc upload; only the message names the
   plunge instead of the holder - fixed by the same RT round)
9. `TestHolderUnknownGate::test_check_json_holder_estimated_for_t13`
   (run 861) - `...max 8.019 mm at XY -16.724, -17.240, first line 18`

## What was fixed (fixtures + tests only; the gate in verify/zmap.py untouched)
- verify/test_zmap.py fixtures that plunged (vertically or via the earlier
  disguised steep diagonals, e.g. `G0 X5 Y0 Z20 / G1 X0 Y0 Z5`) now enter
  honestly: vertical feed descent stops AT the stock top (removes nothing),
  then a ramp at <= 15 deg feeds down to cut depth, then the original
  lateral cuts run unchanged. Affected: stock-chain CLI, warnings,
  optimal-load x3, strict-JSON sample, Z5 half-cell / air-rapid / tess-tol
  / Z5b builder programs, STRICT_OK. Every assertion kept; expected numbers
  unchanged except where noted below.
- New/updated axial gate tests (verify/test_zmap.py): straight flat plunge
  FAILS; 71 deg diagonal (G0 X5 Y0 Z20 / G1 X0 Y0 Z5) FAILS; descent into
  an area cleared by an earlier side-entry pass PASSES (no more stock_init
  cheat); 2 deg helical G2 full circle (I/J, Z drop over one turn) PASSES;
  30 deg helical arc FAILS; 2 deg helix of short G1 segments PASSES; ball
  plunge counted, exit 0.
- `test_axial_real_core_front_rough_fails`: exact count is now **489**
  (was 475): with AXIAL_FLOOR=0.2 the 14 stepdown re-entries of
  1.12-1.62 mm count in addition to the 475 solid-stock plunges;
  max depth/worst XY/first line unchanged (25.654 mm at -2.593, -52.230,
  line 63675).
- connector/testdata/check_ok.nc and check_rough.nc (static check_program
  fixtures, flat T13): entries were vertical plunges into the 0.3-0.4 mm
  stock allowance; they now descend to the stock top (Z12.4, removes
  nothing) and ramp in at ~10-11 deg. This made all four
  TestCheckProgram*/TestCheckProgramSequence* E2E tests pass with their
  assertions intact (skim floors Z12.05/Z12.1 preserved).
