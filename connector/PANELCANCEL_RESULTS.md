# PANELCANCEL results

Session start: `Fri Oct 30 18:16:19 MST 2026` (branch panel-cancel @ 3da478e, main=2da9125).
Finished: `Fri Oct 30 18:35 MST 2026` (~19 min of the 60-min budget; hard stop ~19:46 not approached).
All commands FOREGROUND, all tests through `/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh`
(small lane; longest lane run 5:25 < 10 min). No Core Front, no real engine run beyond
what the at-risk -k batch itself contains (fake spawns in MY tests only). No lock files
touched, nothing installed, no git state changes, no commits, only my own child PIDs
signalled (exact PID, SIGTERM-then-kill-in-teardown). `opencode.json` was already
modified before this session started - NOT mine, untouched.

## Per-item changes (connector/connector.py: +117 / -44 lines; total diff incl. new files below)

**Item 1 - FIFO worker (loop keeps polling).** `__init__`: `self._queue = queue.Queue()`,
`self._worker = None`, `self._lock = threading.RLock()` (+7 lines). New `_dispatch` /
`_exec` / `_worker_loop` (+31 lines): while `run_forever` is up, every job and tool
action is queued as a tuple and executed by ONE daemon worker thread, arrival order,
one at a time - exactly today's ordering. The loop itself handles only "cancel".
Ledger/nonce bookkeeping (`_remember_run`/`_remember_nonce`) stays in the loop BEFORE
queueing, so a ledger run id is never acted on twice and a queued job reports nothing
until the worker picks it up. `_dispatch` runs the item inline when no worker exists
(direct `handle_message` callers - that is how every existing test drives the
connector - keep byte-for-byte today's synchronous behaviour). `run_forever` starts
the worker before enroll.

**Item 2 - verified cancel only.** `handle_message` cancel branch (+8 lines): the
branch now acts ONLY when `verify_envelope` passed (`if not ok: return` - forged /
expired / unknown-kid cancel ignored SILENTLY, no report; on main it was acted on
before the `ok` check). Only `env["run"] == self.current_run` of the ACTIVE job calls
that EngineRun's `cancel()`; queued / finished / unknown ids are ignored (no state
change, no report). No "cancelled" report from the loop - the worker's existing
`except Cancelled` (:678-683 of main) reports it once and runs end_run() ->
status.json ends "idle". Path unchanged otherwise.

**Item 3 - one RLock serializes the writes.** `self._lock = threading.RLock()`;
`_write_status` body wrapped (+lock, status.json still atomic tmp+os.replace);
`emit_state` = ONE critical section (_write_status + _last_event check/update +
post_event); new `_report()` helper wraps every `client.report_run` (15 call sites
rewired; SteveError propagation to the existing handlers unchanged); the
last_run/status/last_runs-event block in `record_run_end` also under the same lock.
RLock so emit_state can nest _write_status.

**Item 4 - SIGTERM / stop().** `stop()` unchanged (sets `_stop`, cancels the active
job). `run_forever` tail (+6 lines): after the loop - cancel the active job (if any),
let the worker finish it, worker exits its 0.25 s `get()` poll WITHOUT draining
anything new, `self._worker.join(timeout=60)` (bounded), then `_write_status("off")`
and main() releases the pidfile -> exit 0. `test_pidstatus.py::test_sigterm_exits_zero`
green (see log).

## Tests - connector/test_panelcancel.py (NEW, 360 lines)
Real connector subprocess against in-process MockSteve (like test_pidstatus's SIGTERM
test). **FAKE SPAWN (chose this option, as the brief requires saying): the launcher
monkeypatches `runner.EngineRun.run` with a fake that sleeps in 0.05 s steps and
raises `runner.Cancelled` once `self.cancelled` is set (exactly what the real _spawn
does); no real child, so the "child PID gone" check is N/A.** `SteveClient.download`
is patched to a fake STEP blob (its sha256/bytes are embedded in the run inputs).
`PANELCANCEL_N` (=CANCEL_N) **N = 10.0 s**; long fake job = 35 s (>= 30 s).

