TASK SP-P3C: run the zmap judges as their own chain beside the engine chain (connector/runner.py only; same verdicts).
Scope: EngineRun.run_slope_split_finish (connector/runner.py ~1008-1530) plus _spawn/cancel (~478-553). Read those line
ranges with sed; never print G-code. Do NOT touch connector/connector.py, engine/, verify/ or any existing test.
Facts (verified on main 2da9125):
- Engine steps read only ENGINE stocks: finish uses --stock-from rough_stock_out (~1203); rest uses --rest-from
  stock_fin_engine and --stock-from rough_stock_out (~1336-1339). No engine step reads a zmap output.
- The zmap heightfield hf01 (freecadcmd verify/heightfield.py, ~1107-1120, step 2 today) is read only by the judges, the
  rest-stock sidecar merge (~1314) and _build_view (~1495). The engine rough uses prep["hf"], not hf01.
- Judges today, in order: zmap rough (~1241, --stock-out stock_after_rough.npy), zmap finish (~1267, --stock-in that
  stock, --stock-out stock_after_finish.npy), zmap rest (~1402, --stock-in stock_after_finish). Gate checks run via
  _check_zmap_gates. check.json, the view (_build_view, _build_view_images) and the result are built after all steps.
- connector.py writes status.json from the run's lifetime: "working" lasts until run_slope_split_finish returns.
- _spawn/cancel track ONE process (self._proc) and kill its process group (start_new_session=True + killpg).
Do:
(1) Two chains inside run_slope_split_finish:
  ENGINE chain = today's order minus the zmap judges and minus hf01: prepare, rough, tessellate, finish, post,
  probe_clcheck, [rest finish, post_rest, clcheck_rest].
  JUDGE chain (a thread) = hf01 (+ require_fresh), then zmap rough, zmap finish, [rest sidecar merge, zmap rest].
  Each judge starts only when its input program exists (rough.nc after the rough step; finish.nc after post; rest.nc
  after clcheck_rest) AND the previous judge has finished. Signal readiness with threading.Event set by the engine
  chain right after the producing step returns successfully. Argv for every step stays byte-identical to today,
  except --jobs (item 4).
  Return only after BOTH chains finish. check.json, the view, the images and the result are built after both, exactly
  as today, from the same files. The result and check.json content must be identical to the serial runner's.
(2) Failure and cancel:
  - A judge failure (non-zero exit, or _check_zmap_gates raising) ends the job promptly: cancel the engine chain's
    running process group and raise the SAME exception today's code would raise for that judge.
  - An engine failure cancels the judge chain the same way and raises the engine error as today.
  - cancel() (and SIGTERM to the connector) kills EVERY running process group of both chains, zmap pool workers
    included. Track all live Popen objects in a set under self._lock (replace the single self._proc); kill each with
    os.killpg(os.getpgid(pid), SIGTERM), then SIGKILL after 5 s if still alive. No orphans.
  - If both fail, report the one that failed first.
(3) Progress: a single on_progress sink guarded by a lock, with monotone values. While the engine chain runs, its
  stage fractions drive progress as today. When the engine chain has finished and judges remain, the message is
  exactly CHECKING_FMT % (n, total), where CHECKING_FMT = "checking (%d of %d)" is a module constant; n is the judge now
  running (1-based), total = 2 (no rest) or 3 (rest). Define the text in one place only.
(4) Resources: ZMAP_JOBS stays 12 for a judge that starts while the engine chain has finished. Add module constant
  ZMAP_JOBS_OVERLAP = 6 for a judge that starts while the engine chain is still running. Choose at judge start.
(5) Atomic outputs: check whether anything the panel can read while a run is in progress (view.load / Show 3D of an
  earlier run, results card, last_runs) reads a file a judge is still writing. If something does, write it to a
  temp name and os.replace it. Report what you found either way. Do not edit verify/zmap.py; wrap it in the runner
  if needed.
Tests (new file connector/test_spp3c.py; the existing connector tests must still pass unchanged):
 - ordering: with fake engine and zmap steps (patch EngineRun._spawn to record start/end times and simulate durations),
   each judge starts after its program step and after the previous judge; the run returns only after both chains.
 - failure propagation both ways: a failing judge cancels a long engine step promptly (< 2 s) and the run raises that
   judge's error; a failing engine step cancels a running judge and the run raises the engine error.
 - cancel with no orphans: real subprocesses (a python child that spawns a grandchild and sleeps 60 s) in both
   chains; cancel() leaves no process from either group alive within 6 s (check with os.kill(pid, 0) on every pid).
 - progress text: after the engine chain ends, the messages are CHECKING_FMT % (n, total) in order.
 - jobs: --jobs is ZMAP_JOBS_OVERLAP for a judge started while the engine runs, and ZMAP_JOBS otherwise.
 - identical outputs: in a fake run with canned step outputs, the check.json and result are byte-identical to the
   serial runner's (run the pre-change runner's code path from a copy kept in the test as the reference).
 - mutation (scratch, then revert): drop the "previous judge finished" wait; the ordering test must fail. Report it.
Rules: FOREGROUND RULE (run every command in the foreground and wait). Targeted tests only (your new test plus
connector/test_connector.py, which is at risk); the supervisor runs the full suites, the panel tests and every Core
Front job. Running any Core Front job voids the round. Write connector/SPP3C_RESULTS.md early and append after every
test run (exit codes + git diff --numstat). Stage nothing, commit nothing. No destructive git. Do not edit any existing
test; if a requirement conflicts with one, stop and report. Continue from your plan; don't stop before the tests exist
and have run. Hard 2 h cap.
