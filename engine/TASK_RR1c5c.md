# Task RR1c-5c: a bore-seed front enters through RR1c-4b's bore descent - fix ONLY the closed-pocket deep entry. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate, the ZB
floor 0.5, the validate_exact tolerance or the leave; do NOT edit verify/ or opencode.json. EVERYTHING ELSE IS FROZEN:
change only what this entry needs. Edit engine/rest_rough.py and engine/test_engine.py only.
BUDGET: <= 20 changed non-test lines vs dda4ed0 (`git diff --numstat dda4ed0 -- engine/rest_rough.py`, adds + dels),
STOP at ~30. FRESH session, HARD CAP 2 h. Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit
carrying this brief (= RR1c-5b WIP dda4ed0 + this brief). Read engine/TASK_RR1c5b.md first (what dda4ed0 implements).

## Facts (the RR1c-5b session's last run on dda4ed0)
The four RR1c-5b tests pass, but two EXISTING tests fail on the same deep entry:
- test_rr1c4b_closed_pocket_bore_levels: AssertionError "deep entry (ZB): [{'line': 196, 'x': 18.462, 'y': 18.7,
  'z': 28.2, 'depth_mm': 1.476...}]"
- test_rr1b_rest_rough_synth_pocket: AssertionError "deep entry: [same entry]"
Both passed on 45d8685, where a closed pocket is entered by RR1c-4b's bore: the helix bores to the lowest legal level,
the tool rises inside the bore, and each lower level is entered by a CL- and ZB-checked descent inside the bore. With
dda4ed0's fronts, a zone with no open edge uses C = its helix bore as the seed, but its lower level is entered by a
1.48 mm axial entry at (18.462, 18.70), Z 28.2 instead of the bore descent.
## Change
A bore-seed front's lower levels are entered through RR1c-4b's bore descent (helix to the level, then down the bore,
each descent step exact-CL and live-ZB checked as before), so both existing tests pass UNCHANGED. Nothing else changes.
## Tests
- Both existing tests above pass unchanged; the four RR1c-5b tests still pass; full engine/test_engine.py green.
- ONE NEW test: the closed-pocket bore-seed case has no axial entry deeper than 0.5 into live stock - it must FAIL BY
  ASSERTION on dda4ed0 (the 1.48 mm entry at (18.462, 18.70)) (`git archive dda4ed0`, never checkout).
- Run every test yourself and paste the exit codes.
## engine/RR1c5c_RESULTS.md: change with file:line, line count, PASTED exit codes + fail-on-dda4ed0 output. Then stop.
