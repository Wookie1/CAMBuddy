# Task PANELCANCEL: read a panel/STEVE "cancel" while a job runs. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: no Core Front and no real engine run at all in this task (fake spawns only). NOTHING longer than 10 minutes goes on
the small lane (slot_m4.sh). Do NOT run the whole connector/test_connector.py (~25 min); the supervisor runs full suites.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/timeouts. Add NEW tests only, in a NEW file
connector/test_panelcancel.py.
SCOPE (hard): edit ONLY connector/connector.py (+ the new test file + a results file). Do NOT edit connector/runner.py (another
thread owns it), connector/mock_steve.py, catalog.py, panel/, engine/, verify/, menubar/ or opencode.json. If mock_steve lacks
something, build it in the test file.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; install NOTHING; do NOT touch
~/.stevecam, ~/Library/LaunchAgents, launchctl or the running connector; stop only processes you started, by exact PID (never
pkill/killall). Never print or store keys, tokens or pairing codes.
SCRATCH: /Users/James/ai-sandbox/stevecam-pc/scratch/ only - never /tmp. Tests use pytest tmp_path.
RESULTS: create connector/PANELCANCEL_RESULTS.md EARLY and keep it current (command, exit code, output, `date`).
FRESH session, TIME BUDGET 60 min, HARD STOP 90 min (`date` at start). Worktree /Users/James/ai-sandbox/stevecam-pc, branch
panel-cancel at the commit carrying this brief (main 2da9125 + brief).
Small tests ONLY via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor, from main 2da9125)
- run_forever (connector.py:720-756) polls client.messages and calls handle_message for each message in the SAME thread.
  handle_message -> _run_job (:558-702) runs the whole job synchronously, so the loop polls nothing until the job ends.
- A "cancel" message is handled at :328-331 (self.running.cancel() if env["run"] == self.current_run) - but it is only read
  after the job ended, so today it never cancels anything. NOTE: that branch runs BEFORE the `ok` check of verify_envelope,
  i.e. an unsigned/forged cancel is acted on. Fix that too: a cancel must pass verify_envelope (mock_steve.enqueue_cancel signs
  it properly; its envelope "id" is None and "run" names the target run).
- EngineRun.cancel() (runner.py:478) is the existing cancel entry point; _spawn raises runner.Cancelled; _run_job's
  `except Cancelled` (:678-683) reports "cancelled" then end_run(). Keep using exactly that path.
- Today's behaviour while a job runs (keep it): any further job or tool-action message (including view.load) waits and runs
  AFTER the current job, in arrival order, one at a time; a job id already in the ledger is never acted on twice
  (_remember_run is called before the job starts).
- SIGTERM: connector.stop (:715-718) sets _stop and calls running.cancel(); the loop ends; main() releases the pidfile; exit 0
  (test_pidstatus.py::test_sigterm_exits_zero).
- emit_state/_write_status (:167-183, :287-299) use one fixed tmp file status.json.tmp and self._last_event; on_progress
  (:581-589) and end_run call them plus client.report_run.

## Items
1. Run jobs AND tool actions on ONE long-lived worker thread fed by a FIFO queue (queue.Queue), in arrival order, one at a
   time - exactly today's ordering. The message loop keeps polling while the worker is busy and handles ONLY "cancel" itself.
   Keep the ledger/nonce bookkeeping where it is (before queueing), so a job is never acted on twice.
2. Cancel: verify_envelope must pass (any failure: ignore silently, no report). If env["run"] equals the ACTIVE job's run id,
   call that EngineRun's cancel(). A cancel for any other id (queued, finished, unknown) is ignored (no state change, no
   report). Do NOT report "cancelled" from the loop - the worker's existing `except Cancelled` path reports it once and runs
   end_run(), so status.json ends "idle".
3. One threading.Lock (or RLock) serializes _write_status, the _last_event check/update + post_event in emit_state, and
   client.report_run calls made by the worker vs the loop; status.json must still be written atomically.
4. SIGTERM / stop(): cancel the active job, stop the worker (drain nothing new), JOIN the worker (bounded, e.g. 60 s), then
   exit 0 with the pidfile released and status "off". test_sigterm_exits_zero must stay green.
## Tests (NEW connector/test_panelcancel.py; use mock_steve.MockSteve like test_pidstatus.py does, and monkeypatch
   runner.EngineRun._spawn / run methods with a fake that sleeps in small steps and checks self.cancelled, OR spawns a real
   `sleep 60` child via the real _spawn so killpg is exercised - say which):
 a. test_cancel_mid_job: start a job, wait for "running", enqueue_cancel(that run); assert terminal state "cancelled" within
    N s (measure and state N; job would otherwise run >= 30 s), the child PID is gone (if a real child), status.json "idle".
    MEASURE ON MAIN: run the same test against an unmodified copy of connector.py (scratch copy of main's file, or
    `git show 2da9125:connector/connector.py`) and record that it fails (job not cancelled within N s). Paste both results.
 b. test_cancel_other_id_ignored: cancel for a different/queued run id -> active job completes "succeeded".
 c. test_forged_cancel_ignored: a cancel with a bad signature (mutate the sig) -> job completes "succeeded".
 d. test_second_job_waits: a second job enqueued while the first runs is "received" only after the first is terminal and then
    completes (order of terminal states == enqueue order).
 e. MUTATION M1 (scratch copy, never the real file): remove the loop's cancel dispatch -> (a) red. Record the measured result.
AT-RISK (must stay green; paste exit codes): connector/test_pidstatus.py (all), connector/test_show3d.py,
connector/test_view3d.py, and from test_connector.py ONLY the tests whose names contain "envelope", "nonce", "reject" or
"ledger" (select with -k; list what ran).
## Results: per-item what you changed (+ line counts), each test's pass/fail with times, N measured, main-vs-branch result for
(a), M1 result. Then stop.
