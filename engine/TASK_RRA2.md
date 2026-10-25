# Task RRA2: pin the scope of RR-A's DEEP_TOP and fix its comment. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, shallow 0.25, DEEP_TOP 0.3).
CONTINUE: continue from your plan; don't stop before the test has run.
Edit engine/rest_rough.py (the DEEP_TOP comment ONLY) and engine/test_engine.py (new test). Results: APPEND a section
"RRA2" to engine/RRA_RESULTS.md.
BUDGET: comment-only engine change. FRESH session, HARD CAP 2 h (run `date` at start and write it in the results file).
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit carrying this brief (= RR-A fa54f9b + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK: test_rr1c3_bay_deep_groove_top_down, test_rr1c_thin_band_inpass_ramp, test_rr1c_narrow_pocket_side_entry,
test_rr1c4b_plateau_topdown_axial_load, test_rr1c5d_live_grid_fine_for_coarse_stock, test_rr1b_rest_rough_synth_pocket.

## Facts
- fa54f9b (RR-A): rest_rough.py DEEP_TOP = 0.3 is the step-2 ramp top-clear limit used ONLY at the two pass-loop
  DESCENT re-entry sites (deep = dzd > 1e-9, a lower level entered from the level just cleared). Level entries,
  straight descents and SE2 step 4 keep `shallow` (0.25). Bay scene: the accepted descent ramp top reads 0.2631 mm.
## Change
1. Replace DEEP_TOP's comment with exactly: "descent re-entry top-clear; calibrated at live grid 0.1, judge ZB 0.5"
   (one line; no code change).
2. NEW test test_rra2_deep_top_scope: pins that DEEP_TOP applies only at the descent re-entry sites. Mutation (scratch
   copy only, never committed): apply 0.3 at a level entry or a straight descent (not a descent re-entry); the new test
   must then fail by a MEASURED value - the accepted ramp-top depth in mm (a top in (0.25, 0.3] accepted where 0.25
   must hold). Show the test passes on this tree and fails on the mutation with that number.
   If no existing or simple synthetic scene can produce a level-entry/straight-descent top in (0.25, 0.3], STOP and
   report that in RRA_RESULTS.md (what you tried, the depths you measured) - do not invent a scene that bypasses the
   engine.
## RRA_RESULTS.md "RRA2": the comment change, the test, PASTED exit codes of the at-risk + new test, the mutation
output (with the measured depth). Then stop.
