# Task BS1a4d7: engine _simulate windowing mirrors ZG2 - sub-1 mm tails merge, never dropped. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d7" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. (No cause section needed - feature.)
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py and engine/test_engine.py only.
BUDGET: <= 15 changed non-test engine lines vs 36319bf; STOP and report at ~22. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= BS1a4d6d 36319bf + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 20): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0.

## Facts (supervisor)
- ZG2 (branch zg2, 462d985, accepted; NOT merged into this branch): verify/zmap.py _ae2_windows now MERGES a trailing
  run under 1 mm into the preceding kept window of its chain (windows[n-1]), else the next kept window; area, length,
  a and hist are summed; a cut with no kept window at all is reported (engagement ae2_isolated_sub1mm) and never
  gated. Read it at /Users/James/ai-sandbox/stevecam-zg2/verify/zmap.py (read-only; never edit that worktree).
- engine/band.py _simulate (:154) still DROPS sub-1 mm runs: the trailing acc_area/acc_len at the end of the path is
  never appended, and a >45 deg chord break (DIR_COS) resets acc_area/acc_len, discarding that fragment.
- ZG2's synthetic pushed-over case (verify/test_zmap.py test_zg2_merged_tail_pushes_window_over_spike on zg2):
  merged ae_eff 5.857 mm (area 12.300 / length 2.100) > 2.25; dropped-tail value 0.800 mm.
## Change (coordinator spec)
1. _simulate windowing follows ZG2's rule exactly: a sub-1 mm run (at the path end or at a chord break) merges into
   the chain's last kept window, else into the next window; area and length are summed (the window value unit does
   NOT change - it stays the summed area per window; AE-UNITS is separate and not scheduled). A run with no kept
   window at all (the whole path < 1 mm) stays out of the returned windows (as zmap keeps it out of the gates).
   `ends` must stay consistent with the windows returned.
2. NEW test: the same synthetic geometry as ZG2's pushed-over test, through _simulate. The engine must read it over
   2.25 just as zmap does (compare as width = area / that window's length, mm, like the side-entry test); print both
   the engine and the ZG2 zmap values. Mutation (scratch copy, revert): drop the tail again; the test must fail by
   the measured value. Record it.
3. Re-run test_bs1a4b_windows_align_zmap against a zmap WITH ZG2: build a scratch copy of this worktree whose
   verify/zmap.py is the zg2 worktree's file (copy, read-only source), and run the test there. Window boundaries must
   stay identical. Report its max differences both ways (engine-zmap, zmap-engine) BEFORE (this branch's own zmap,
   today: +14.070 / 1.488 mm) and AFTER (engine change + ZG2 zmap).
## engine/BS1a4d6_RESULTS.md "BS1a4d7": the change with file:line, line count vs 36319bf, the item 2 numbers + mutation
output, the item 3 before/after table, PASTED exit codes of all 20 at-risk tests + the new test, git diff --numstat.
Then stop.
