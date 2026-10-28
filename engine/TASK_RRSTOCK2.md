# Task RR-STOCK2: rest-rough hands down its own replayed stock; skip clusters carry a reason; the rest handoff source is pinned by a test. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh). If a run would exceed 10 min, don't
start it; write what you would have run into the results file. The supervisor times the CF replay in the chain judge.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT edit verify/
or opencode.json; engine code NEVER imports zmap/verify (tests may); emitted PROGRAMS must not change (rough, rest-rough, finish,
rest) - only handed-down stock files and stats change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-fe5t/scratch/ - never /tmp.
RESULTS: create engine/RRSTOCK2_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and
what it printed.
CONTINUE: continue from your plan; don't stop before every red test exists and has run on the UNCHANGED code, and every test
below has run.
Edit engine/cli.py, engine/rest_rough.py (or wherever engine.cli rest-rough lives), engine/finish.py, engine/entry_depth.py
only if needed, and connector/runner.py.
BUDGET: <= 60 changed non-test lines vs bee88c8 (`git diff --numstat bee88c8 -- engine connector ':!*test_*' ':!*TASK_*'`);
STOP and report at ~90. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-fe5t, branch
fe5-trial at the commit carrying this brief (= RR-STOCK bee88c8 + brief).
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Engine test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_finish as t; t.<test_name>()"
Connector/verify test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- RR-STOCK (6da4260/bee88c8) added entry_depth.replay_stock(moves, dia, corner, out, box=/init=) and uses it for rough
  --stock-out and finish --stock-out; the connector's rest pass now plans on the engine replay. replay_stock is a PORT of the
  judge's stamping; test_rrstock_replay_matches_analytic_stamp checks it against exact heights.
- engine.cli rest-rough (the T20 ball rest-rough) has NO --stock-out. In the CF chain the finish after the rest-rough is therefore
  planned on ZMAP's rest stock - the last place a judge stock feeds the engine.
- FE5f skip clusters in finish stats (engine/finish.py _fe5_cluster_skips ~1915) carry center/bbox/area_mm2/max_depth_mm/n but
  NO reason. The runner writes check.json["left_for_hole_op_or_another_setup"] (runner.py ~1346).
- Mutation M2 (rest pass --rest-from pointed back at zmap's stock_after_finish.npy in runner.py) is caught by NO existing test.
## Items
1. engine.cli rest-rough --stock-out: replay_stock of the rest-rough's EMITTED moves (its ball) onto its --stock-from input stock,
   .npy + sidecar. Connector/chain: wherever a rest-rough feeds a finish, the finish gets this file (connector/runner.py if it
   runs a rest-rough; the CF chain scripts are the supervisor's).
2. Per-cluster "reason" in the fe5f skip stats: a cluster whose centre lies over a THROUGH OPENING - computed from the part the
   finish already has (the part surface at the cluster centre is at the stock bottom, or there is no part) - gets
   "left_for_hole_op_or_another_setup"; every other cluster gets "entry_deeper_than_floor_no_legal_ramp" (its max_depth_mm is
   already there). Do NOT invent a reach cause the code does not compute.
3. Connector argv test: the rest pass's --rest-from must be the engine's replay file (stock_after_finish_engine*), never a zmap
   stock file. It must FAIL when runner.py passes zmap's stock_after_finish.npy (state that you checked this with a scratch
   mutation copy, and paste the failure).
RED TESTS (write first, run on the UNCHANGED code, paste numbers - each must FAIL there):
 (a) test_rrstock2_restrough_handoff_not_below_judge: a small synthetic rest-rough scene (reuse a test_engine rest-rough scene,
     e.g. the rr1b synth pocket setup); rest-rough with --stock-out; judge the SAME emitted rest-rough program with verify.zmap
     --stock-out (--stock-in = the same input stock, on the 0.1 grid); engine handoff >= judge - 0.1 at every cell with standing
     stock. Must stay under 10 min.
 (b) test_rrstock2_skip_clusters_have_reason: the FE5f through-bore scene (test_fe5f_skip_bore_entries' setup) -> every skip
     cluster has a non-empty reason; the bore cluster's reason is left_for_hole_op_or_another_setup; plus one scene where a skip
     is NOT over a through opening (or a unit call on _fe5_cluster_skips' classifier) -> entry_deeper_than_floor_no_legal_ramp.
 (c) the connector argv test of item 3.
AT-RISK (must stay green; run ALL, paste exit codes): the whole engine/test_finish.py (fe5f bore skips stay 21), engine/test_entry_depth.py,
test_engine.py rest-rough tests test_rr1b_rest_rough_synth_pocket, test_rr1c3_bay_deep_groove_top_down, test_rra2_deep_top_scope,
test_rra3_straight_descent_scope, test_rr1c5c_closed_pocket_bore_entry_no_deep_axial, plus test_rough_testblock_r2,
test_dt1_synthetic_rough_twice_identical, verify/test_zmap.py -k "zg1 or ze2b", connector/test_tlg1.py, connector/test_connector.py
-k "rest or stock" EXCEPT the 11-min TB E2E (the supervisor runs that one).
## engine/RRSTOCK2_RESULTS.md: change (file:line), line count, red tests before/after, PASTED exit codes, git diff --numstat. Then stop.
(Supervisor verifies from committed code: mutations (rest-rough replay skipped; reason dropped; M2) -> each red test fails by its
measured value; full suites; chain9 = the merge candidate.)
