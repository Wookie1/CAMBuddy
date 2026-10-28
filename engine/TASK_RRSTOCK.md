# Task RR-STOCK: the stock the engine hands downstream is a replay of the EMITTED program, never lower than what it removes. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate (ZB floor, CLCHECK,
gouge checks unchanged); do NOT edit verify/ or opencode.json; engine code NEVER imports zmap/verify (tests may); the rough,
finish and rest PROGRAMS (the emitted moves) must not change - only the stock files handed downstream change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-fe5t/scratch/ - never /tmp.
RESULTS: create engine/RRSTOCK_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and what
it printed.
CONTINUE: continue from your plan; don't stop before every red test exists and has run on the UNCHANGED code, and every test
below has run.
Edit engine/entry_depth.py, engine/cli.py, engine/rough.py, engine/finish.py and connector/runner.py only.
BUDGET: <= 60 changed non-test lines vs 26b19fc (`git diff --numstat 26b19fc -- engine connector ':!*test_*'`); STOP and report at
~90. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-fe5t, branch fe5-trial at the
commit carrying this brief (= FE5h 26b19fc + brief).
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Engine test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_finish as t; t.<test_name>()"
Connector/verify test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor, measured)
- The connector hands the finish and the rest pass the ENGINE's coarse post-rough stock (stock_after_rough_engine.npy, 0.5 mm,
  engine.cli rough --stock-out; connector/runner.py ~1014-1079 and ~1211). On the TB chain that stock is LOWER than the judge's
  0.1 mm replay of the same rough program at 1,190 cells (11.9 mm2) by > 0.5 mm, max 15.019 mm, all real standing stock, every
  one within 0.32 mm of a cell the rough really cut (141 clusters): the coarse kernel over-clears thin slivers beside cuts. Entry
  decisions then see no stock where full-height slivers stand: the TB finish ZB entry plunge 1.130 mm at (-34.763, 34.744).
- The rest pass is built with --rest-from stock_after_finish.npy, which is ZMAP's --stock-out of the finish (runner.py ~1140):
  the judge's stock feeds the planner, so a judge error would be shared by planner and checker.
- a2d output varies run to run (timing), so the sliver cells move: tests must measure on the run they build, never a pinned cell.
- engine/entry_depth.py already has exact 0.1 mm stamping (LiveStock.stamp_chord, FINE = 0.1).

## Items (coordinator spec)
1. ONE engine function (entry_depth.py or a small new helper next to it; numpy only) replays an EMITTED program (the move list
   the program is written from) with its tool into the engine's own 0.1 mm stock starting from a given initial stock, and writes
   it with the usual .json sidecar. TWO call sites:
   (i) rough -> finish/rest: engine.cli rough --stock-out writes THIS replay (not the coarse planning stock);
   (ii) finish -> rest: engine.cli finish writes its own replayed after-finish stock; the connector passes THAT to the rest pass
        (--rest-from) instead of zmap's stock_after_finish.npy.
   The connector no longer passes ANY zmap stock to the engine; zmap still writes --stock-out for judging and reports.
2. Report compute time of the replay on TB and on CF (rough-only CF timing: one engine.cli rough of samples/core_front_setup.step
   with --stock-out, ENGINE_WORKERS 4, through the small lane only if under 10 min, else report the TB time and estimate CF).
3. Rough/finish/rest programs byte-identical (they must not change); only handed-down stock files change.
RED TESTS (write first, run on the UNCHANGED code, paste the numbers - each must FAIL there):
 (a) test_rrstock_rough_handoff_not_below_judge (engine/test_finish.py or test_engine.py): rough the test block (fixtures
     out/test_block*, manifest-pinned) with --stock-out, judge the SAME emitted rough program with verify.zmap --stock-out on the
     0.1 mm part grid; at every judge cell with standing stock (above the part): engine handoff stock >= judge stock - TOL. Use
     TOL = 0.1 unless you find a smaller honest value; state it.
 (b) test_rrstock_finish_handoff_matches_judge: the engine's replayed after-finish stock vs zmap's --stock-out of the same finish
     on a small scene: |engine - judge| <= TOL at every cell with standing stock.
 (c) connector/test_connector.py::TestZg1connStockBottomE2E::test_tb_rest_chain_checks_stock_bottom (TB ZB entry plunge).
AT-RISK (must stay green; run ALL, paste exit codes): the whole engine/test_finish.py, engine/test_entry_depth.py, test_engine.py
tests test_rough_testblock_r2, test_rough_testblock_r4, test_dt1_synthetic_rough_twice_identical, test_rr1b_rest_rough_synth_pocket,
test_rr1c3_bay_deep_groove_top_down, test_rra2_deep_top_scope, test_rra3_straight_descent_scope,
test_rr1c5c_closed_pocket_bore_entry_no_deep_axial, test_stock_out_roundtrip (test_finish), verify/test_zmap.py -k "zg1 or ze2b",
connector/test_tlg1.py, connector/test_connector.py -k "rest or stock".
## engine/RRSTOCK_RESULTS.md: the change (file:line), line count, red tests before/after numbers, TOL, compute times, PASTED exit codes,
git diff --numstat. Then stop. (Supervisor verifies from committed code: mutations (handoff reverted to coarse stock; rest
--rest-from back to zmap) -> red tests fail by measured mm; full suites; CF chain.)
