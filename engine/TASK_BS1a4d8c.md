# Task BS1a4d8c: no jump inside an emitted run - re-plan joins fixed at the root, every in-run cutting pair guarded. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d8c" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. CAUSE: given below (supervisor-measured); confirm it in the results by reading the named code, no new full CF run.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/rough.py and engine/test_engine.py only (engine/band.py ONLY if (2) cannot be done without it - then write why in the results FIRST).
BUDGET: <= 50 changed non-test engine lines vs 337c44b; STOP and report at ~65. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= BS1a4d8b 337c44b + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 23): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0, test_bs1a4d7_sub1mm_tail_merges_not_dropped, test_bs1a4d8_arrival_gate_reads_judge_skin, test_bs1a4d8b_no_unsimulated_link_into_path, plus your new tests.

## Facts (supervisor, full Core Front, instrumented scratch copy of 337c44b; every trans_guard call logged)
- BS1a4d8b changed nothing on CF: the program is byte-identical to 63db90f's; n_backstop_links / bstd_chk / bstd_cvt
  all absent. 10,276 trans_guard calls, ALL reached the d0 test, zero "tool up" early exits.
- CF line 64233 (25.2 mm G1 F3429 (26.7568, 13.4273) -> (1.6689, 10.7822), Z 42.354, judged ae_eff 9.319, a 18.61) is a
  jump INSIDE ONE RUN: after the emit re-check/re-plan, that region's run is [q4 = (26.7568, 13.4273), (1.6689,
  10.7822), ...] - the stale stored start q4 kept as run[0] and the lightest-option piece that starts 25 mm away
  appended right after it. try_cand's helix + 1.5 mm feed-in lands on q4 = run[0], so trans_guard(run[0]) reads
  d0 = 0.000 and passes; the run loop (rough.py:2402-2404, after the d8b guard at :2398) then emits run[1] straight
  at cutting feed. The plan-time channel_regions path for (26.7568, 13.4273) is a normal dense 119-point path - the
  join is made at emit (BS1a4d6b's "pcs[0] joins q4, kept by the walker" shape).
- Z 40.289 (24.8 mm (26.1469, 7.59) -> (1.5693, 10.8034), judged 12.118 full width): the same shape.
- d8b's (a) did not fire: the entry WAS at run[0] (= q4); it is run[1] that is far.
- Plan-time in-run jumps > 2 mm are common in emitted region paths too (e.g. 3.0-6.2 mm steps near the end of region
  (1.6689, 10.7822), 5.7 / 5.63 mm in (20.568, 7.0041), up to 5.9 mm in (-2.8057, 9.4074)) - emitted point-to-point at
  cutting feed; not judged per segment yet.
## Items (coordinator spec)
(2) ROOT FIX: a re-planned region's run never starts with the stale q4 when the piece does not start there; the entry
    goes to the piece's own first point (the enter_at ladder), and the predictor/re-check mirror that entry.
    Test (synthetic, in code): a re-plan scene where the lightest option starts 20+ mm from q4. With (2) correct:
    bstd_cvt for that scene is 0 and the first cutting move is within one step of the entry (measured). Mutation (2)
    reverted, (1) on: bstd_cvt == 1. Mutation both reverted: the test fails by the MEASURED zmap ae_eff.
(1) BACKSTOP: every consecutive cutting-feed pair in an emitted run longer than 0.6 mm is simulated on the live stock
    at eps 0 (the same lnk_cut_ok rule as d8b) right before it is written; otherwise lift -> rapid at clearance ->
    proper entry (enter_at) at the far point, and the run continues from there.
    Test (synthetic, in code): a run [p, q] with q 20+ mm away through standing stock, tool entered at p. Mutation:
    the in-run check bypassed -> must fail by the measured zmap ae_eff (print ae_eff and a).
(3) COUNTERS in stats: in-run pairs checked and converted (e.g. irun_chk / irun_cvt), plus bstd_skip_<reason> for
    EVERY trans_guard early exit (so a judge run shows the guard ran). The Z-equality "tool up" change (tool up must
    come from the last emitted move - a rapid, or the tool above the stock top at its XY - never from Z equality) ONLY
    if it fits in 5 lines; otherwise leave it and say so.
(4) Synthetic in-code scenes only - NO fixture derived from James's part (CF data stays out of git; no test that skips
    when a fixture is missing). No full CF run needed: the supervisor runs the CF judge afterwards.
## engine/BS1a4d6_RESULTS.md "BS1a4d8c": confirmation of the cause (file:line), the change with file:line, line count vs
337c44b, PASTED exit codes of all at-risk tests + the new tests, all mutation outputs, git diff --numstat. Then stop.
