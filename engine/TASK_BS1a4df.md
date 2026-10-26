# Task BS1a4d-f: finish BS1a4d - call-compatible bore credit, and real fail-on-base tests. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; you MAY fix the two NEW tests of
this branch (test_bs1a4d_credit0_lightest_option, test_bs1a4d_credit_real_bore) since they are not on main.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify; no margin/leave/feed change. Edit engine/band.py,
engine/rough.py and engine/test_engine.py only.
BUDGET: <= 20 changed non-test lines vs 5896dbf (`git diff --numstat 5896dbf -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~30. FRESH session, HARD CAP 2 h. Worktree /Users/James/ai-sandbox/stevecam-bs1a4d, branch bs1a4 at the
commit carrying this brief (= BS1a4d WIP 5896dbf + this brief).
AT-RISK existing tests (run these plus your two new tests; NOT the full suite): test_bs1a4b_windows_align_zmap,
test_bs1a4c2_band_chord_cl_checked, test_bs1a_lshaped_channel.

## Facts (supervisor, detached worktrees)
- On 5896dbf the full suite crashes: the existing tests test_bs1a4b_windows_align_zmap and test_bs1a4c2_band_chord_cl_
  checked replace band.channel_regions with a spy of the OLD signature (rings, stock, isl_ok3, z, tool_r, leave, cell,
  stats=None); rough.py now calls channel_regions(..., borefn=...) -> "TypeError: cr_spy() got an unexpected keyword
  argument 'borefn'". 5896dbf also gave _simulate a new positional parameter bore_xy.
- On 22cdff7: test_bs1a4d_credit0_lightest_option PASSES (its scene never reaches the silent credit-0 drop), and
  test_bs1a4d_credit_real_bore ERRORS ("_simulate() takes from 6 to 7 positional arguments but 8 were given") - neither
  is a fail-on-base.
## Change (design fixed - do exactly this)
(1) channel_regions keeps its EXACT signature. rough.py passes the bore function through a SCOPED context: a
    contextvars.ContextVar in band.py with a small `with band.bore_context(borefn):` around the channel_regions call.
    No bare module global, no signature introspection. Without a context, channel_regions behaves as BS1a4c did
    (start-centred credit), so direct callers and spies work unchanged.
(2) _simulate takes bore_xy as a KEYWORD-ONLY argument defaulting to None; old positional calls stay valid.
(3) Both new tests FAIL BY ASSERTION on 22cdff7 (`git archive 22cdff7`, never checkout): (a0) a scene where 22cdff7
    silently drops a credit-0-failing region (replan0_drop) and the new code lists it in failed_region_emitted with its
    option; (c) call the base through the OLD signature and assert on the credited cells (start-centred disk vs the
    real helix + floor-circle footprint).
## Report
The test-block region (6.28, -2.08) and the two L-channel regions ((-18.72,-0.12), (-2.09,5.74)): engine max ae and the
option chosen.
## engine/BS1a4_RESULTS.md - add section (14) BS1a4d-f: change with file:line, line count, the Report items, PASTED exit
codes of the at-risk + new tests and the fail-on-22cdff7 output. Then stop.
