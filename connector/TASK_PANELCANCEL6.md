# Task PANELCANCEL6: close the cancel window between dequeue and `self.running = engine`. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: no Core Front and no real engine run (fake runs only). NOTHING longer than 10 minutes goes on the small lane
(slot_m4.sh). Do NOT run the whole connector/test_connector.py (~25 min); the supervisor runs full suites.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/timeouts. Add NEW tests only (append to
connector/test_panelcancel.py).
SCOPE (hard): edit ONLY connector/connector.py (+ appended tests + a "## PANELCANCEL6" results section in
connector/PANELCANCEL_RESULTS.md). Do NOT edit runner.py, mock_steve.py, errors.py, catalog.py, panel/, engine/, verify/,
menubar/ or opencode.json.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; install NOTHING; do NOT run
install_agent.sh or any launchctl command; do NOT touch ~/.stevecam, ~/Library/LaunchAgents or the running connector; stop only
processes you started, by exact PID (never pkill/killall). Never print or store keys, tokens or pairing codes.
SCRATCH: /Users/James/ai-sandbox/stevecam-pc/scratch/ only - never /tmp. Tests use pytest tmp_path.
RESULTS: append "## PANELCANCEL6" to connector/PANELCANCEL_RESULTS.md EARLY and keep it current (command, exit code, `date`).
FRESH session, TIME BUDGET 35 min, HARD STOP 50 min. Worktree /Users/James/ai-sandbox/stevecam-pc, branch panel-cancel at the
commit carrying this brief (23ac6a9 = PANELCANCEL..5 work, + this brief).
Small tests ONLY via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- The worker takes an item off self._queue, then _run_job sets self.current_run (:736), calls emit_state("busy") and
  report("received") (two HTTP calls), creates EngineRun and only then sets self.running (:754-755). The loop's cancel branch
  acts on the active run only when `self.running and self.current_run == target`; otherwise it looks in the queue. A cancel
  arriving after the worker's get() and before :755 finds neither, and is ignored: the run then executes in full. Window =
  tens to hundreds of ms (two HTTP round trips), not microseconds.
## Item
1. One small lock (e.g. self._cancel_lock; or reuse an existing one if it is safe - say which) makes these atomic:
   - loop, verified cancel: if the target is the active run with an engine -> engine.cancel(); elif it is queued -> the
     PANELCANCEL4 drop (unchanged); else -> add the id to a BOUNDED pending-cancel collection (e.g. OrderedDict trimmed to
     the newest 64 ids). Unknown ids just sit there harmlessly.
   - worker, in _run_job right where self.running = engine is set: set it AND test-and-remove run_id in the pending
     collection under the same lock; if it was pending, call engine.cancel() at once (its cancelled flag makes the first
     _spawn raise Cancelled; the existing `except Cancelled` path reports "cancelled" once and end_run() leaves status
     "idle"). No engine subprocess may start for such a run.
   Keep the PANELCANCEL4 _dropped double-cancel guard. Tool actions: out of scope (say so).
## Tests (append to connector/test_panelcancel.py)
 a. test_cancel_in_dequeue_window: a launcher whose fake EngineRun.__init__ sleeps ~2 s (this widens exactly the window
    between current_run and self.running) and whose fake run counts calls; start a job, wait for "received", enqueue_cancel
    (that run) during the sleep. Assert terminal "cancelled", the fake run was never called (or no spawn happened), status
    "idle". State how you made sure the cancel landed inside the window.
 b. MUTATION M5 (scratch copy only): skip the pending check in _run_job -> (a) red. Record the result.
AT-RISK (must stay green; paste exit codes): connector/test_panelcancel.py (all), connector/test_pidstatus.py (all),
connector/test_show3d.py.
## Results: what changed (+ line counts), (a) result and time, M5 measured. Then stop.
