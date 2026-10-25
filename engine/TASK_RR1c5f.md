# Task RR1c5f: re-scope the SCENE of test_rr1c5d_front1_chord_offset_slabs so it reaches its case. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: in test_rr1c5d_front1_chord_offset_slabs ONLY its scene (stock and/or level setup) may change, plus ONE added
assert (item 2); its threshold and vacuity guard stay exactly as they are. Do not touch any other test.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; NO engine change (test/scene only).
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-rr1b/scratch/ - never /tmp.
CAUSE FIRST: copy the bisect table below into a section "RR1c5f" of engine/RRA_RESULTS.md before any change.
CONTINUE: continue from your plan; don't stop before the test has run.
Edit engine/test_engine.py only. BUDGET: <= 20 changed test lines. FRESH session, HARD CAP 2 h (run `date` at start).
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit carrying this brief.
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK: test_rr1c5d_front1_chord_offset_slabs, test_rra2_deep_top_scope, test_rra3_straight_descent_scope,
test_rr1c3_bay_deep_groove_top_down, test_rr1c_thin_band_inpass_ramp, test_rr1c_narrow_pocket_side_entry,
test_rr1c5d_live_grid_fine_for_coarse_stock.

## Facts (supervisor bisect, 2026-10-25; that test only, on archives of each rr1b engine commit; "deep" = ae2 windows
at >= 0.9 x 2280 feed with a > 0.5 mm, as the test's own guard counts them)
| commit | windows | at cutting feed | deep | max a (feed) | max a (all) | result |
| 8d96cea (added the test) | 81 | 63 | 0 | 0.241 | 0.879 | FAIL vacuous |
| 5f938de | 81 | 63 | 0 | 0.241 | 0.879 | FAIL vacuous |
| eee3f66 | 81 | 63 | 0 | 0.241 | 0.879 (1st sim 0.199) | FAIL vacuous |
| 447c434 | 81 | 63 | 0 | 0.241 | 0.879 | FAIL vacuous |
| 07f0c7e | 81 | 63 | 0 | 0.241 | 0.879 | FAIL vacuous |
| 9260c78 | 82 | 63 | 0 | 0.241 | 0.879 | FAIL vacuous |
| fa54f9b | 82 | 63 | 0 | 0.241 | 0.879 | FAIL vacuous |
Cause: the test has been vacuous SINCE the commit that added it - the scene never produced a deep cutting-feed window.
(eee3f66's own fix to the test helper's grid origin changed only the first of its two zmap sims.)
## Change
1. Re-scope the SCENE only (stock and/or level) so the test reaches its case: at least one deep cutting-feed window
   (a > 0.5 mm at >= 0.9 x feed) that the slab check actually inspects.
2. Add ONE assert that the front-1 chord-offset slab code path is exercised: the count of chord-offset slabs emitted or
   inspected is >= 1, read from the engine's own stats or tags (find the existing front-1 stats/tags in
   engine/rest_rough.py, e.g. the front-1 flags / rr_f1_mismatch bookkeeping; do not add engine code).
3. Report the new scene's windows / deep count / max a in the same table form.
4. If no reasonable scene reaches a deep window at all (the engine never makes one there), STOP and report what you
   tried and the max a you measured; change nothing.
Mutation (scratch copy only, never committed): break the chord-offset slab logic (e.g. drop the front-1 chord offset in
rest_rough.py); the re-scoped test must then fail by a MEASURED value. Record it.
## RRA_RESULTS.md "RR1c5f": the table, the scene change, PASTED exit codes of the at-risk tests, the mutation output.
Then stop.
