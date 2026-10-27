# Task FE5g: no lifted vertex / steep in-pass drop in constant-Z finish passes (ZB). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only if needed.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate (ZB
BALL_AXIAL_FLOOR 0.5, CLCHECK, gouge checks stay as they are); do NOT edit verify/ or opencode.json; engine code never imports
zmap/verify (tests may); no stepover/stepdown/feed/leave change; never MOVE an existing pass point; never skip whole passes.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-fe5t/scratch/ - never /tmp.
RESULTS: create engine/FE5g_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code
and what it printed. Start with a short CAUSE section (where the lifted vertex is created, file:line, and why).
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/finish.py (and engine/entry_depth.py only if needed).
BUDGET: <= 60 changed non-test engine lines vs 74582f3 (`git diff --numstat 74582f3 -- engine/finish.py engine/entry_depth.py`);
STOP and report at ~90. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-fe5t, branch
fe5-trial at the commit carrying this brief (= main e53f503 + fe5 d7bb4f6 merged + FE5M 74582f3 + red test 9394f83 + brief).
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Run an engine test like this: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_finish as t; t.<test_name>()"
Run a connector/verify test like this: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"
RED TESTS (must turn green):
 1. engine/test_finish.py test_fe5g_no_lifted_vertex_in_constant_z_pass (74582f3: 98 lifted vertices, max 4.607 mm).
 2. connector/test_connector.py::TestZg1connStockBottomE2E::test_tb_rest_chain_checks_stock_bottom (74582f3: the T20 finish
    fails the ZB gate, 2 axial plunges, max 0.815 mm at XY -5.763, 20.745; ~9 min run).
AT-RISK (must stay green; run ALL and paste exit codes): the whole engine/test_finish.py (python engine/test_finish.py, all
FE5/FE5e/FE5f/FE5fb/FE5fc tests), engine/test_entry_depth.py, verify/test_zmap.py -k "zg1 or ze2b", connector/test_tlg1.py,
engine/test_engine.py tests test_rr1b_rest_rough_synth_pocket, test_rr1c3_bay_deep_groove_top_down, test_rra2_deep_top_scope,
test_rra3_straight_descent_scope, test_rr1c5c_closed_pocket_bore_entry_no_deep_axial.

## Facts (supervisor, measured on 74582f3)
- Test block (connector E2E, reproduced; run files for DIAGNOSIS ONLY, never as a fixture:
  /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/fe5g_e2e/stevecam-home0/runs/1950/):
  finish_neutral.ngc lines 15224-15227, a Z26 constant-Z pass at cutting feed:
    G1 X-5.8630 Y20.7370 Z26.0000 / G1 X-5.7960 Y20.7370 Z28.2680 / G1 X-5.7630 Y20.7450 Z26.0000
  Pass vertices sit on a 0.1 mm X grid; X-5.796 is an INSERTED off-grid vertex whose Z (28.268) is the drop-cutter CL at
  that XY (the same vertex/Z also lifts the Z28.05 pass, line 10519, and starts a ramped entry, line 12622). The 2.268 mm
  drop over 0.033 mm XY drives the ball 0.815 mm into live stock (ZB). It is an IN-PASS descent, not an entry, so FE5e/FE5f
  (entry estimator, skip/trim) never examine it.
- Synthetic red scene (test 1): 20 x 20 x 14 boss, constant-Z passes carry 98 interior vertices lifted > 0.5 above both
  neighbours, around the boss corners (e.g. (-14.762, -10.007) at Z 8.6 lifted 0.707; max 4.607).
## Items (coordinator spec)
1. ROOT FIRST: find where a constant-Z pass gets an inserted vertex whose CL is sampled (drop-cutter) far above the pass Z
   (pass split / fragment-trim / gap-split / corner insertion boundary - name it with file:line in CAUSE) and fix it THERE:
   an inserted vertex of a constant-Z pass carries the pass Z (or the pass is split at it), never a drop-cutter CL above it.
   Do not move existing points.
2. SAFETY NET (finish AND rest passes): any in-pass G1 descent steeper than 15 deg whose live-stock disk depth (the FE5
   estimator) exceeds 0.5 mm is ramped along the pass's own FOLLOWING vertices at the ramp angle (as FE5e's vertex-raise
   does for entries), else the illegal fragment is trimmed to its legal part; never skip whole passes; every trim listed in
   stats ("fe5g_trimmed": [{"x","y","z","depth"}]) and counted ("fe5g_trimmed_n"); ramped descents counted ("fe5g_ramped_n").
3. Programs where neither applies stay byte-identical.
## engine/FE5g_RESULTS.md: CAUSE (file:line), the change with file:line, line count vs 74582f3, both red tests' printed numbers,
PASTED exit codes of the red tests and all at-risk tests, git diff --numstat. Then stop. (Supervisor verifies from committed code,
runs mutations (root fix reverted; safety net disabled), the full suites, and the CF chain judge (chain8).)
