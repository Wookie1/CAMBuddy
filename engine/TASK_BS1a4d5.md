# Task BS1a4d5: band credit is backed by the bore that is actually emitted (split pieces). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances, with ONE approved exception:
the matcher inside test_bs1a4d_credit_real_bore (item b). Add NEW tests only otherwise.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS); a fix that only passes by moving a limit is rejected.
CAUSE FIRST: write the cause in engine/BS1a4d5_RESULTS.md before any code change (which pieces, planned bore vs emitted bore, offset in mm).
CONTINUE: continue from your plan; don't stop before the test has run.
Edit engine/band.py, engine/rough.py and engine/test_engine.py only. Results in the NEW file engine/BS1a4d5_RESULTS.md.
BUDGET: <= 15 changed non-test engine lines vs 6f116f9 (`git diff --numstat 6f116f9 -- engine/band.py engine/rough.py`),
STOP at ~25. FRESH session, HARD CAP 2 h (run `date` at start and write it in the results file). Worktree
/Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief (= bs1a4d4 6f116f9 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK existing tests (run these plus your new/edited tests; NOT the full suite): every test_bs1a4* test,
test_bs1a_lshaped_channel, test_bs1a_straight_channel, test_bs1a3_no_band_after_a2d, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d3_links_measured_as_cuts, test_bs1a4d4_credit_entry_matches_prediction,
test_bs1a4d4_entry_pinned_to_stored_start, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical.

## Facts (supervisor, instrumented run of 6f116f9, L scene Z 0.381)
- band.py channel_regions plans each ring segment through shrink_ladder; its credit/bore for planning is evaluated at
  the chosen path's path[0]. The emitted region is a PIECE of that path after isl_ok3 filtering / _split_at_jumps:
  its start pc[0] usually differs from path[0]. BS1a4d4 stores res['bore'] = the predictor's bore AT pc[0], and the
  emitter enters with exactly that bore.
- So for a credited split piece the planning sim pre-cleared the bore found at path[0], while the entry clears the
  bore found at pc[0]. Example: piece (-4.8248,-1.9977) emits a helix centred (-5.2405,-1.8255) r 0.5 (= its stored
  bore); no planning sim with that bore exists. Earlier diag: 14 such split pieces with a bore on the L scene.
- Pieces with NO bore at pc[0] are already handled (credit 0, tag plan0_split, res['replan0'] = True -> emit-time
  credit-0 re-check in rough.py ~2146-2180 via shrink_ladder / failed_region_emitted).
- test_bs1a4d_credit_real_bore fails on 6f116f9 only because its matcher pairs a cap with the first _simulate call
  within 0.5 mm, which is now a NEIGHBOUR's emit-time re-check.
## Change
(a) Engine: a credited piece whose emitted bore (at pc[0]) differs from the bore it was planned with (at path[0])
    goes through the same emit-time re-check as plan0_split, but the re-check simulates the piece with its ACTUAL
    bore (bore_xy = the stored centre and r, as the planning sim does). Credit = that result; the piece is listed in
    stats credit_fallback with the new tag 'plan0_splitbore'. If the re-check fails every level, the existing
    lightest-option / failed_region_emitted path applies.
(b) Test (approved edit): rewrite ONLY the matcher in test_bs1a4d_credit_real_bore so each credited, helix-entered cap
    is matched to the planning or re-check sim whose bore_xy equals its EMITTED helix (centre within 1e-6, r within
    1e-6; capture the emitted helix exactly, e.g. by spying engine.rough._helix_moves). No proximity matching. Every
    such cap must have a match; an unmatched cap fails with the cap and its emitted bore printed. Keep every other
    assertion of that test exactly as it is.
Mutation (scratch copy only, never committed): drop the (a) branch; the rewritten test must then fail on a split cap
with the measured planning-vs-emitted bore offset in mm in the message. Report that output.
## engine/BS1a4d5_RESULTS.md: the cause (with values), the change with file:line, line count, how many pieces were
tagged plan0_splitbore on the L and TB scenes, PASTED exit codes of the at-risk + edited tests, the mutation output.
Then stop.
