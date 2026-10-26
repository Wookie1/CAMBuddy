# Task FI1: every helix entry's cutting-feed return feed-in is simulated (B2 on all helix entries). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only if needed.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-fi1/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS, SPIKE_MM).
RESULTS: APPEND a section "FI1" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. (Cause given below; no cause section needed.)
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/rough.py only (the red test is already committed in engine/test_engine.py).
BUDGET: <= 25 changed non-test engine lines vs main 02bb395; STOP and report at ~35. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-fi1, branch fi1 at the commit carrying this brief
(= main 02bb395 merged + red test + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
Run a test like this (no pytest in VibeCAD python): slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_engine as t; t.<test_name>()"
AT-RISK (all 29): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0,
test_bs1a4d7_sub1mm_tail_merges_not_dropped, test_bs1a4d8_arrival_gate_reads_judge_skin,
test_bs1a4d8b_no_unsimulated_link_into_path, test_bs1a4d8c_inrun_jump_simulated,
test_bs1a4d8c_replan_far_piece_enters_own_start, test_bs1a4d8e_inrun_guard_skips_planned_paths,
test_bs1a4d9_no_entry_at_stale_q4, test_rr1c_narrow_pocket_side_entry, and the RED test
test_fi1_entry_feedin_within_limit (must turn green).

## Facts (supervisor, measured on main 02bb395 + the red test)
- Red test test_fi1_entry_feedin_within_limit (synthetic ledge pocket, Adaptive2d only): "fi1 T-feedin: 158 entry
  feed-ins, 1 judged over 2.44, worst line 2722 ae_eff 10.947 a 17.62" - a helix entry's return feed-in at CUTTING
  feed (the single F3429 move right after the F1270 helix, same Z) slots standing stock.
- Cause: helix_entry -> try_cand (rough.py ~:1340-1348) already has the B2 simulation of that return feed-in
  (_simulate of seg with only the swept bore pre-cleared, entry="bore", eps 0; over SPIKE_MM the candidate is
  refused and the ladder moves on), but it runs ONLY when _gate[0] is set, and only enter_point (~:1802-1805) sets it.
  Every other helix entry (enter_at from the region loop, guard conversions, feed_down) emits its feed-in unsimulated.
- BS1a4d9 already removed the stale-q4 entry (the old "line 206" feed-in on the d8c re-plan scene); the d8c scene's
  piece overload at lines 418-423 is a scene artifact (spy-pinned fake prediction), not in scope.
## Item (coordinator spec)
1. B2 on EVERY helix entry: the return feed-in simulation in try_cand runs for every candidate, not only gated ones;
   a refused candidate lets the ladder move on exactly as today (next candidate / radius / fallback - no new entry
   kind). If _gate is then unused, remove it. Count every refusal in a new stats counter (e.g. stats["b2_rej"]) -
   no silent early exit. When EVERY ladder option is refused, no region is dropped and nothing new is invented: the
   existing exhausted-ladder path runs as today and is counted (stats["b2_exhausted"]). The red test turns green;
   every at-risk test stays green.
2. Same gates: no gouge/axial/rapid/clcheck counts may appear on any at-risk scene (n_axial_plunge must not rise
   because a refused helix fell back to a plunge - report the counter before/after on the ledge scene and the L
   channel).
3. Not output-neutral by design: report the L-channel and test-block programs before/after (cmp; when they differ,
   the line counts removed/added and where), plus b2_rej on each.
## engine/BS1a4d6_RESULTS.md "FI1": the change with file:line, line count vs 02bb395, the counters (b2_rej, b2_exhausted, n_axial_plunge) and cmp results,
PASTED exit codes of all 29 at-risk tests, git diff --numstat. Then stop. (Supervisor runs the CF judge: gates 0 with
holder, FW <= 1.1 mm, overload <= 445 / 496.6 mm, cycle within 3 % of 5,424.8 s, b2_rej and b2_exhausted reported.)