| test | what | result |
|---|---|---|
| (a) test_cancel_mid_job | running + enqueue_cancel(active run) | PASS - terminal 'cancelled' **0.11 s** after the cancel (N=10 s), status.json 'idle', then SIGTERM exit 0, pidfile released |
| (a)-main test_cancel_mid_job_fails_on_main_connector | same scenario vs `git show 2da9125:connector/connector.py` scratch copy | PASS (asserts the OLD behaviour): terminal **None after 10.1 s**, job still 'running' -> main does NOT cancel |
| (b) test_cancel_other_id_ignored | cancel for a QUEUED run id + an UNKNOWN id | PASS - active job 'succeeded', queued job later 'succeeded', no 'cancelled' anywhere |
| (c) test_forged_cancel_ignored | cancel with a bad (random) signature for the active run | PASS - job 'succeeded', nothing reported for the cancel |
| (d) test_second_job_waits | 2nd job enqueued while 1st runs | PASS - 2nd has NO reports while 1st runs; terminal order == enqueue order; 'received' is the 2nd's first report, after the 1st's terminal |

Full-file run: **5 passed in 39.90s, EXIT=0** (18:28).

## (a) main-vs-branch, both pasted
- BRANCH: `test_cancel_mid_job` PASS - `PANELCANCEL BRANCH MEASUREMENT: terminal='cancelled' after 0.11 s (N=10.0 s; the fake job would run 35 s)`.
- MAIN (same test file, `PANELCANCEL_CONNECTOR_DIR=scratch/panelcancel_main`, the unmodified 2da9125 file): **FAILED, EXIT=1** - `AssertionError: no terminal 'cancelled' within N=10.0 s (got None after 10.0 s)` -> 1 failed in 12.02s (18:35).

## M1 mutation (scratch/panelcancel_m1, the MODIFIED file copied there - never edited the real one)
Removed the loop's cancel dispatch (`target = ...; self.running.cancel()` -> plain
`return`). `PANELCANCEL_CONNECTOR_DIR=scratch/panelcancel_m1 ... ::test_cancel_mid_job`
-> **(a) RED: EXIT=1**, `no terminal 'cancelled' within N=10.0 s (got None after 10.1 s)`,
1 failed in 12.56s (18:35). Mutation killed by the new test.

## AT-RISK suites (all through the lane, exit codes pasted)
- connector/test_pidstatus.py (all 5): **EXIT=0**, 5 passed in 2.99s (18:28)
- connector/test_show3d.py: **EXIT=0**, 27 passed in 14.46s (18:28)
- connector/test_view3d.py: **EXIT=0**, 11 passed in 0.78s (18:29)
- connector/test_connector.py -k "envelope or nonce or reject or ledger": **EXIT=0**,
  22 passed, 90 deselected in 324.63s (18:29-18:34). Ran (22):
  TestCryptoUnit::test_envelope_and_keys_list_verify; TestTimestamps::test_naive_rejected;
  TestTimestamps::test_garbage_rejected; TestNegatives::test_bad_envelope_sig_rejected;
  TestNegatives::test_sha_mismatch_rejected_before_running;
  TestNegatives::test_expired_envelope_rejected; TestNegatives::test_input_out_of_range_rejected;
  TestNegatives::test_ball_rough_rejected_before_running; TestTimestampsE2E::test_naive_iso_rejected;
  TestTimestampsE2E::test_garbage_time_rejected; TestTimestampsE2E::test_expired_iso_rejected;
  TestSteveKeys::test_rotation_by_untrusted_key_rejected_keeps_old;
  TestSteveKeys::test_tampered_keys_list_rejected; TestSlopeCatalog::test_validate_rejects;
  TestSlopeSplitFinish::test_out_of_range_input_rejected;
  TestStaleArtifactsRejected::test_stale_hf01_wrong_step_sha_rejected;
  TestStaleArtifactsRejected::test_failing_hf_build_with_stale_file_fails_run;
  TestStaleArtifactsRejected::test_stale_model_stl_fails_run;
  TestPerAxisStockCatalog::test_rejects_negative; TestAgentEnvelopeE2E::test_agent_walk_through;
  TestAgentEnvelopeE2E::test_envelope_schema_on_tb_runs;
  TestTl2CheckOriginE2E::test_missing_origin_rejected.
  (These include the real-engine E2E `live` fixture runs - they exercise the new
  subprocess worker end-to-end and stayed green.)

## Test log (chronological, exit codes)
- 18:25 `... pytest connector/test_panelcancel.py` -> EXIT=1, 5 failed: MY test bug -
  MockSteve(code="PAIR-PC-*") vs config pairing_code "PAIR-1234" -> child exited
  "code_invalid" before enrolling. Fixed (MockSteve() default code). connector.py untouched.
