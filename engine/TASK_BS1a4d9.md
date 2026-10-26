# Task BS1a4d9: a far re-planned piece emits nothing at the stale q4. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only if needed.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d9/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d9" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. (Cause given below; no cause section needed.)
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/rough.py only (the red test is already committed in engine/test_engine.py).
BUDGET: <= 25 changed non-test engine lines vs main 498ebae; STOP and report at ~35. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d9, branch bs1a4d9 at the commit carrying this brief
(= 498ebae + red test + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
Run a test like this (no pytest in VibeCAD python): slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_engine as t; t.<test_name>()"
AT-RISK (all 27): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0,
test_bs1a4d7_sub1mm_tail_merges_not_dropped, test_bs1a4d8_arrival_gate_reads_judge_skin,
test_bs1a4d8b_no_unsimulated_link_into_path, test_bs1a4d8c_inrun_jump_simulated,
test_bs1a4d8c_replan_far_piece_enters_own_start, test_bs1a4d8e_inrun_guard_skips_planned_paths, and the RED test
test_bs1a4d9_no_entry_at_stale_q4 (must turn green).

## Facts (supervisor, measured on 498ebae)
- Red test test_bs1a4d9_no_entry_at_stale_q4 (d8c re-plan scene): "12 move(s) still emitted at the stale q4 (lines
  147, 148, 149, 166, 167, 168 ...); judged windows there: 4, max ae_eff 6.303 mm" - a helix next to q4 = (-13, 0),
  a 1.5 mm cutting-feed feed-in ending AT q4, then a lift-off; then a rapid to the far piece, which enters again.
- Cause: in the region loop (rough.py ~:2256) enter_at(entry...) emits the entry at the stored start BEFORE the
  replan0 decision. The far branch (~:2298-2328: shrink_ladder with approach=q4, lnk_cut_ok(..., "rjoin") fails,
  re-predict without approach, enter_point(pcs[0][0], ...)) only ADDS the piece's own entry after it. The q4 entry
  is left behind in moves (and in the live stock, if enter_at cut it there).
- On Core Front (498ebae baseline) rjoin_chk 5 / rjoin_cvt 2: both far re-plans carry this stale q4 entry (stale
  feed-in ends at CF lines 64232 and 245855, then a ~25 mm rapid to the piece).
## Item (coordinator spec)
1. When a region's piece is far (the rjoin decision), NO entry is emitted at the stale q4: no helix, no feed-in, no
   lift-off. The piece is entered ONCE, at its own start, by the existing enter_point decision. Whatever enter_at
   did to the live stock and to the stats/counters for the abandoned q4 entry must not remain either (decide before
   entering, or make the abandoned entry leave no trace - your choice; say which in the results). Non-far regions
   and every non-replan0 region must be unchanged: the red test turns green (0 moves), every at-risk test stays green.
2. Output-neutral elsewhere: the L-channel and test-block rough programs byte-identical before and after (cmp) - this
   scene's far re-plan is the only behaviour change.
## engine/BS1a4d6_RESULTS.md "BS1a4d9": the change with file:line and which approach, line count vs 498ebae, the cmp
results, PASTED exit codes of all 27 at-risk tests, git diff --numstat. Then stop.
