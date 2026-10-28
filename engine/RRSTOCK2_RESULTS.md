# RR-STOCK2 RESULTS

Session start: Tue Oct 27 19:07:22 MST 2026 (2 h cap => stop ~21:07).
Base: 7076ce7 (brief) on bee88c8. Branch fe5-trial.

## Plan
1. Explore: engine/cli.py rest-rough, engine/entry_depth.replay_stock, engine/finish.py _fe5_cluster_skips, connector/runner.py rest pass + check.json.
2. Write RED tests (a) rest-rough --stock-out handoff vs judge, (b) skip-cluster reason, (c) connector argv rest-from pin. Run on UNCHANGED code, paste exit codes (all must fail).
3. Implement items 1-3 (<=60 non-test lines).
4. Re-run red tests (green), then AT-RISK list, appending every run + exit code + git diff --numstat here.

## Log

### RED phase (UNCHANGED code @ 7076ce7)
- RED (a) test_rrstock2_restrough_handoff_not_below_judge: FAIL exit 1.
  First failure line: "AssertionError: engine.cli rest-rough has no
  --stock-out flag (rc=0)"; with the help-assert relaxed it proceeds and
  fails "rest-rough --stock-out wrote no handoff stock" (exit 1). Rest-rough
  scene itself runs in 0.2 s (1263 moves) - well under 10 min.
- RED (b) test_rrstock2_skip_clusters_have_reason: FAIL exit 1:
  "AssertionError: skip cluster without reason: {'center': [0.0, 1.0],
  'bbox': [-8.0, 8.0, -3.5, 5.5], 'max_depth_mm': 5.9, 'n': 437,
  'area_mm2': 144.0}" (no reason key; no _fe5_skip_reason exists).
- (c) connector/test_rrstock2.py::test_rrstock2_rest_from_is_engine_replay:
  PASSES on unchanged code (runner.py:1214 already carries the engine replay
  since RR-STOCK - the pin is the point). Red verified with the M2 MUTATION
  copy scratch/m2/ (runner.py:1214 --rest-from -> zmap stock_finish):
  FAIL exit 1:
  "AssertionError: the rest pass plans on zmap's judge stock
  stock_after_finish.npy - RR-STOCK says the engine replays its own finish"
  (M2_EXIT=1).
- Note: runner.py runs NO rest-rough (only the T20 rest-finish via
  engine.cli finish --rest-from); the CF chain scripts that run rest-rough
  are the supervisor's, so item 1's connector half is a no-op here.

