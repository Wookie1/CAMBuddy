# Task BS1a4d6d: simulate the side/link APPROACH segment so window 0 holds the approach's own engagement. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances, EXCEPT item 2 in test_bs1a4d6c_side_entry_no_under_read. Add NEW tests otherwise.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d6d" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. CAUSE FIRST: write the cause there before any code change.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py, engine/rough.py and engine/test_engine.py only.
BUDGET: <= 20 changed non-test engine lines vs 5b6e6b0; STOP and report at ~30. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= 5b6e6b0: BS1a4d6c + its test-units fix 73e8d92 + record notes, + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 19): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read.

## Facts (supervisor, 73e8d92)
- BS1a4d6c (accepted): _simulate(entry=) pre-clears only a bore footprint; "side"/"link" pre-clear nothing.
- test_bs1a4d6c_side_entry_no_under_read now compares WIDTHS (window area / that window's travel, from ends=), mm:
  clean predictor width 23.958 mm >= judged ae_eff 11.458 mm (PASS); unconditional pre-clear restored: 9.375 mm
  < 11.458 mm (FAIL, under-read 2.083 mm).
- 23.958 mm exceeds D = 12.686: impossible as an engagement width. For entry="side"/"link", _simulate starts at
  path[0] = P0 and never simulates the approach move INTO P0, so the whole standing start disk lands in window 0.
## Item (coordinator rule, second half)
1. For entry="side"/"link", simulate the approach segment (the emitted entry's start point -> P0) through the live
   stock, so window 0 holds the approach's own engagement instead of the whole standing disk. Pass the approach start
   point in from each caller that uses "side"/"link" (band.py shrink_ladder, rough.py lnk_cut_ok, rough.py emit
   re-check); where a caller cannot know the emitted approach start, say so in the results with file:line and keep
   today's behaviour there (do not guess).
2. The side-entry test: its predictor width must then be <= D (12.686) and still >= the judged 11.458 mm. Assert
   both, print both. (Change ONLY that test's assertions for this, plus any NEW test you need.)
3. Mutation (scratch copy, revert): skip the approach (today's behaviour); the test must fail by the MEASURED width
   (> D). Record the number.
## engine/BS1a4d6_RESULTS.md "BS1a4d6d": cause, change with file:line, line count vs 5b6e6b0, PASTED exit codes of all
19 at-risk tests, the mutation output, git diff --numstat. Then stop.