- 18:26 `... "::test_second_job_waits"` -> EXIT=0, 1 passed 7.92s.
- 18:27 full file -> EXIT=1, 4 passed 1 failed: main-comparison child crashed in
  publish_catalog_and_panel() (reads panel/ next to ITS connector.py - scratch copy
  had none). Fixed: start_connector symlinks panel/ into scratch connector dirs.
- 18:27 `... "::test_cancel_mid_job_fails_on_main_connector"` -> EXIT=0, 1 passed 12.01s.
- 18:28 `... pytest -q -s connector/test_panelcancel.py` -> **EXIT=0, 5 passed 39.90s**
  (measurements above).
- 18:28-18:34 AT-RISK runs: pidstatus EXIT=0 (2.99s), show3d EXIT=0 (14.46s),
  view3d EXIT=0 (0.78s), test_connector -k EXIT=0 (324.63s).
- 18:35 M1 (a) -> EXIT=1 red; main (a) -> EXIT=1 red (both as expected/recorded).

## Final `git diff --numstat` (18:35)
```
117	44	connector/connector.py
26	4	opencode.json        <- pre-existing at session start, NOT part of this task
```
Untracked added by me: connector/test_panelcancel.py (360 lines),
connector/PANELCANCEL_RESULTS.md, scratch/panelcancel_m1/ + scratch/panelcancel_main/
(M1 / main-comparison copies + panel symlink, kept for the supervisor; scratch/ per brief).
Not committed (per brief). No lane stuck, no locks touched.

---

## PANELCANCEL3

Session start: `Fri Oct 30 18:39 MST 2026` (branch panel-cancel @ f8ccf71). Budget 45 min, hard stop ~19:49.
Baseline `git diff --numstat` at start: `26 4 opencode.json` (pre-existing, NOT part of this task).
Plan: (1) SIGTERM/SIGINT handler ONLY sets a threading.Event; loop + shutdown tail do cancel/join/reject/"off"
outside signal context; (2) queued items rejected "connector_stopping" at shutdown; (3) main-measure test
skip unless PANELCANCEL_MEASURE_MAIN=1. New tests (a) test_sigterm_while_spawn_holds_lock,
(c) test_queued_job_rejected_on_shutdown; M2 mutation in scratch copy only. All tests via
`/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh`, foreground, targeted only.

### Log (append after every run: command, EXIT, date)
- 18:40 `slot_m4.sh ... -m py_compile connector/connector.py` -> EXIT=0.
- 18:41 `... pytest connector/test_panelcancel.py::test_queued_job_rejected_on_shutdown` -> **EXIT=0**,
  1 passed 3.95s. (c) MEASURED: SIGTERM with A running + B queued -> **exit 0 after 0.56 s**;
  A terminal "cancelled", B exactly ["rejected"] code connector_stopping, pidfile gone, status "off".
- 18:41 `... pytest connector/test_panelcancel.py::test_sigterm_while_spawn_holds_lock` -> **EXIT=0**,
  1 passed 4.83s. (a) MEASURED: SIGTERM while the run's self._lock is held (3.0 s) -> **exit 0 after
  2.98 s** (N = SIGTERM_N = **10.0 s** hard bound via proc.wait); pidfile removed, status "off", job cancelled.
Current `git diff --numstat` (18:41): connector.py +79/-16-ish (see Final), test file appended (+~190 lines).
- 18:42 MUTATION M2 (scratch/panelcancel_m2/connector.py = my fixed file with _handle_signal
  changed to call self.running.cancel() DIRECTLY and never set the Event):
  `PANELCANCEL_CONNECTOR_DIR=$PWD/scratch/panelcancel_m2 slot_m4.sh ... pytest \
   connector/test_panelcancel.py::test_sigterm_while_spawn_holds_lock` -> **EXIT=1, 1 failed in 36.68s**
  = **HANG**: `subprocess.TimeoutExpired: ... timed out after 10.0 seconds` (proc.wait's hard
  SIGTERM_N bound - never an infinite wait; teardown then SIGTERMs again, still ignored, hard-kills).
  The handler blocks on the held lock IN signal context and the loop never learns to stop: SIGTERM
  effectively ignored. Mutation killed by test (a).

