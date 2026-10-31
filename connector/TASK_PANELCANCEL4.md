# Task PANELCANCEL4: a verified cancel for a QUEUED run drops it (it never runs). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: no Core Front and no real engine run (fake spawns only). NOTHING longer than 10 minutes goes on the small lane
(slot_m4.sh). Do NOT run the whole connector/test_connector.py (~25 min); the supervisor runs full suites.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/timeouts - EXCEPT exactly the one named in item 2
below (coordinator-approved). Add NEW tests only (append to connector/test_panelcancel.py).
SCOPE (hard): edit ONLY connector/connector.py, connector/errors.py (item 3 only), the codes table between
<!-- codes:begin --> and <!-- codes:end --> in docs/agent_guide.md (item 3 only), + appended tests + a "## PANELCANCEL4"
results section. Do NOT edit
connector/runner.py, mock_steve.py, catalog.py, panel/, engine/, verify/, menubar/ or opencode.json.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; install NOTHING; do NOT touch
~/.stevecam, ~/Library/LaunchAgents, launchctl or the running connector; stop only processes you started, by exact PID (never
pkill/killall). Never print or store keys, tokens or pairing codes.
SCRATCH: /Users/James/ai-sandbox/stevecam-pc/scratch/ only - never /tmp. Tests use pytest tmp_path.
RESULTS: append "## PANELCANCEL4" to connector/PANELCANCEL_RESULTS.md EARLY and keep it current (command, exit code, `date`).
FRESH session, TIME BUDGET 40 min, HARD STOP 60 min. Worktree /Users/James/ai-sandbox/stevecam-pc, branch panel-cancel at the
commit carrying this brief (7f89867 = PANELCANCEL + PANELCANCEL3 work, + this brief).
Small tests ONLY via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- Jobs and tool actions wait in self._queue (queue.Queue of (kind, run_id, env, action)) for the one FIFO worker; the ledger
  and nonce are recorded BEFORE queueing (a redelivered message is never acted on twice).
- Today handle_message's verified "cancel" only acts on the ACTIVE run (self.current_run); a cancel for a queued id is ignored,
  so that run still executes later. The coordinator decided: a person who presses Cancel expects it never to run.
## Item
1. A verified cancel (verify_envelope ok - unchanged) whose env["run"] matches a QUEUED item removes that item from the queue
   (safely vs the worker's get(), e.g. under self._queue.mutex on self._queue.queue, or your own lock - say which) and reports
   it ONCE as "received" then "cancelled" (message "cancelled before it started", via the locked _report). STEVE's state
   machine (mirrored in mock_steve.NEXT_OK) only allows "received"/"rejected" as a run's first report, and "cancelled" only
   after "received" - a bare first "cancelled" is refused. Its engine/tool action never
   starts. The ledger/nonce stay recorded. Cancel for the ACTIVE run: unchanged. Cancel for an unknown/finished id: still
   ignored (no report). A second cancel for the same already-dropped id: ignored (no second report).
2. The ONE allowed test change (coordinator decision of 2026-10-31 reverses what it asserts; the test is new on this branch,
   never merged): test_panelcancel.py::test_cancel_other_id_ignored enqueues cancel(8002) for a QUEUED run and asserts 8002
   later "succeeded" with no "cancelled" (its lines ~288, ~292-293). Change ONLY that queued-id part so it asserts the new
   behaviour (8002 states exactly ["received", "cancelled"], never "running"); keep its unknown-id (99999) part and its active-job (8001)
   assertions exactly as they are; keep the test name. Paste the before/after lines in the results.
3. Register the code PANELCANCEL3 introduced: add "connector_stopping" to errors.CODES (kind "error", next_step like
   "The SteveCAM connector was shutting down; start it again (menu bar: Start) and re-run.") next to the other run-lifecycle
   codes, and regenerate ONLY the codes table in docs/agent_guide.md so it equals errors.render_code_table() exactly.
   test_track2.py::test_f_codes_table_and_guide_in_sync must pass (run it; paste the exit code).
4. Long-poll slice (supervisor review of 7f89867): POLL_INTERRUPT = 1.0 makes the idle connector GET /messages once a second
   (30x the old rate). Set POLL_INTERRUPT = 10.0 (fewer requests; shutdown still bounded well inside launchd's default 20 s
   ExitTimeOut - our plist sets none). Change nothing else in _poll_messages. Re-run test_panelcancel.py (all) and state the
   measured SIGTERM-to-exit times of the two SIGTERM tests (they use poll_wait=1, so they should not change).
## Tests (append to connector/test_panelcancel.py)
 a. test_cancel_queued_job_dropped: long fake job A running, job B queued behind it; cancel(B). Assert B's states are exactly
    ["received", "cancelled"] (never "running"; its fake run is never called - count calls), A ends "succeeded"
    unaffected, and a later redelivery-like duplicate of B's message (same run id) is not run.
 b. test_double_cancel_queued_reports_once: cancel(B) twice -> B's states exactly ["received", "cancelled"] (one of each).
 c. MUTATION M3 (scratch copy only): skip the queue removal (report nothing, leave B queued) -> (a) red. Record the result.
AT-RISK (must stay green; paste exit codes): connector/test_panelcancel.py (all), connector/test_pidstatus.py (all),
connector/test_show3d.py, connector/test_track2.py::test_f_codes_table_and_guide_in_sync.
## Results: what changed (+ line counts), each test's result and time, M3 measured. Then stop.
