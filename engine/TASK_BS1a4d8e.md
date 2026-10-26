# Task BS1a4d8e: the in-run guard checks only recorded piece boundaries; small output-neutral cleanups. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d8e" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. (Cause given below; no cause section needed.)
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/rough.py only (tests: none to add or edit - the red test is already committed).
BUDGET: <= 25 changed non-test engine lines vs a830ce2; STOP and report at ~35. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= 5431aba + red test a830ce2 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 26): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0, test_bs1a4d7_sub1mm_tail_merges_not_dropped, test_bs1a4d8_arrival_gate_reads_judge_skin, test_bs1a4d8b_no_unsimulated_link_into_path, test_bs1a4d8c_inrun_jump_simulated, test_bs1a4d8c_replan_far_piece_enters_own_start, and the RED test test_bs1a4d8e_inrun_guard_skips_planned_paths (must turn green).

## Facts (supervisor, CF judge on 5431aba + synthetic probes)
- 5431aba fixed the far-piece entries (both targets now entered by 3.7 mm feed-ins judged 0.003 / 0.0; single F3429
  moves >= 2 mm over 2.44: 0; gates 0 with holder; FW 1.1 mm) but FAILS the bar on overload (overload_feeds_ae2 777 /
  840.5 mm vs 36319bf 458 / 554.4) and cycle (20,283.5 s vs 5,502.9 s, x3.7; 656,194 program lines vs 356,401).
- Cause: all 817 conversions are cvt_join = irun_cvt (irun_chk 16,079). d8d scoped the in-run guard with
  `if ki and not res.get("band") and irun_guard(...)` (rough.py run loop, ~:2466) - that exempts plan-simulated BAND
  paths but guards EVERY pair of every Adaptive2d run, i.e. adaptive's own planned segments. Earlier split on CF:
  393 of 394 converted pairs judged <= 2.11 mm at 36319bf; 371 of them are 1-2 mm planned steps.
- Red test test_bs1a4d8e_inrun_guard_skips_planned_paths (committed, a830ce2): a synthetic ledge pocket (Adaptive2d
  only, no band pieces, so NO emit-time joins). On 5431aba: "planned-path pairs converted on a join-free scene:
  irun_cvt 4, n_backstop_links 4"; with the in-run guard off the judged overloads are IDENTICAL (10 windows / 12.0 mm,
  max 10.947) - the 4 conversions only add 569 moves.
- Supervisor mutation M5 (exemption removed for bands too) is caught by test_bs1a4b_windows_align_zmap ("engine 791 vs
  zmap 331") - keep band paths exempt.
## Items (coordinator spec)
1. When a run is built from pieces, RECORD the indices where a new piece starts (q4 -> piece, piece -> piece, the
   re-plan rejoin, bridge -> path); the in-run guard checks ONLY the pair that crosses each recorded boundary, never a
   pair inside one planned path - Adaptive2d or band. The red test must turn green (irun_cvt 0, n_backstop_links 0 on
   the ledge scene) and test_bs1a4d8c_inrun_jump_simulated must stay green (its jump IS a boundary).
2. Cleanup (b): irun_guard drops its copied skip tests (nopos / Z equality / <= 0.6) and lets trans_guard do them, so
   EVERY skip is counted in bstd_skip_*. The Z rule stays EXACTLY as it is (abs(prev_z - z) > 1e-6), but count that
   exit as bstd_skip_zdiff (rename toolup -> zdiff). Output-neutral.
3. Cleanup (c): the B2 feed-in _simulate inside try_cand runs only when _gate[0] is set (move it inside the check).
   Output-neutral.
4. Name the 0.5 tier in enter_point (`bxy[2] > 0.5 * tool_r`) as a module constant with a ONE-line comment: empirical
   from the d8c re-plan scene; 0.4 and 0.6 are untested (supervisor: both pass every current test). No new test.
5. Items 2-4 must be output-neutral: the L-channel and test-block rough programs byte-identical before and after
   (cmp) - item 1 is the only behaviour change.
## engine/BS1a4d6_RESULTS.md "BS1a4d8e": the change with file:line, line count vs a830ce2, the cmp results for items
2-4, PASTED exit codes of all 26 at-risk tests, git diff --numstat. Then stop.
