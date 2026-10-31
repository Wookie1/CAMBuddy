# Task PANELCANCEL3: SIGTERM handler only sets an Event; cancel + join happen outside signal context. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: no Core Front and no real engine run (fake spawns only). NOTHING longer than 10 minutes goes on the small lane
(slot_m4.sh). Do NOT run the whole connector/test_connector.py (~25 min); the supervisor runs full suites.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/timeouts (including the PANELCANCEL tests in
connector/test_panelcancel.py). Add NEW tests only (append to connector/test_panelcancel.py).
SCOPE (hard): edit ONLY connector/connector.py (+ appended tests + a "## PANELCANCEL3" results section). Do NOT edit
connector/runner.py (another thread owns it; its non-reentrant self._lock stays as it is), mock_steve.py, catalog.py, panel/,
engine/, verify/, menubar/ or opencode.json.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; install NOTHING; do NOT touch
~/.stevecam, ~/Library/LaunchAgents, launchctl or the running connector; stop only processes you started, by exact PID (never
pkill/killall). Never print or store keys, tokens or pairing codes.
SCRATCH: /Users/James/ai-sandbox/stevecam-pc/scratch/ only - never /tmp. Tests use pytest tmp_path.
RESULTS: append "## PANELCANCEL3" to connector/PANELCANCEL_RESULTS.md EARLY and keep it current (command, exit code, `date`).
FRESH session, TIME BUDGET 45 min, HARD STOP 70 min. Worktree /Users/James/ai-sandbox/stevecam-pc, branch panel-cancel at the
commit carrying this brief (6e9c2ca = the PANELCANCEL work, + this brief).
Small tests ONLY via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- runner.EngineRun.cancel() takes self._lock (a non-reentrant threading.Lock); _spawn holds the same lock around Popen.
- A Python signal handler runs on the MAIN thread between bytecodes. If the handler calls cancel() (directly or via stop())
  while the main thread is inside that `with self._lock:` block, it deadlocks; and the other thread's P3C will make cancel()
  do up to ~5 s of process teardown, which must never run in signal context.
## Item
1. The SIGTERM/SIGINT handler ONLY sets a threading.Event (no cancel, no join, no I/O, no status write). The message loop
   (and a small watcher thread if the loop can be blocked in a long-poll - say which you chose and why) sees the event and
   then, outside signal context: cancels the active job, stops/joins the worker (bounded), writes status "off", returns so
   main() releases the pidfile and exits 0. Bound the long-poll wait so shutdown does not wait a full poll_wait if avoidable,
   or state the measured worst case.
2. Queued jobs at shutdown (supervisor review of 6e9c2ca): handle_message calls _remember_run before queueing and the loop
   saves the cursor past the message, but _worker_loop exits on _stop WITHOUT running what is still queued - those runs are
   then never run, never reported and never redelivered (on main an unprocessed message was neither remembered nor past the
   saved cursor, so it came back after a restart). Fix in connector.py: at shutdown, after the active job is cancelled and
   the worker has stopped, every job/tool item still in self._queue gets ONE report "rejected" with a new error code
   "connector_stopping" (errors.make_error; message "connector shut down before this run started") via _safe_reject-style
   reporting, so STEVE sees a terminal state. Nothing still queued is executed.
3. test_cancel_mid_job_fails_on_main_connector (supervisor-requested change to this NOT-yet-merged test, new in
   the previous round): it permanently asserts 2da9125's broken behaviour and costs ~12 s per run. Make it skip unless
   PANELCANCEL_MEASURE_MAIN=1 is set (pytest.mark.skipif on that env var); do not change its body or assertions. Record one
   run with the env var set (it must still pass, i.e. main still fails to cancel).
## Tests (append to connector/test_panelcancel.py)
 a. test_sigterm_while_spawn_holds_lock: an in-process or subprocess connector whose fake EngineRun._spawn takes the run's
    self._lock and holds it (e.g. sleeps 3 s inside it) on the MAIN thread path the handler can interrupt - or the closest
    honest equivalent with the worker design (explain it); deliver SIGTERM while the lock is held; assert exit 0 (or loop
    return) within N s (measure; state N), pidfile removed, status "off", no hang.
 c. test_queued_job_rejected_on_shutdown: job A (long fake) running, job B enqueued behind it; SIGTERM; assert A ends
    "cancelled", B ends "rejected" with code "connector_stopping" (B never reaches "running"), exit 0, pidfile removed.
 b. MUTATION M2 (scratch copy only): make the handler call cancel() directly -> (a) hangs or times out. Record the measured
    result (test timeout, never an infinite wait: use a hard timeout in the test).
AT-RISK (must stay green; paste exit codes): connector/test_panelcancel.py (all), connector/test_pidstatus.py (all, incl.
test_sigterm_exits_zero), connector/test_show3d.py.
## Results: what changed (+ line counts), (a) pass time and N, (c) result, M2 measured, item 3 run with the env var. Then stop.
