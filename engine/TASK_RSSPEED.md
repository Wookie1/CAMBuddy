# Task RS-SPEED: make entry_depth.replay_stock fast, output bit-identical. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough or a Core Front replay. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh). If a run would
exceed 10 min, don't start it; write what you would have run into the results file. The supervisor times the CF replays and checks
their equality on the CF lane.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT edit verify/
or opencode.json; engine code NEVER imports zmap/verify (tests may); numpy only - install NOTHING, no new packages, no numba/
cython/C; emitted PROGRAMS must not change, and replay_stock's output array must be BIT-IDENTICAL (np.array_equal, same dtype and
shape, same x0/y0/cell sidecar) to today's for every input.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-rss/scratch/ - never /tmp.
RESULTS: create engine/RSSPEED_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and
what it printed.
CONTINUE: continue from your plan; don't stop before every red test exists and has run on the UNCHANGED code, and every test
below has run.
Edit ONLY engine/entry_depth.py (replay_stock and any new private helper beside it). Callers (engine/cli.py) stay as they are.
BUDGET: <= 60 changed non-test lines vs f597018 (`git diff --numstat f597018 -- engine connector ':!*test_*' ':!*TASK_*'`);
STOP and report at ~90. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-rss, branch
rs-speed at the commit carrying this brief (= main f597018 + brief).
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Engine test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_rsspeed as t; t.<test_name>()"
Connector/verify test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- replay_stock (engine/entry_depth.py ~334) replays an emitted move list into the engine's 0.1 mm stock. It loops in Python
  over every G1 and over every sample (np.linspace, pitch <= fine/4), and per sample builds the tool disk window with
  hypot/sqrt and np.minimum's it into L. The CF rough replay (377,327 moves) takes 514.9 s. TARGET: <= 120 s for it.
- Every stamp is an elementwise np.minimum into L, which is exact and order-independent: the result depends only on the SET
  of (window, value) pairs, so batching samples is safe as long as each value is computed by the SAME floating-point
  expression (same operands, same operation order, same np.linspace call) as today. Different arithmetic (e.g. rewriting
  gx via cell offsets, caching a kernel computed at a different sx, float32) is NOT bit-identical - check, don't assume.
- Users: engine/cli.py (rough --stock-out ~266, finish --stock-out ~338, rest-rough --stock-out ~766). Tests that pin it:
  engine/test_finish.py test_rrstock_replay_matches_analytic_stamp, test_rrstock_rough_handoff_not_below_judge,
  test_rrstock_finish_handoff_matches_judge (the two-sided handoff tests), engine/test_rrstock2.py.
## Items
1. Make replay_stock faster (vectorize/batch the per-sample work in numpy; keep the function's signature, return value,
   sidecar and its "replay_stock: N moves -> path in T s" print).
RED TESTS (new file engine/test_rsspeed.py; write first, run on the UNCHANGED code, paste numbers):
 (a) test_rsspeed_matches_reference: copy TODAY's replay_stock body verbatim into the test as _replay_stock_reference (the
     reference stays in the test, never edited). Run both on: a fixed synthetic program (seeded random G0/G1 moves incl. pure
     plunges, zero-length moves, missing-axis modal moves, long diagonals) for flat (corner 0), bull and ball tools, both with
     box=/top_z= and with init= (same-pitch and a coarser-pitch init); plus the test_block rough program and one test_block
     finish program if one can be generated in < 2 min. np.array_equal on every array and equal x0/y0/cell. On the unchanged
     code this passes trivially - state that; its job is to guard the new code.
 (b) test_rsspeed_timing: the same seeded synthetic program sized so TODAY's code takes ~20-40 s on the M4 (paste the time);
     assert the new replay_stock is >= 4x faster than _replay_stock_reference on it (measure both in the test). Must FAIL on
     the unchanged code (paste the ratio).
AT-RISK (must stay green; run ALL, paste exit codes): engine/test_rrstock2.py (both tests), engine/test_finish.py
test_rrstock_replay_matches_analytic_stamp, test_rrstock_rough_handoff_not_below_judge, test_rrstock_finish_handoff_matches_judge,
connector/test_rrstock2.py, engine/test_entry_depth.py. The TB E2E (11 min) is the supervisor's.
## engine/RSSPEED_RESULTS.md: change (file:line), line count, red tests before/after with pasted times/ratios, PASTED exit codes,
git diff --numstat. Then stop.
(Supervisor verifies from committed code: the reference test; mutations (one changed float expression; one dropped sample)
-> the equality test fails; CF rough, rest-rough and finish replays np.array_equal to the chain9 files with the new time; the
TB E2E; full suites.)
