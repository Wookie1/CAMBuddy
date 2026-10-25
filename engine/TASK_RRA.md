# Task RR-A: the rest-rough bay test under RR1c-5d (A). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5); a fix that only passes by moving a limit is rejected.
CONTINUE: continue from your plan; don't stop before the test has run.
Edit engine/rest_rough.py (and engine/entry_depth.py only if the cause is there) and engine/test_engine.py only. Write
results to the NEW file engine/RRA_RESULTS.md.
BUDGET: <= 30 changed non-test engine lines vs the base commit, STOP at ~45. FRESH session, HARD CAP 2 h (run `date`
at start and write it in the results file). Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit
carrying this brief (= main 04eea8d merged into rr1b 1149984, + this brief).
AT-RISK existing tests (run these plus any new test; NOT the full suite): test_rr1b_rest_rough_synth_pocket,
test_rr1b_rest_rough_reports_small_pocket, test_rr1c_thin_band_inpass_ramp, test_rr1c_narrow_pocket_side_entry,
test_rr1c2_cf_rapid_shapes_clear_stock, test_rr1c3_curved_thin_band_centre_line, test_rr1c3_bay_deep_groove_top_down,
test_rr1c4b_plateau_topdown_axial_load, test_rr1c4b_closed_pocket_bore_levels,
test_rr1c5c_closed_pocket_bore_entry_no_deep_axial, test_rr1c4c_floor_circle_over_rising_surface,
test_rr1c5b_varying_width_band_fronts, test_rr1c5b_open_edge_proud_block, test_rr1c5b_fully_walled_band_bore_seed,
test_rr1c5b_mixed_band_core_front, test_rr1c5d_live_grid_fine_for_coarse_stock. (test_rr1c5d_front1_chord_offset_slabs
also fails today - leave it OUT of this task; just report its status at the end.)

## Facts (supervisor)
- 07f0c7e (RR1c-5d before (A)): test_rr1c3_bay_deep_groove_top_down PASSES.
- 9260c78 (A): the rest-rough live grid's fine cell is min(input stock cell, 0.1) (`fine=min(stock[3], fin.FINE)`; pin test
  test_rr1c5d_live_grid_fine_for_coarse_stock). With (A) the bay test FAILS: "only the entered level cut: ... 'levels': 1,
  'floor_tip_z': 28.2, 'entry_steps': [2, 2, ..., 4, 4, ...]" - the deeper groove level is refused; the refused passes
  read 1.80 / 2.58 mm on the finer grid.
- (A) itself stays: a 0.5 mm live grid under-read descents by up to 0.64 mm.
## Change
1. FIRST, before any code change: in a scratch copy (not the worktree; e.g. `git archive` of 07f0c7e and of HEAD into
   your own temp dir), log the deeper-level decision for the bay scene on both, and write in engine/RRA_RESULTS.md the
   FIRST decision that differs between 07f0c7e and HEAD for those refused passes - which check, its inputs and both
   values. Name it.
2. Then fix the cause in the rest-rough code so the groove level is cut and every limit above still holds. Do not
   change (A). If the fix is a tolerance or threshold, show the measured values that justify it - and it must not be
   one of the LIMITS.
## Test
test_rr1c3_bay_deep_groove_top_down must pass UNCHANGED; test_rr1c5d_live_grid_fine_for_coarse_stock must still pass.
If your fix needs its own guard, add a NEW test that fails by a measured value on the pre-fix code.
## engine/RRA_RESULTS.md: the first differing decision with both values, the change with file:line, line count, PASTED
exit codes of the at-risk tests, and the status of test_rr1c5d_front1_chord_offset_slabs. Then stop.