### What changed (connector/connector.py +101 / -16; connector/test_panelcancel.py +207 / -0, append + 1 decorator)

**Item 1 - handler ONLY sets an Event; shutdown work outside signal context.**
`self._stop` is now a `threading.Event` (:147). New `_handle_signal` (:811-820) is the
SIGTERM/SIGINT handler registered by run_forever: its entire body is `self._stop.set()` -
no cancel, no join, no I/O, no status write (docstring states why: handler runs on the MAIN
thread between bytecodes, possibly inside `_spawn`'s `with self._lock:`, the same
non-reentrant lock `EngineRun.cancel()` takes; the other thread's teardown can keep
cancel() busy for seconds). `stop()` kept as a programmatic request - also ONLY sets the
Event. All `_stop` reads are `is_set()` checks (:277 get_token_blocking, :407/:412 worker,
:873 loop). run_forever tail (:901-912, outside signal context): cancel active job ->
worker join(timeout=60, bounded) -> `_reject_queued()` -> `_write_status("off")` -> return
-> main() releases pidfile, exit 0.
**Long-poll choice: loop-based slicing, NO watcher thread** (`_poll_messages`, :830-857):
the poll_wait-long fetch is taken in slices of <= POLL_INTERRUPT = 1.0 s; when the Event is
set the next fetch asks wait=0 (immediate). Chosen because the loop thread must run the
shutdown tail anyway (a watcher would race the message handling / cursor save, and could
not interrupt an in-flight HTTP read either - slicing bounds it instead). Worst-case
shutdown wait beyond the tail itself = one poll slice ~= 1 s (measured total 0.56 s in (c),
which included the cancel round-trip); with the old code it was a full poll_wait (default
30 s). With the tests' poll_wait=1 the request pattern is unchanged (one GET /messages per
iteration); with poll_wait=30 idle it costs one extra GET per second - idempotent by
protocol (ledger dedupes), the price of a bounded shutdown.

**Item 2 - queued items rejected at shutdown.** `_reject_queued` (:631-652): after the
worker stopped, every job/tool item still in `self._queue` gets ONE `report "rejected"`
with `errors.make_error("connector_stopping", "connector shut down before this run
started")`, SteveError swallowed (_safe_reject-style); nothing queued is executed.
`_worker_loop` (:406-418) re-checks the Event AFTER `get()` and puts a just-taken item
BACK unrun (so it cannot slip through the drain and get executed at shutdown). The loop's
mid-batch `if self._stop: break` is REMOVED (:886-898): the whole fetched batch is handled
(every run remembered + queued), so the cursor save can never silently swallow a message -
anything not run is in the queue and gets its terminal "connector_stopping" report.
NOTE (SCOPE: connector.py only): `connector_stopping` is therefore NOT added to
errors.CODES / docs - `make_error` gives it `next_step: ""`; registering the code is a
follow-up outside this task's scope (test_track2's CODES-vs-guide check is untouched).

**Item 3 - main-measure test opt-in.** `test_cancel_mid_job_fails_on_main_connector` got a
`pytest.mark.skipif(os.environ.get("PANELCANCEL_MEASURE_MAIN") != "1", ...)` decorator ONLY
(+6 lines, body and assertions byte-identical). Recorded run WITH the env var (18:43):
**EXIT=0, 1 passed 12.04s** - `PANELCANCEL MAIN MEASUREMENT: cancel for the ACTIVE run ->
terminal=None after 10.0 s ... not cancelled within N=10.0 s` (main still fails to cancel).

**New tests (appended; existing tests untouched).** `SIGTERM_N = 10.0` s hard bound
(proc.wait timeout) in both; `LAUNCHER_LOCKHOLD` fake holds `self._lock` (the exact lock
cancel() takes) for `LOCK_HOLD = 3.0` s on the WORKER thread, checking nothing inside -
honest-equivalence note in `start_connector_lockhold` (main never runs a job under the
worker design; the property proven is that the handler does no work, so it cannot block or
deadlock on the held lock, and the lock-waiting cancel runs later, outside signal context).
- (a) `test_sigterm_while_spawn_holds_lock`: **PASS, exit 0 after 2.98 s, N = 10.0 s**;
  pidfile removed, status "off", job terminal "cancelled", no hang.
