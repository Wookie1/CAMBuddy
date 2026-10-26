# Task RR1c5e: test_rr1c5d_front1_chord_offset_slabs has gone vacuous - find why, then re-scope its SCENE. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test's assertions/tolerances; in test_rr1c5d_front1_chord_offset_slabs
ONLY its scene (stock / level setup) may change (step 2); its threshold and vacuity guard stay exactly as they are.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick (use `git archive <sha>` into the scratch folder
for old trees); no bypass flags; never relax a gate; do NOT edit verify/ or opencode.json; NO engine change (test/scene
only) unless step 3 applies - and then STOP and report instead.
SCRATCH: scratch files, archives and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-rr1b/scratch/ - never
/tmp or /private/tmp.
CAUSE FIRST: write steps 1 and the step-2/3 decision in engine/RRA_RESULTS.md (section "RR1c5e") before any change.
CONTINUE: continue from your plan; don't stop before the test has run.
Edit engine/test_engine.py only (that test's scene). BUDGET: <= 20 changed lines. FRESH session, HARD CAP 2 h (run
`date` at start and write it in the results file). Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the
commit carrying this brief.
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK: test_rr1c5d_front1_chord_offset_slabs, test_rra2_deep_top_scope, test_rra3_straight_descent_scope,
test_rr1c3_bay_deep_groove_top_down, test_rr1c_thin_band_inpass_ramp, test_rr1c_narrow_pocket_side_entry,
test_rr1c5d_live_grid_fine_for_coarse_stock.

## Facts (supervisor)
- On rr1b today the test fails "no deep cutting-feed windows: gate would be vacuous".
- rr1b's own engine commits, newest first (main merges excluded): fa54f9b (RR-A DEEP_TOP), 9260c78 (RR1c-5d (A) live
  grid 0.1), 07f0c7e (strip/zigzag front-1 flags), 447c434 (front-1 flag alignment fix), eee3f66 (test helper origin
  fix), 5f938de (front-1 dv x CELL fix), 8d96cea (RR1c-5d WIP, the commit that added this test).
## Steps
1. Bisect over those commits on scratch archives, running ONLY that test (and printing its deep cutting-feed window
   count and max depth on each). Report the first commit where it goes vacuous, with the measured deep-window
   count/depth before and after.
2. If that commit LEGITIMATELY removed the deep windows (the fix worked; the scene just no longer reaches the case),
   re-scope the SCENE (stock or level) so it again produces at least one deep cutting-feed window that the slab check
   actually inspects. Threshold and vacuity guard unchanged.
3. If instead it is a REGRESSION (deep work now hidden, or routed somewhere the check does not look): STOP and report
   in RRA_RESULTS.md; change nothing.
Mutation (scratch copy only, never committed): break the chord-offset slab logic the test guards (e.g. drop the
front-1 chord offset); the re-scoped test must fail by a MEASURED value. Record it.
## RRA_RESULTS.md "RR1c5e": bisect table, decision, the scene change, PASTED exit codes of at-risk, mutation output.
Then stop.
