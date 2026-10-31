TASK SP-P3C-1: run the zmap judges as their own chain beside the engine chain (connector/runner.py only; same verdicts).
Round 1 of 2. This round: the two chains, progress text, judge --jobs, and per-step timestamps. Failure/cancel
hardening and atomic outputs are round 2: in THIS round a failure in either chain may simply re-raise after both
chains are joined.
Scope: EngineRun.run_slope_split_finish (connector/runner.py ~1008-1530) plus _spawn (~495-553). Read those line
ranges with sed; never print G-code. Do NOT touch connector/connector.py, engine/, verify/ or any existing test.
Facts (verified on main 2da9125):
- Engine steps read only ENGINE stocks: finish uses --stock-from rough_stock_out (~1203); rest uses --rest-from
  stock_fin_engine and --stock-from rough_stock_out (~1336-1339). No engine step reads a zmap output.
- The zmap heightfield hf01 (freecadcmd verify/heightfield.py, ~1107-1120, step 2 today) is read only by the judges,
  the rest-stock sidecar merge (~1314) and _build_view (~1495). The engine rough uses prep["hf"], not hf01.
- Judges today, in order: zmap rough (~1241, --stock-out stock_after_rough.npy), zmap finish (~1267, --stock-in that
  stock, --stock-out stock_after_finish.npy), zmap rest (~1402, --stock-in stock_after_finish). Gate checks run via
  _check_zmap_gates. check.json, the view (_build_view, _build_view_images) and the result are built after all steps.
- connector.py writes status.json from the run's lifetime: "working" lasts until run_slope_split_finish returns.
Do:
(1) Two chains inside run_slope_split_finish:
  ENGINE chain (the calling thread) = today's order minus the zmap judges and minus hf01: prepare, rough, tessellate,
  finish, post, probe_clcheck, [rest finish, post_rest, clcheck_rest].
  JUDGE chain (one threading.Thread) = hf01 (+ require_fresh), then zmap rough, zmap finish, [rest sidecar merge,
  zmap rest]. Each judge starts only when its input program exists (rough.nc after the rough step; finish.nc after
  post; rest.nc after clcheck_rest) AND the previous judge has finished. Signal readiness with threading.Event set by
  the engine chain right after the producing step returns successfully. The judge thread also needs `stock` and the
  tool data the judges use today; compute them before starting the thread. Argv for every step stays byte-identical
  to today, except --jobs (item 3).
  An exception raised in the judge thread must be CAPTURED (stored) and RE-RAISED in the main thread after join; it
  must never be swallowed by the thread. If the engine chain raises, set every pending Event so the judge thread can
  exit (it must not wait forever), join it, then re-raise the engine error.
  Return only after BOTH chains finish. check.json, the view, the images and the result are built after both, exactly
  as today, from the same files. The result and check.json content must be identical to the serial runner's.
(2) Progress: route every on_progress call through ONE sink guarded by a threading.Lock; values never decrease. The
  judge thread must never call on_progress except through that locked sink. While the engine chain runs, its stage
  fractions drive progress as today. When the engine chain has finished and judges remain, the message is exactly
  CHECKING_FMT % (n, total), with CHECKING_FMT = "checking (%d of %d)" a module constant (the text defined in one place
  only); n = the judge now running (1-based), total = 2 (no rest) or 3 (rest).
(3) Resources: ZMAP_JOBS stays 12 for a judge that starts after the engine chain has finished. Add module constant
  ZMAP_JOBS_OVERLAP = 6 for a judge that starts while the engine chain is still running. Choose at judge start.
(4) Timestamps: append one line per step to <work>/steps.log: "<step> <start epoch s> <end epoch s> <chain>"
  (chain = engine|judge), written under the same lock, for every step of both chains (needed for the CF proof).
Tests (new file connector/test_spp3c.py; the existing connector tests must still pass unchanged):
 - ordering: with fake steps (patch EngineRun._spawn to record start/end and simulate durations), each judge starts
   after its program step and after the previous judge; the run returns only after both chains; hf01 starts before
   the rough step ends.
 - judge exception: a judge raising is re-raised in the main thread (the same exception type and message).
 - progress text: after the engine chain ends, the messages are CHECKING_FMT % (n, total) in order; values monotone.
 - jobs: --jobs is ZMAP_JOBS_OVERLAP for a judge started while the engine runs, and ZMAP_JOBS otherwise.
 - identical outputs: in a fake run with canned step outputs, check.json and the result are byte-identical to the
   serial runner's (keep the pre-change code path as a reference copy in the test).
 - steps.log: one line per step, both chains.
 - mutation (scratch, then revert): drop the "previous judge finished" wait; the ordering test must fail. Report it.
Rules: FOREGROUND RULE (run every command in the foreground and wait). Targeted tests only (your new test plus
connector/test_connector.py, which is at risk); the supervisor runs the full suites, the panel tests and every Core
Front job. Running any Core Front job voids the round. Write connector/SPP3C1_RESULTS.md early and append after every
test run (exit codes + git diff --numstat). Stage nothing, commit nothing. No destructive git. Do not edit any existing
test; if a requirement conflicts with one, stop and report. Continue from your plan; don't stop before the tests exist
and have run. Hard 2 h cap.
