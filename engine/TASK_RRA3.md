# Task RRA3: pin DEEP_TOP's scope at step-1 straight descents (test only). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add ONE new test only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; NO engine code change at all (test-only task); engine code never imports zmap/verify.
SCRATCH: scratch files and mutation copies go ONLY in this worktree's scratch folder
/Users/James/ai-sandbox/stevecam-rr1b/scratch/ (create it; it is untracked) - never /tmp or /private/tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, shallow 0.25, DEEP_TOP 0.3).
CONTINUE: continue from your plan; don't stop before the test has run.
Edit engine/test_engine.py only (one new test + its _main() registration). Results: APPEND a section "RRA3" to
engine/RRA_RESULTS.md. FRESH session, HARD CAP 2 h (run `date` at start and write it in the results file).
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit carrying this brief (= RRA2 072dc41 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK: test_rra2_deep_top_scope, test_rr1c_thin_band_inpass_ramp, test_rr1c3_bay_deep_groove_top_down,
test_rr1c5d_live_grid_fine_for_coarse_stock.

## Facts (from RRA2, engine/RRA_RESULTS.md)
- rest_rough.py: DEEP_TOP = 0.3 applies only to the step-2 ramp top-clear at the two descent re-entry sites; step-1
  straight descent uses `d <= shallow` (0.25).
- RRA2's mutation B (step1 `d <= shallow` -> `d <= DEEP_TOP`) was NOT caught: on the thin-band scene the step-1
  column reads ~0.55 mm, which fails under both limits, so no existing scene shows a step-1 column in (0.25, 0.3].
## Change
NEW test test_rra3_straight_descent_scope: build a SMALL synthetic scene (through the real rest_rough entry point, like
the existing rr1c tests) where a step-1 straight-descent candidate column reads a depth in (0.25, 0.3]. Assert every
recorded straight-descent (step 1) entry is <= 0.25 mm, printing the measured depth on failure; assert the scene is not
vacuous (the in-window column exists and was refused as a straight descent on the clean tree, with its measured depth).
Mutation (scratch copy in the scratch folder only, never committed): mutation B above; the new test must then FAIL by
the measured accepted straight-descent depth in mm. Show the clean-tree PASS and the mutation FAIL output.
If no simple scene can produce a step-1 column depth in (0.25, 0.3], STOP and report what you tried and the depths you
measured; do not change engine code or invent a path around the engine.
## RRA_RESULTS.md "RRA3": the scene, the test, PASTED exit codes of at-risk + new test, the mutation output. Then stop.
