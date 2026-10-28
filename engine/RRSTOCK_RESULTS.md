# Task RR-STOCK — results

Session: Tue Oct 27 17:18 -> 19:00 MST (2 h cap 19:18). Worktree
/Users/James/ai-sandbox/stevecam-fe5t, branch fe5-trial @ 13c2414 (FE5h
26b19fc + brief). All tests through
/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh, FOREGROUND only. NOT
committed (per brief). opencode.json was already modified at session
start — untouched here.

## THE CHANGE (file:line, after edit)

- engine/entry_depth.py:334 +replay_stock(moves, dia, corner, out_path,
  box=/init=): replays an EMITTED move list (modal x/y/z, g 0|1, mm) with
  its tool (profile disk dz = 0 inside R-cr, cr - sqrt(cr^2-(d-R+cr)^2)
  beyond: cr=0 flat, cr=corner bull, cr=dia/2 ball) sampled at <= fine/4
  = 0.025 mm (the judge's own _move_samples resolution; G0 never cuts)
  into the engine's own 0.1 mm stock, starting from `init` (A,x0,y0,cell;
  used directly when cell == fine — resample_fine at equal pitch max-pools
  the touching neighbour, so it is bypassed) or a full `box` raised to
  top_z; writes .npy + x0/y0/cell .json sidecar; prints compute time.
  numpy only; engine code imports no zmap/verify.
- engine/cli.py:750-754 rough --stock-out: after rough() returns, the
  emitted moves are replayed (box = --stock, top = stock zmax) OVER the
  coarse planning file — downstream gets the replay, never the coarse
  over-cleared stock.
- engine/cli.py:261-269 + 554-556 finish --stock-out (needs --stock-from):
  replay of THIS program's emitted moves (ball corner=dia/2; a rest pass
  replays with the rest tool) from --stock-from, same .npy+sidecar.
  Programs are written before the replay - emitted moves untouched.
- connector/runner.py:1067-1069,1085 finish subprocess gets
  "--stock-out stock_after_finish_engine.npy" (freshness-removed first);
  connector/runner.py:1214 rest pass "--rest-from stock_fin_engine" —
  the ENGINE replay, not zmap's stock_after_finish.npy. zmap still writes
  its --stock-out chain (rough->finish->rest) for judging and reports;
  the connector hands the engine NO zmap stock.

## BUDGET (deviation, reported)

git diff --numstat 26b19fc -- engine connector ':!*test_*':
    7  1  connector/runner.py
   57  0  engine/TASK_RRSTOCK.md   <- the brief itself, not my code
   18  0  engine/cli.py
   64  0  engine/entry_depth.py
Code only (brief excluded): 90 added/changed lines — at the "~90 STOP and
report" line, over the 60 target. (The brief's literal numstat also
counts its own 57-line brief file.) Tests: engine/test_finish.py
+165/-1 (the -1 is the __main__ list's last line gaining two entries;
NO existing test, assertion or tolerance changed).

## RED tests on UNCHANGED code (all written first, all FAILED)

- (b) test_rrstock_finish_handoff_matches_judge: FAIL exit 1 —
  "cli finish failed rc=2: engine.cli: error: unrecognized arguments:
  --stock-out .../stock_after_finish_engine.npy" (replay did not exist).
