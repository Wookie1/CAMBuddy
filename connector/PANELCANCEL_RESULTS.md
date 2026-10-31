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