- (c) `test_queued_job_rejected_on_shutdown`: **PASS**; A "cancelled", B exactly
  ["rejected"] code `connector_stopping` / message "connector shut down before this run
  started" (never "received"/"running"), exit 0 after 0.56 s, pidfile removed, status "off".
- M2 (scratch copy only, see log): **HANG measured** - TimeoutExpired after SIGTERM_N=10 s,
  EXIT=1 -> mutation killed by (a).

### AT-RISK suites (all via the lane, exit codes)
- 18:42 `... pytest connector/test_panelcancel.py` (default env) -> **EXIT=0**, 6 passed,
  1 skipped (the main-measure test now skips by design) in 36.62s.
- 18:43 `... pytest connector/test_pidstatus.py` (all 5, incl. test_sigterm_exits_zero) ->
  **EXIT=0**, 5 passed in 2.99s.
- 18:43 `... pytest connector/test_show3d.py` -> **EXIT=0**, 27 passed in 14.46s.

### Finished
`date` at finish: Fri Oct 30 18:44 MST 2026 (~5 min of the 45-min budget; hard stop not
approached). Final `git diff --numstat`:
```
109	0	connector/PANELCANCEL_RESULTS.md   (this file; its own count is from the moment of writing)
101	16	connector/connector.py
207	0	connector/test_panelcancel.py
26	4	opencode.json        <- pre-existing at session start, NOT part of this task
```
Untracked: scratch/panelcancel_m2/connector.py (M2 mutation copy + panel symlink, kept for
the supervisor). Not committed (per brief). No Core Front, no real engine run (fake spawns
only), everything foreground through slot_m4.sh, no lock files touched, no git state
changes, only my own child PIDs signalled. No existing test body/assertion/timeout deleted
or rewritten (only the supervisor-requested skipif decorator added).
- 18:44 final `git diff --numstat` pasted above; results file complete. Stopping (no commit).

---

## PANELCANCEL4

Session start: Fri Oct 30 2026, worktree /Users/James/ai-sandbox/stevecam-pc @ 62e9739
(branch panel-cancel). Brief connector/TASK_PANELCANCEL4.md. Budget 40 min, hard stop 60 min.

### Plan
1. connector.py: verified cancel for a QUEUED run removes it from self._queue (under
   self._queue.mutex) and reports "received" then "cancelled" once
   ("cancelled before it started"); second cancel for a dropped id ignored; a
   set self._dropped (loop-thread only) tracks dropped ids. POLL_INTERRUPT 1.0 -> 10.0.
2. test_panelcancel.py::test_cancel_other_id_ignored: queued-id part (8002) asserts the
   new behaviour (coordinator-approved single test change); unknown-id + active-job parts
   untouched.
3. errors.py: add "connector_stopping" code; regenerate only the codes table in
   docs/agent_guide.md (python3 connector/errors.py).
4. New tests test_cancel_queued_job_dropped, test_double_cancel_queued_reports_once
   (appended) + M3 mutation in scratch copy.

### Log
- (init) results section created; no test run yet. `git diff --numstat`: 26 4 opencode.json
  (pre-existing, not this task).
- 18:46 item 3 done: errors.CODES + "connector_stopping" (error) after input_digest_mismatch;
  `slot_m4.sh ... python3 connector/errors.py` -> EXIT=0 (guide +1 line only);
  guide == render_code_table() verified ("IN SYNC").
- 18:46 `slot_m4.sh ... pytest -q -p no:cacheprovider connector/test_track2.py::test_f_codes_table_and_guide_in_sync`
  -> **EXIT=0**, 1 passed in 0.14s.
- connector.py edited (items 1+4): cancel branch drops queued ids under self._queue.mutex,
  reports received+cancelled once, self._dropped guards double cancels; POLL_INTERRUPT=10.0.
- 18:47 item 2 done: test_cancel_other_id_ignored queued-id part now asserts the drop.
  BEFORE (lines 281-282 docstring, 293, 297-298):
    (b) cancels for a QUEUED run id and an UNKNOWN id are ignored: the
        active job completes "succeeded" (and so does the queued one).
    mock.enqueue_cancel(8002)       # queued id -> ignored
    assert mock.wait_terminal(8002, timeout=30) == "succeeded"
    assert "cancelled" not in mock.states_for(8002)
  AFTER:
    (b) PANELCANCEL4: a cancel for a QUEUED run id drops it (it never
        runs); one for an UNKNOWN id is ignored: ... ends ["received", "cancelled"]
    mock.enqueue_cancel(8002)       # queued id -> dropped, never runs
    assert mock.wait_terminal(8002, timeout=30) == "cancelled"
    assert mock.states_for(8002) == ["received", "cancelled"], \
        "the queued run was not dropped with exactly one report pair"
  Unknown-id (99999) line and both 8001 assertions unchanged; name kept.