- (a) test_rrstock_rough_handoff_not_below_judge: FAIL exit 1 (1m47s):
  "rrstock(a): standing=800000 cells, violations(>0.10)=1116
  (11.2 mm2), cells >0.5mm low=1061, max deficit 13.335 mm"
  (supervisor's TB measurement: 1190 cells / 11.9 mm2 / max 15.019 mm).
  TOL = 0.1 mm (brief's value; kept). Comparison read = max over the
  handoff cells overlapping each judge cell (the conservative
  resample_fine read the finish itself performs).
- (c) connector/test_connector.py::TestZg1connStockBottomE2E::
  test_tb_rest_chain_checks_stock_bottom: FAIL exit 1 (497.01s) —
  FileNotFoundError runs/1950/check.json: the TB chain died at the
  finish judge's axial_plunges gate (max 1.1303 mm, FE5h's number).

## SAME tests AFTER the change

- (b): PASS exit 0 (23.3s): "standing=17042 cells, |engine-judge|>0.10
  at 0 cells, max diff 0.0000 mm" — engine replay cell-exact vs zmap.
- (a): PASS exit 0 (2m28s): "standing=800000 cells, violations(>0.10)=0
  (0.0 mm2), cells >0.5mm low=0, max deficit 0.000 mm".
- (c): PASS exit 0 (671.75s) — full TB rough->finish->rest chain with
  all zmap gates green; the finish entry planner now sees the standing
  slivers in the replayed handoff instead of plunging through them.

## AT-RISK battery (all ran, exit codes pasted)

- engine/test_finish.py WHOLE file (incl. both new tests and
  test_stock_out_roundtrip): "ALL FINISH TESTS PASSED" exit 0 (9m18s).
  fe5f skip-bore count 21 — unchanged from the accepted FE5h baseline.
- engine/test_entry_depth.py: "ALL ENTRY_DEPTH TESTS PASSED" exit 0.
- test_engine.py test_rough_testblock_r2 (71.0s), test_rough_testblock_r4
  (65.3s), test_dt1_synthetic_rough_twice_identical (16.4s),
  test_rr1b_rest_rough_synth_pocket, test_rr1c3_bay_deep_groove_top_down,
  test_rra2_deep_top_scope, test_rra3_straight_descent_scope,
  test_rr1c5c_closed_pocket_bore_entry_no_deep_axial: all PASS, exit 0
  (2m36s).
- verify/test_zmap.py -k "zg1 or ze2b" + connector/test_tlg1.py (one
  pytest run, -k "zg1 or ze2b or tlg1"): 26 passed, exit 0 (13s).
- connector/test_connector.py -k "rest or stock": 15 passed exit 0
  (7m15s) with TestZg1connStockBottomE2E::test_tb_rest_chain_checks_stock_bottom
  deselected — that 16th matching test is red (c)/green (c) above, run
  separately to avoid a third 11-minute E2E (3600 s timeout test).

## COMPUTE TIME (item 2)

- TB (test block, flat 12.686, 41,659 moves, 0.1 mm grid 1127x1027):
  engine.cli rough total 105.7 s, of which replay_stock = 43.6 s.
  Rough CLI green-(a) wall total 2m28s including the zmap judge.
- CF (core_front_setup, stock 257.3 x 165.1 x 48.8 mm, floor 4.0,
  ENGINE_WORKERS 4): one engine.cli rough --stock-out through the small
  lane did NOT finish inside a 40-minute lane window at 18:18-18:58
  (partly lane queueing; CF rough is far above the brief's 10-minute
  gate), so per the brief I report TB + an estimate: the replay cost
  scales ~ moves x tool-window; CF stock area is 5.3x TB and its cut
  path/move count ~3-5x, estimate replay_stock(CF) ~ 4-8 min on the
  0.1 mm grid. (Supervisor times CF in the CF chain check.)
- Small-scene finish replay: 23,176 moves in 6.8 s.

## Programs

Rough/finish emitted moves are generated exactly as before (the replay
runs AFTER the program is written; rough(stock_out=...) coarse save is
overwritten, never read downstream): rough/finish programs byte-identical
— evidenced by test_rough_testblock_r2/r4, test_dt1_twice_identical and
the whole finish suite staying green. The rest pass is now PLANNED on the
engine's replayed after-finish stock (the intended handoff change); on
TB its entry decisions differ where the coarse/zmap stock misread slivers
— that is the fix red (c) demanded.

## Notes / deviations

- BUDGET at 90 code lines (see above) — stopped there, did not refactor
  further under the cap.
- resample_fine's equal-pitch neighbour max-pool (its kx/ky edge test is
  "> ix", not "> ix+1") left untouched (frozen by the estimator tests);
  replay_stock bypasses it when cell == fine.
- No slot was stuck at any point; no lock files touched.
- CF rough timing exceeded the lane window — reported as estimate above.

## Exit-code summary (pasted)

RED:  (b) EXIT=1 | (a) EXIT=1 | (c) EXIT=1 (1 failed in 497.01s)
GREEN (b) EXIT=0 | (a) EXIT=0 | (c) EXIT=0 (1 passed in 671.75s)
test_finish.py EXIT_FINISH=0 | test_entry_depth.py EXIT_ENTRY=0
test_engine named EXIT_ENG=0 | zmap -k zg1/ze2b + tlg1 EXIT_Z=0
connector -k "rest or stock" (15, TB E2E deselected) EXIT=0
