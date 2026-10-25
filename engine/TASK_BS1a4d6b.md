# Task BS1a4d6b: cover the WHOLE lightest option of a failed split piece; settle the q4 entry; finish BS1a4d6's tests. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances, except the already-approved
BS1a4d6 (b) edit in test_bs1a4d_credit_real_bore (item 3 refines it). Add NEW tests otherwise.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
CAUSE FIRST: append a section "BS1a4d6b" to engine/BS1a4d6_RESULTS.md with the cause of the two red tests below BEFORE
any code change. CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py, engine/rough.py and engine/test_engine.py only.
BUDGET: <= 45 changed non-test engine lines vs b6c48e1 IN TOTAL (BS1a4d6 WIP already uses 20 in rough.py); STOP and
report at ~60. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5,
branch bs1a4d5 at the commit carrying this brief (= BS1a4d6 WIP 3a10607 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical, plus your new q4 test.

## Facts (supervisor run of the 17 at-risk tests on 3a10607)
- 15 PASS, incl. test_bs1a4d_credit_real_bore (10 helix-entered regions) and the d5 splitbore test (22 forced re-checks).
- FAIL test_bs1a4d_credit0_lightest_option: "credit-0 failure (-2.5924, 3.2481, 0.381, 'replan0_shrink0.55') not
  EMITTED as its lightest option: {'x': -2.7176, 'y': 3.0018, 'z': 0.381, 'area': 441.5, 'option': 'shrink1',
  'max_ae': 36.25}" (note the 36.25 mm max_ae).
- FAIL test_bs1a_lshaped_channel: "7 full-width window(s) at cutting feed in the channel: (2.741, 15.276..20.276,
  Z 0.381, 12.0-12.5 mm wide)" - same windows as on b6c48e1, so the stock there is still left for the ring.
- BS1a4d6 (a) WIP: when the lightest option's first piece cannot join q4 it emits only the NEXT >= 4-point piece
  (`own = next(pc for pc in pcs[1:] if len(pc) >= 4)`) as its own region; other pieces are not covered. The region's
  ORIGINAL entry at q4 was already emitted before the re-check runs.
## Items (coordinator)
1. Cover the WHOLE lightest option: every piece is either joined by a CL-checked link or entered with its own enter_at
   + descend. A piece shorter than 4 points must not silently leave its stock: emit it, or show by measurement that the
   ring pass cuts that stock at <= 2.44 mm (judged with verify/zmap in a test, not predicted). Drop stays only when the
   option has no cuttable piece at all, and then it is listed in failed_region_emitted with the reason.
2. The q4 entry. Preferred: decide before emitting the region's original entry, so nothing is entered for an abandoned
   piece. If the order cannot allow that, the q4 entry stays, but its emitted bore must be in the live stock and the
   predictor (credit backed by the emitted bore), and its descent must pass the CL check. Add a NEW test on the L scene
   asserting the q4 bore cells read as cut in the stock sim right after that entry. Report which way you took and why.
3. In test_bs1a4d_credit_real_bore's (b) edit use the named min helix radius constant (it equals 0.3 x tool_r =
   1.9029), not the literal. "Within 4 cells" is fine provided the start-disk mutation fails by far more: report both.
4. Mutations (scratch copies, each must fail BY A MEASURED VALUE, record the number, revert):
   - route the failed split piece back to replan0_drop: test_bs1a_lshaped_channel (full-width window mm) or
     test_bs1a4d_credit0_lightest_option must fail;
   - emit the own-region piece at the failing load: test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load must fail
     with the overload mm;
   - credit a small bore with the tool_r start disk: the (b) assert must fail by the area difference.
## engine/BS1a4d6_RESULTS.md "BS1a4d6b": cause, change with file:line, total line count vs b6c48e1, the q4 decision, the
own-region pieces (xy, z, option, max_ae), PASTED exit codes of all at-risk tests, the mutation outputs. Then stop.
