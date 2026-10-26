# Task BS1a4d6: a failed split piece is emitted as its OWN region at its lightest option (never dropped); credit_real_bore small-bore bound. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances, with ONE approved exception (item b).
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ (create it;
untracked) - never /tmp or /private/tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
CAUSE FIRST: write in engine/BS1a4d6_RESULTS.md, before any code change, which pieces hit replan0_drop and why their
lightest option cannot rejoin q4 (values).
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py, engine/rough.py and engine/test_engine.py only. Results in the NEW file engine/BS1a4d6_RESULTS.md.
BUDGET: <= 30 changed non-test engine lines vs b6c48e1, STOP and report at ~45. FRESH session, HARD CAP 2 h (run `date`
at start and write it in the results file). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the
commit carrying this brief (= b6c48e1 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (run all; NOT the full suite): test_bs1a4d2b_centred_entry_bore, test_bs1a4d4_credit_entry_matches_prediction,
test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4d_credit0_lightest_option, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_lshaped_channel,
test_bs1a_straight_channel, test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro,
test_dt1_synthetic_rough_twice_identical, test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load,
test_bs1a4d_credit_real_bore.

## Facts (supervisor, verification of b6c48e1)
- rough.py emit re-check: a plan0_splitbore piece (replan0 == 2) whose real-bore re-check fails runs the existing
  credit-0 shrink ladder; when the lightest option's first piece cannot join q4 by a segment-checked chord the act is
  replan0_drop and the cut is DROPPED (stock left for the ring).
- That breaks two at-risk tests on b6c48e1:
  test_bs1a4d_credit0_lightest_option: "credit-0 failure (-6.2719, 3.5231, 0.381, 'replan0_drop') not EMITTED as its
  lightest option: {... 'option': 'drop_ring', 'max_ae': 2.5}";
  test_bs1a_lshaped_channel: "7 full-width window(s) at cutting feed in the channel: (2.741, 15.276..20.276, Z 0.381,
  12.0-12.5 mm wide)" - the ring cut the dropped piece's stock full width.
- test_bs1a4d_credit_real_bore (matcher rewritten in BS1a4d5) fails "credit is still (about) the tool_r start disk:
  extra 88" (needs > 100) on a correctly matched SMALL bore (r 0.5 / 0.2).
## Change
(a) Own-region path: a split piece whose real-bore re-check fails at every level is emitted as its OWN region at its
    lightest option, with its own enter_at entry (the normal ladder; enter_at stays the only entry). Never dropped,
    never emitted at the failing load. List it in failed_region_emitted and credit_fallback with its measured max_ae.
    Its stock must not be left for the ring. test_bs1a4d_credit0_lightest_option and test_bs1a_lshaped_channel must
    pass UNCHANGED. The predictor mirrors the emitted entry; credit is backed only by the actually emitted bore.
(b) Approved edit to test_bs1a4d_credit_real_bore: scope the existing "extra > 100" assert to caps whose emitted bore r
    >= min_helix_r (1.903; the case it was written for) and keep it unchanged there. For smaller bores ADD a replacement
    assert: the credited area equals the emitted bore's own sim footprint within the grid tolerance, measured from the
    emitted helix (centre and r). Do not just remove the check. If the scene then has no large-bore cap left, SAY SO in
    the results; do not invent one.
## Mutations (scratch copies only, each must fail BY A MEASURED VALUE; record the number)
- route the failed split piece back to replan0_drop: test_bs1a_lshaped_channel (full-width window mm) or
  test_bs1a4d_credit0_lightest_option must fail;
- emit the own-region piece at the failing load: test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load must fail
  with the overload mm;
- credit a small bore with the tool_r start disk instead of its real footprint: the new (b) assert must fail by the
  area difference.
## engine/BS1a4d6_RESULTS.md: cause, change with file:line, line count, own-region pieces (xy, z, option, max_ae) on the
L scene, PASTED exit codes of all at-risk tests, the three mutation outputs. Then stop.