- 18:47 new tests appended: test_cancel_queued_job_dropped,
  test_double_cancel_queued_reports_once (+ LAUNCHER_COUNTED calls-counting launcher,
  start_connector gained optional launcher_src/extra_env, defaults = old behaviour).
- 18:47 `slot_m4.sh ... pytest -q -p no:cacheprovider ::test_cancel_other_id_ignored
  ::test_cancel_queued_job_dropped ::test_double_cancel_queued_reports_once`
  -> **EXIT=0**, 3 passed in 27.70s.
  `git diff --numstat`: 31/0 RESULTS.md, 42/5 connector.py, 3/0 errors.py,
  169/10 test_panelcancel.py, 1/0 agent_guide.md, 26/4 opencode.json (pre-existing).
- 18:48 `slot_m4.sh ... pytest -q -p no:cacheprovider -s connector/test_panelcancel.py` (ALL,
  with POLL_INTERRUPT=10.0) -> **EXIT=0**, 8 passed, 1 skipped in 52.68s
  (the 1 skip = test_cancel_mid_job_fails_on_main_connector, opt-in by design).
  Item 4 measurements (both use poll_wait=1, so POLL_INTERRUPT 1.0 -> 10.0 cannot change
  them - min(poll_wait, POLL_INTERRUPT) stays 1 s - and they did not change):
  - test_sigterm_while_spawn_holds_lock: SIGTERM-to-exit measured **2.98 s**, exit 0
    (bounded by the 3.0 s held lock, not by the poll slice).
  - test_queued_job_rejected_on_shutdown: SIGTERM-to-exit measured **0.60 s**, exit 0.
  - (context) test_cancel_mid_job: terminal 'cancelled' 0.11 s after the cancel.
- 18:48 `slot_m4.sh ... pytest -q -p no:cacheprovider connector/test_pidstatus.py` (all)
  -> **EXIT=0**, 5 passed in 3.01s.
- 18:48 `slot_m4.sh ... pytest -q -p no:cacheprovider connector/test_show3d.py`
  -> **EXIT=0**, 27 passed in 14.47s.

### MUTATION M3 (scratch copy only) - measured
scratch/panelcancel_m3/connector.py = this connector.py with ONLY the queued-drop block
removed from handle_message's cancel branch (a queued-id cancel reports nothing and leaves
B queued); panel/ symlinked by the test helper; run via PANELCANCEL_CONNECTOR_DIR.
- 18:49 `PANELCANCEL_CONNECTOR_DIR=.../scratch/panelcancel_m3 slot_m4.sh ... pytest -q
  -p no:cacheprovider "connector/test_panelcancel.py::test_cancel_queued_job_dropped"`
  -> **EXIT=1**, 1 failed in 18.63s: wait_terminal(8202, timeout=15) returned None - with
  the drop removed B gets NO "cancelled" (A still runs its 12 s, B only starts afterwards),
  so test (a) is red. Mutation detected. Copy kept in scratch/panelcancel_m3/ for the
  supervisor.

### Summary of changes (git diff --numstat at finish, see below)
- connector/connector.py: +42/-5 - self._dropped set in __init__; cancel branch drops a
  QUEUED id under self._queue.mutex (the lock queue.Queue.get()/put() take - chosen over a
  private lock so the worker can never pick the item off between check and removal) and
  reports ONCE "received" then "cancelled" ("cancelled before it started") via the locked
  _report; second cancel for a dropped id ignored; unknown/finished ids still ignored, no
  report; active-run cancel and the ledger/nonce handling unchanged; POLL_INTERRUPT
  1.0 -> 10.0 (item 4, nothing else in _poll_messages touched).
- connector/errors.py: +3 - "connector_stopping" (kind "error") next to the other
  pre-run rejection codes.
- docs/agent_guide.md: +1 - codes table regenerated by `python3 connector/errors.py`
  (equals render_code_table(); test_track2.py::test_f_codes_table_and_guide_in_sync EXIT=0).
