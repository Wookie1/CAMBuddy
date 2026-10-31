TASK SP-P3C-2: failure propagation, cancel of both chains, atomic outputs (connector/runner.py only).
Round 2 of 2, on top of SP-P3C-1 (d3e2049): run_slope_split_finish already runs an ENGINE chain (calling thread) and a
JUDGE chain (judge_thread) with ev_rough/ev_finish/ev_rest/engine_done/abort Events, one locked progress sink and
steps.log. Read connector/runner.py ~478-560 (cancel/_spawn) and ~1085-1600 (the two chains) with sed; never print
G-code. Do NOT touch connector/connector.py, engine/, verify/ or any existing test (incl. connector/test_spp3c.py,
which must keep passing; add new tests in a NEW file).
Facts:
- _spawn/cancel track ONE process (self._proc) today; with two chains the slot is overwritten, so cancel() kills only
  the later process group. Every _spawn uses start_new_session=True, so each step is its own process group (zmap's
  fork Pool and the engine's island pool share their step's group; killpg reaches them).
- SIGTERM to the connector calls running.cancel() from the MAIN thread only (connector.py:715-721); the judge thread
  never sees signals, so it relies on cancel() killing its process group.
- connector.py end_run() sets idle after run_slope_split_finish returns or raises: BOTH chains must be finished
  (joined, no live child) before this function returns or raises.
- Today (serial): a failed rough/finish gate raises before any rest-pass engine work; clcheck failures raise on the
  engine chain; _spawn raises _engine_error on rc != 0; tests check error codes (EngineError.code / where).
Do:
(1) Process tracking + cancel: replace self._proc with a set of live Popen objects under self._lock (add on start,
  remove after wait). cancel(): set self.cancelled, then for every live proc os.killpg(os.getpgid(pid), SIGTERM);
  after up to 5 s, SIGKILL any group still alive. Keep the existing ProcessLookupError/PermissionError fallbacks.
  run() and run_check_program keep working unchanged (one proc at a time).
(2) Failure propagation in run_slope_split_finish, with the FIRST error winning:
  - record the first failure (exception object + which chain) under a lock; later failures are ignored;
  - a judge failure (non-zero exit, gate check raising, stale hf01) cancels the engine chain promptly: kill the
    engine's running process group(s) and make the engine chain stop before its next step (check a shared stop flag
    before each step, raising Cancelled internally);
  - an engine failure cancels the judge chain the same way (kill its running zmap/heightfield group, set abort and
    every Event so it cannot wait);
  - on Cancelled from cancel()/SIGTERM: kill every live group of both chains;
  - in every case: join the judge thread, make sure no tracked proc is alive, THEN raise. Raise the FIRST error
    unchanged (same type, message, code, where). If the run was cancelled by cancel(), raise Cancelled. An internal
    stop caused by the other chain's failure must never be reported in place of the first error.
(3) Atomic outputs: confirm (do not assume) that nothing the panel or connector reads DURING a run reads a file a
  judge is still writing (view.load / Show 3D of earlier runs read <home>/runs/<id>/ only after the run ends; the
  results card reads after the final state; status.json is written by connector.py). Report file:line evidence in
  the results file. Only if something can race, write it via a temp name + os.replace in the runner. No zmap.py
  edits.
Tests (new file connector/test_spp3c2.py):
 - judge failure stops the engine: a fake long engine step (a real `python -c "import time; time.sleep(60)"` child)
   is killed within 2 s of a judge failing; the run raises the JUDGE's EngineError (same code), and no rest-pass
   engine step starts after a failed rough/finish gate.
 - engine failure stops the judges: a long fake zmap child is killed within 2 s; the run raises the ENGINE error.
 - first error wins: both chains fail, the first one is reported with its code.
 - cancel with no orphans: in BOTH chains a real child that spawns a grandchild (both sleep 60 s); cancel() from
   another thread, and separately a simulated SIGTERM path (call cancel() from the main thread while the judge
   thread runs): every child and grandchild pid is gone within 6 s (os.kill(pid, 0) raises), the run raises
   Cancelled, and the judge thread is joined.
 - busy: the function never returns or raises while the judge thread is alive or a tracked proc is alive.
 - mutation (scratch, then revert): make cancel() kill only one tracked proc; the no-orphans test must fail. Report.
Rules: FOREGROUND RULE (run every command in the foreground and wait). Targeted tests only: your new file, plus
connector/test_spp3c.py and connector/test_connector.py (at risk). The supervisor runs the full suites, the panel
tests and every Core Front job. Running any Core Front job voids the round. Write connector/SPP3C2_RESULTS.md early and
append after every test run (exit codes + git diff --numstat). Stage nothing, commit nothing. No destructive git. Do
not edit any existing test; if a requirement conflicts with one, stop and report. Continue from your plan; don't stop
before the tests exist and have run. Hard 2 h cap.
