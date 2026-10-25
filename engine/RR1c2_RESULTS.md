# RR1c-2 results (written by the supervisor: the model's turn ended before it wrote this file)

Model: M4 local model, 13:39-14:11 local, worktree stevecam-rr1b on 885ee43 + engine/RR1c_DIAG.md (f23b97f).
Its last message (oc_rr1c2.log) listed the changes below with file:line; the supervisor re-ran every test itself.

## (1) Line count (`git diff --numstat 885ee43`)
engine/rest_rough.py +85/-62 (147 changed, non-test; budget 200). engine/test_engine.py +65/-1 (one new test + registration).
The two existing RR1c tests are byte-unchanged (diff vs 885ee43 is additions only plus the runner tuple).

## (2) Per item (model's file:line claims; supervisor's test runs)
1. Thin band - step-2 direction from the region's long axis (rest_rough.py ~547); zigzag_runs centre run + `ys` for
   vertical runs (~155, ~179); centre-line pass when the region has no offset rings (~636).
   test_rr1c_thin_band_inpass_ramp: OK (supervisor run, VibeCAD python, ENGINE_WORKERS=4).
2. Side entry - step4 descent column and every feed-in point vs exact CL (~407, ~412); all emitted entry geometry through
   batched `cl_ok_path` (~321); ONE ladder `enter()` (~460) for zone entry and pass links.
   test_rr1c_narrow_pocket_side_entry: OK (0 gouge points).
3. Rapid collisions - the model located all 7 in out/rr1b/rest_rough_cf.ngc (lines 338/605/1149/1438/1637/1803/1968,
   diagonal zone-to-zone G0s leaving a low Z across standing stock); fix: `g0` never diagonal (~302: rise, traverse at the
   swept-checked height, drop). New test test_rr1c2_cf_rapid_shapes_clear_stock: OK on this code; on a `git archive
   885ee43` engine extract it FAILS BY ASSERTION ("rapid through live stock: 46 pts (worst 1.253)").
RR1b tests and test_rr1a_rough_cli_refuses_ball: OK.

## (3) Not done
Full engine/test_engine.py, engine/test_finish.py and pytest (the model's suite runs died with its session); the Core
Front chain judge (supervisor's, on fe5 code) - both pending.
