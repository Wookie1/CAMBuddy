# Task BS1a4d6c: the predictor pre-clears EXACTLY what the emitted entry cuts. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d6c" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. CAUSE FIRST: write item 0 there before any code change.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py, engine/rough.py and engine/test_engine.py only.
BUDGET: <= 25 changed non-test engine lines vs 46db9be; STOP and report at ~35. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= BS1a4d6b 46db9be + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 18): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, plus your new test.

## Facts (coordinator judgement of 46db9be)
- Accepted: the whole-option coverage, the q4 fallback and its test, the (b) refinement, the three mutations.
- NOT accepted: band.py _simulate (line ~180) now pre-clears the tool_r start disk at path[0] UNCONDITIONALLY. That
  breaks "the predictor mirrors the emitted entry": if a credit-0 arrival is a side entry or a link into standing
  stock, that arrival's own engagement disappears from the prediction (an under-read).
## Items
0. Explain the metric in the results: what _simulate's window value (max_ae / ae_eff) is - area per window, area per
   step, a width? - with its unit, why values of 12-24.5 and 36.25 exceed the 12.686 mm tool diameter, and whether any
   gate compares it to 2.44 (ZE2) or 2.286 (ZE2B) directly (name file:line of each comparison).
1. Rule: pre-clear exactly what the emitted entry cuts.
   - helix bore of radius r_b: clear the footprint disk (r_b + tool_r) - as before;
   - axial plunge at an already-bored spot: nothing extra;
   - side entry or link: do NOT pre-clear; simulate the approach move through the stock so its load is measured.
   If the emitted entry type is not known inside _simulate, pass it in from each caller (band.py:278, band.py:380,
   rough.py:1461, rough.py:2156 on 46db9be). Do not guess the type.
2. NEW test: a credit-0 piece entered from the side into standing stock. The predictor's max for that arrival must be
   >= the verify/zmap-judged engagement of the same arrival as emitted (no under-read), measured, both numbers printed.
3. For each own-region piece on the L scene (test_bs1a_lshaped_channel's), report the zmap-judged max engagement AS
   EMITTED next to the engine's number (the BS1a4d6b table read 12-24.5 pre-cut).
4. Mutation (scratch copy, revert): restore the unconditional pre-clear; your new test must fail by the under-read in
   mm (predictor vs judge). Record the number.
## engine/BS1a4d6_RESULTS.md "BS1a4d6c": item 0, the change with file:line, line count vs 46db9be, the item 3 table,
PASTED exit codes of all at-risk tests + the new test, the mutation output, git diff --numstat. Then stop.
