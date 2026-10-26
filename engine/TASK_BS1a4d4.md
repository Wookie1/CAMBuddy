# Task BS1a4d4: band entry credit and the emitted entry are one decision. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
CONTINUE: continue from your plan; don't stop before the test exists and has run.
Edit engine/rough.py, engine/band.py and engine/test_engine.py only. Write your results to the NEW file
engine/BS1a4d4_RESULTS.md (do not edit engine/BS1a4_RESULTS.md).
BUDGET: <= 30 NEW non-test lines vs 6793ad9 (`git diff --numstat 6793ad9 -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~45. FRESH session, HARD CAP 2 h (run `date` at start and write it in the results file). Worktree
/Users/James/ai-sandbox/stevecam-bs1a4d4, branch bs1a4d4 at the commit carrying this brief (= 6793ad9 + this brief).
AT-RISK existing tests (run these plus your new test; NOT the full suite): every test_bs1a4* test in
engine/test_engine.py (test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4c_backed_credit, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4d_credit0_lightest_option, test_bs1a4d_credit_real_bore, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d3_links_measured_as_cuts), test_bs1a_lshaped_channel, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d.

## Facts (supervisor diagnosis on 6793ad9, one Core Front rough generation)
- band.py:471 sets regions[-1]["credit"] = entry_credit(...) on EVERY band region (value tool_r or 0.0), so the key is
  always present.
- rough.py:2129 passes centred="credit" in res to enter_at: always True for band regions, so every band region entry
  takes the centred-only ladder whether or not the planner ever predicted a centred bore for it.
- The bore predictor (_bore_pred, rough.py:668, installed via band.bore_context at rough.py:2083-2085 and read in
  channel_regions as borefn) is consulted only during planning; the emit-time entry (rough.py ~2105-2129) is chosen from
  [res["start"], first cutting point] and re-searches its own centred ladder.
- On Core Front a region entry at (26.757, 13.427) Z 42.354 rejected all 96 centred candidates (circle_ok isl_ok) while
  _bore_pred was never evaluated at that XY; with no helix, enter_at fell to feed_down and rough failed closed.
## Change
1. Where band planning grants a region credit > 0 from the bore predictor (_bore_pred via band.bore_context), store the
   exact bore it accepted in the region dict: res['bore'] = start point evaluated, centre, radius, direction.
2. In rough.py's band region entry (about lines 2105-2141), replace `centred = "credit" in res`, which is always true
   because band.py:471 sets credit on every region. If res has 'bore', enter at exactly that stored start with exactly
   that stored bore: pass it through to enter_at / helix_entry, with no re-search. Otherwise use the normal entry ladder
   with all tiers (centred=False), as before BS1a4d2b.
3. If a stored bore fails any emit-time check, raise RuntimeError('band credit bore rejected at emit: <xy>'). Never
   substitute another entry.
## Test (engine/test_engine.py) - must FAIL BY ASSERTION on 6793ad9 (`git archive 6793ad9`, never checkout)
NEW test_bs1a4d4_credit_entry_matches_prediction: a synthetic channel scene with an island beside one band region, so
that no centred bore fits at that region's entry (credit 0 there), while another region gets credit > 0. Assert:
- rough generates;
- every region with credit > 0 entered with its stored bore (helix centre within 1e-6 of res['bore'] centre);
- no credit-0 region used the centred-only ladder;
- gates, clcheck and axial counts are all 0.
## engine/BS1a4d4_RESULTS.md: change with file:line, line count, the count of credited regions in your test scene and
their entries, PASTED exit codes of the at-risk + new tests and the fail-on-6793ad9 output. Then stop.