### GREEN phase (after implementation: cli.py +13, finish.py +23/-2)
- test_rrstock2_skip_clusters_have_reason: PASS exit 0
  ("rrstock2(b): 1 cluster(s); bore cluster reason
  'left_for_hole_op_or_another_setup'; unit call classified
  'left_for_hole_op_or_another_setup' / 'entry_deeper_than_floor_no_legal_ramp'")
- test_rrstock2_restrough_handoff_not_below_judge: PASS exit 0
  ("rrstock2(a): standing=40000 cells, handoff below judge by >0.10 at 0
  cells, max deficit 0.000 mm") - rest-rough 0.2 s, replay 1.0 s, total < 2 min
- connector test_rrstock2_rest_from_is_engine_replay: PASS exit 0 on the
  real code (0.10 s); RED under the M2 scratch mutation (exit 1, above).
- git diff --numstat bee88c8 (non-test): 13 0 engine/cli.py, 23 2
  engine/finish.py = 38 changed lines (budget 60).

### AT-RISK battery (all ran through the lane, exit codes pasted)
- engine/test_finish.py WHOLE file: "ALL FINISH TESTS PASSED" exit 0
  (rrstock(a) 174.8s, rrstock(b) 23.3s, analytic 0.0s all green inside).
- fe5f bore skips unchanged: "fe5f skip-bore: skipped 21 passes in
  1 cluster(s) at [0.0, 1.0] (max live depth 5.90 mm)" exit 0.
- engine/test_entry_depth.py: "ALL ENTRY_DEPTH TESTS PASSED" exit 0.
- engine/test_engine.py test_rr1b_rest_rough_synth_pocket,
  test_rr1c3_bay_deep_groove_top_down, test_rra2_deep_top_scope,
  test_rra3_straight_descent_scope,
  test_rr1c5c_closed_pocket_bore_entry_no_deep_axial,
  test_rough_testblock_r2, test_dt1_synthetic_rough_twice_identical:
  all OK, exit 0 (dt1 16.0s, twice-identical moves re-proven).
- verify/test_zmap.py -k "zg1 or ze2b": 18 passed, 115 deselected, exit 0
  (12.26s).
- connector/test_tlg1.py: 8 passed, exit 0 (0.56s).
- connector/test_connector.py -k "rest or stock" (15 passed, 97 deselected)
  exit 0 (429.87s = 7m09s), with the 11-min TB E2E
  TestZg1connStockBottomE2E::test_tb_rest_chain_checks_stock_bottom
  DESELECTED per the brief (the supervisor runs that one).
- connector/test_rrstock2.py: 1 passed, exit 0 (0.09s).

## Change (file:line)
- engine/cli.py:653-658 rest-rough parser gains --stock-out;
  engine/cli.py:334-340 after the program is written,
  entry_depth.replay_stock(moves, dia, dia/2.0, --stock-out,
  init=load_heightfield(--stock-from)) - the rest-rough's OWN emitted ball
  moves replayed onto its input stock (.npy + x0/y0/cell sidecar). Runs
  AFTER posting, so emitted programs cannot change.
- engine/finish.py:1943-1960 new _fe5_skip_reason(clusters, surf, floor_z):
  drop of a 0.2 flat at the cluster centre; NO part (nan) or part surface
  at/below the stock bottom (the setup floor) =>
  "left_for_hole_op_or_another_setup", otherwise
  "entry_deeper_than_floor_no_legal_ramp". No invented reach cause.
  engine/finish.py:2631-2634 stats["fe5_skipped_clusters"] now carries it
  (flows into the runner's check.json
  left_for_hole_op_or_another_setup unchanged, runner.py:1352).
- connector/runner.py: UNCHANGED - it runs no rest-rough (only the
  rest-FINISH, whose --rest-from is already the engine replay at
  runner.py:1214, now pinned by connector/test_rrstock2.py). The CF chain
  scripts that feed a rest-rough into a finish are the supervisor's - they
  should pass rest-rough --stock-out as the finish's --stock-from input.
- engine/entry_depth.py: unchanged (replay_stock reused as is).

## Exit-code summary (pasted)
RED (unchanged code): A_EXIT=1 | B_EXIT=1 | M2 mutation C_EXIT=1
("the rest pass plans on zmap's judge stock stock_after_finish.npy",
M2_RECHECK_EXIT=1 after scratch tidy)
GREEN: B_EXIT=0 | A_EXIT=0 | C_EXIT=0
AT-RISK: ENTRY_EXIT=0 | ENG_EXIT=0 | ZMAP_EXIT=0 | TLG1_EXIT=0 |
CONN_EXIT=0 (15 passed, TB E2E deselected) | FINISH_EXIT=0 | FE5F_EXIT=0
git diff --numstat bee88c8 (non-test): 13 0 engine/cli.py, 23 2
engine/finish.py = 38 lines (<= 60 budget).

## Notes
- Session 19:07 -> 19:31, far under the 2 h cap. No locks touched, no slot
  stuck, no Core Front job run, no full suite run (only the brief's named
  at-risk sets). scratch/m2/ keeps the M2 mutation copy (runner.py:1214
  --rest-from -> stock_finish; engine/verify symlinked in) with only
  test_rrstock2.py + test_toollib.py as test files.
- Emitted programs: the whole test_finish suite (incl. its byte-exactness
  tests) and test_dt1_twice_identical / test_rough_testblock_r2 stay green;
  the rest-rough replay runs strictly after the .ngc is written.