- connector/test_panelcancel.py: +169/-10 - the ONE approved test change (item 2 above) +
  appended PANELCANCEL4 section (2 new tests + counted launcher helper; start_connector
  gained launcher_src/extra_env kwargs, defaults preserve old behaviour exactly).
- connector/PANELCANCEL_RESULTS.md: this section.

### Finished
No Core Front, no real engine run (fake spawns only), all runs foreground through
slot_m4.sh, full connector/test_connector.py NOT run (supervisor's). No lock files touched,
no git state changes, no installs; only self-started child PIDs signalled (test shutdowns).
No G-code or large outputs printed. opencode.json diff (26/4) pre-existing at session
start, NOT part of this task. Nothing committed (per brief).
102	0	connector/PANELCANCEL_RESULTS.md
42	5	connector/connector.py
3	0	connector/errors.py
169	10	connector/test_panelcancel.py
1	0	docs/agent_guide.md
26	4	opencode.json
Fri Oct 30 18:49:32 MST 2026

---

## PANELCANCEL5 — bounded shutdown (< 30 s even if a child ignores SIGTERM) + plist ExitTimeOut 30

(session started ~19:0x; worktree /Users/James/ai-sandbox/stevecam-pc, branch panel-cancel @ cae05f2)

### Plan / status (kept current)
- [in progress] plist ExitTimeOut 30 + README line; connector.py _kill_engine_groups + bounded tail (grace 8 s, kill-join 4 s); tests a/b/d + unit; M4 mutation.

### Worst-case arithmetic (SIGTERM -> exit, must be < 30 s)
- <= POLL_INTERRUPT 10.0 s (last in-flight GET /messages slice before the loop sees the stop Event)
- cancel() of the active job: sets cancelled + killpg SIGTERM (bounded by the engine _lock, held at most across one Popen fork/exec - sub-second)
- SHUTDOWN_GRACE 8.0 s worker join
- SHUTDOWN_KILL_JOIN 4.0 s worker join after SIGKILL of the engine's live process groups
- tail: queued rejects (0..few POSTs, SteveError swallowed) + status "off" + pidfile release: ~1 s
- Total 10 + 8 + 4 + ~1 ~= 23 s < 30 s (launchd ExitTimeOut 30).
### Test runs (all via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh, foreground)
- 18:52 py_compile connector.py + both test files -> **EXIT=0**
- 18:52 `pytest -q -p no:cacheprovider menubar/test_menubar_files.py::test_plist_exit_timeout
  connector/test_panelcancel.py::test_engine_kill_hook_exists
  connector/test_panelcancel.py::test_kill_engine_groups_helper` -> **EXIT=0**, 3 passed in 0.15s.
  (Two launcher-template bugs fixed on the way: unescaped % in LAUNCHER_STUBBORN, and the
  child pid must be recorded BY the child (`echo $$`) - _spawn only returns once the child
  is gone, so a post-_spawn write can never appear while it lives.)
- 18:54 `pytest -q -p no:cacheprovider -s connector/test_panelcancel.py::test_shutdown_kills_child_ignoring_sigterm`
  -> **EXIT=0**, 1 passed in 10.83s.
  MEASURED (b): SIGTERM with a SIGTERM-ignoring REAL-_spawn child (sh 'trap "" TERM; sleep 120')
  -> connector **exit 0 after 8.97 s** (N=25 s), stubborn child pid **gone 8.97 s** after the
  SIGTERM; pidfile removed, status "off".
- 18:54 MUTATION M4 (scratch copy scratch/panelcancel_m4/connector.py = this connector.py with
  ONLY the SIGKILL step of run_forever's tail dropped - `_kill_engine_groups(engine)` +
  SHUTDOWN_KILL_JOIN join replaced by `pass`; run via PANELCANCEL5_CONNECTOR_DIR=that dir):
  same test (b) -> **EXIT=1**, 1 failed in 15.90s: connector exit 0 after 8.95 s (grace only,
  no kill-join: the removed block owned it) but **"child pid 79512 survived the shutdown
  (still alive after 14.0 s)"** - test (b) is RED without the backstop. Mutation detected.
  The copy stays in scratch/panelcancel_m4/ for the supervisor; the stray child was killed
  by exact PID in the test's finally.
- 18:56 combined at-risk run `pytest -q -p no:cacheprovider connector/test_panelcancel.py
  connector/test_pidstatus.py menubar/test_menubar_files.py connector/test_show3d.py`
  -> **EXIT=0**, 51 passed, 1 skipped in 81.58s (the skip is the permanently-skipped
  PANELCANCEL3 main-branch measurement test).
- 18:58 per-file at-risk re-runs (each its own lane run, exit codes as asked):
  connector/test_panelcancel.py -> **EXIT=0**, 11 passed, 1 skipped in 64.95s
  connector/test_pidstatus.py   -> **EXIT=0**, 5 passed in 2.99s
  menubar/test_menubar_files.py -> **EXIT=0**, 8 passed in 0.56s
  connector/test_show3d.py      -> **EXIT=0**, 27 passed in 14.47s

### Summary of changes
- menubar/com.stevecam.connector.plist.in: +2 - `<key>ExitTimeOut</key><integer>30</integer>`
  after ThrottleInterval (item 1).
- menubar/README.md: +2/-1 - one sentence (wrapped): ExitTimeOut 30 gives the connector 30 s
  to shut down cleanly before launchd SIGKILLs it.
- connector/connector.py: +62/-5 - module constants SHUTDOWN_GRACE = 8.0 / SHUTDOWN_KILL_JOIN
  = 4.0 and ONE helper _kill_engine_groups(engine) trying, in order, public live_pgids()
  (killpg each SIGKILL, OSError ignored), public kill_all(signal.SIGKILL), private _procs
  (set of Popen), private _proc; live == poll() is None; failed killpg -> p.kill()
  (ProcessLookupError/PermissionError), other OSError ignored, never raises. run_forever's
  tail: engine captured, cancel(), join(SHUTDOWN_GRACE) (was 60), if the worker is still
  alive -> _kill_engine_groups(engine) + join(SHUTDOWN_KILL_JOIN); queued rejects + "off"
  unchanged and run regardless. POLL_INTERRUPT comment updated (plist now sets 30).
- connector/test_panelcancel.py: +216/-0 (append only) - PANELCANCEL5 section:
  LAUNCHER_STUBBORN (fake run through the REAL runner._spawn, child
  /bin/sh -c 'echo $$ > pidfile; trap "" TERM; sleep 120' - own process group via
  start_new_session=True, records its OWN pid because _spawn returns only after the child
  is gone) + test_shutdown_kills_child_ignoring_sigterm (b) +
  test_engine_kill_hook_exists (d: real EngineRun, cfg {engine_python, repo_root} + tmp work
  dir, asserts >=1 of live_pgids/kill_all/_procs/_proc, message names all four) +
  test_kill_engine_groups_helper (pure unit, four fakes one per shape, records the path;
  Popen fakes carry an already-reaped child pid so no real signal is sent).
- menubar/test_menubar_files.py: +20/-0 (append only) - test_plist_exit_timeout (renders the
  template like test_plist_template_renders_and_lints, plistlib, asserts ExitTimeOut is an
  int >= 30).
- connector/PANELCANCEL_RESULTS.md: this section.

### Measurements
- (b): connector exit 0 **8.97 s** after SIGTERM (N=25 s; budget 30 s); stubborn child gone
  at the same 8.97 s; pidfile removed; status "off". (Idle poll ~0 s with poll_wait=1 +
  8.0 s grace + ~1 s tail; the kill-join was not needed - the SIGKILL lands within ms of
  the grace expiring.)
- M4 (SIGKILL step dropped): connector still exits 0 (8.95 s) but the child SURVIVES
  ("still alive after 14.0 s") -> (b) red, EXIT=1. The backstop is what kills it.
- Worst-case arithmetic (unchanged from the plan above): 10 (poll slice) + cancel (sub-s)
  + 8 (grace) + 4 (kill-join) + ~1 (rejects + "off" + pidfile) ~= 23 s < 30 s = the new
  plist ExitTimeOut.

### Finished
No Core Front, no real engine run (only the stubborn /bin/sh child through the real
_spawn), everything foreground via slot_m4.sh, full connector/test_connector.py NOT run
(supervisor's). No lock files touched, no git state changes, nothing installed, no
launchctl; only self-started PIDs signalled, by exact PID. No G-code or large outputs
printed. Scratch only under scratch/ (panelcancel_m4 + logs). opencode.json diff (26/4)
pre-existing at session start, NOT part of this task. Nothing committed (per brief).
