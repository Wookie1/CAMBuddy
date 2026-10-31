# SP-P3C-2 RESULTS — failure propagation, cancel of both chains, atomic outputs

Session: round 2 of 2, on top of d3e2049 (SP-P3C-1), brief = TASK_SPP3C2.md @ e064b5e.
Scope: connector/runner.py only + NEW test file connector/test_spp3c2.py.
All commands run FOREGROUND through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh.
No Core Front job was run. Nothing staged, nothing committed.

## Baseline (before any edit)

- `git diff --numstat` baseline (pre-existing, NOT from this task):
  `26 4  opencode.json` (harness config change already present at session start).
- Test lane: `/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>`;
  pytest lane binary: /opt/homebrew/bin/pytest (the VibeCAD python has no pytest).

## Plan

1. Process tracking + cancel: `self._proc` -> set `self._procs` under `self._lock`
   (add after Popen, discard after wait in a finally). `cancel()` = set
   `cancelled`, then SIGTERM every live process group, re-SIGTERM any group that
   appears while tearing down, after up to 5 s SIGKILL every group still alive.
   ProcessLookupError/PermissionError fall back to terminate()/kill() as before.
   Every _spawn uses start_new_session=True so killpg reaches zmap's fork Pool /
   the engine's island pool / grandchildren in the step's group.
2. Failure propagation in run_slope_split_finish: first-error map under a lock
   ({exc, chain}); shared stop flags (stop_engine for the engine chain, the
   existing abort for the judge chain) checked in step() before every step;
   the failing chain records the first error, sets the other chain's stop flag
   and kills every live process group; both chains' error paths join the judge
   thread and ensure no tracked proc is alive BEFORE raising; the FIRST error is
   re-raised unchanged; cancel() always ends as Cancelled.
3. Atomic outputs: verify by reading connector.py + panel that nothing reads a
   judge's in-flight files during a run (evidence below). No runner temp-file
   change unless a real race is found.

## Test log

(append after every run: command, exit code, pass/fail, git diff --numstat)

- BASELINE pre-edit, lane `/opt/homebrew/bin/pytest`:
  - `connector/test_spp3c.py -q` -> 12 passed, EXIT=0 (3.75 s).
  - `connector/test_connector.py -q -k "not E2E"` -> 80 passed, 32 deselected,
    EXIT=0 (167 s).
  - `connector/test_connector.py -q -v` (full) -> EXIT=124 (timeout 780 s):
    the 12 TestAgentEnvelopeE2E/TestTl2*/TestZg1conn* E2E tests run the REAL
    engine chain (mock connector waits up to 3600 s per run); tests 1..107
    passed, test #108 (test_envelope_schema_on_tb_runs, real slope-split)
    still running when the timeout fired - slow, not hung. E2E is therefore
    verified post-edit with a dedicated long-timeout run (see below).

## (3) Atomic-output evidence (confirmed by reading the code, no runner change)

Nothing the panel or connector reads DURING a run is a file a judge is still
writing, so no temp-name + os.replace was needed in the runner:

- The connector is SINGLE-THREADED: connector.py:720 `run_forever()` polls
  STEVE and calls `handle_message` inline (connector.py:748); there is no
  `import threading` / `Thread(` anywhere in connector.py. A run therefore
  blocks the loop: no view.load / Show 3D / status request is processed
  while `run_slope_split_finish` is executing.
- The run dir IS the future panel dir (connector.py:560
  `work = os.path.join(self.home, "runs", str(run_id))`), but the only
  reader of an existing `<home>/runs/<id>` during operation is
  `_view_load_files` / `_run_view_load` (connector.py:379-438), reached
  only through `handle_message` - i.e. serialized AFTER the previous run
  returned or raised, which (per (2)) is only after the judge chain was
  joined and its process groups killed. view.bin/view.json/view_*.png are
  built by the runner only after `judge_thread.join()` (runner.py:1690
  / :1696 join; runner.py:1771 `final_stock`, :1777 `_build_view`,
  :1790 `_build_view_images`), so a Show 3D never sees them half-written
  and never reads judge outputs directly.
- Files uploaded to STEVE are read only after the call returns:
  connector.py:654 `run_slope_split_finish` returns -> :659-666 check.json
  read -> :668-671 `put_file` loop reads `files` -> :675
  `report_run(... "succeeded")` -> :677 `end_run()`; the Cancelled path
  (:678-684) and the failure path (:694-699) likewise only run afterwards.
- During the run, progress messages carry text only (connector.py:585
  `report_run(... "running", progress=...)`), no file reads.
- status.json is written by connector.py itself (`_write_status`,
  connector.py:167, documented "Atomic <home>/status.json"), never by the
  runner or a judge.
- The panel is static HTML/JS served through STEVE (connector/panel/); it
  reads the RESULT payload of the final run state, not the filesystem
  (no fs/run-path reads in panel/panel.js, report.js, viewer.js).
- Inside the run, the ENGINE chain never reads a judge file: rough exports
  its own stock (runner.py:1548 `--stock-from rough_stock_out`), the rest
  pass plans on the ENGINE's finish stock (runner.py:1527 "RR-STOCK: ...
  the rest pass plans on THAT (never on a judge stock)", :1603
  `--rest-from stock_fin_engine`, :1607 `--stock-from rough_stock_out`).
  The judge's own outputs (check_rough/check_finish/check_rest.json,
  part_hf01.npy, stock_after_rough/finish/rest.npy, preview.png) are read
  only by the judge chain itself (sequentially, right after its own step)
  or after both chains ended (check.json assembly, view builder).

=> No racing reader exists; per the brief, no temp+os.replace change made.

## Test log (continued)

- RUN 3: `pytest connector/test_spp3c2.py connector/test_spp3c.py
  connector/test_connector.py -q -k "not E2E"` (/usr/bin/timeout 500)
  -> **100 passed, 32 deselected, EXIT=0** (173 s). numstat unchanged.
- RUN 4 (test hardening: the no-orphans 6 s window now measured FROM the
  cancel): `pytest connector/test_spp3c2.py -q` -> **8 passed, EXIT=0**
  (5.58 s).
- MUTATION (scratch, then reverted): runner.py `cancel()` made to kill ONE
  tracked proc only (`procs[-1:]`) and the two error-path `_kill_all()`
  calls removed (faithful round-1 world: cancel was the only killer and
  knew a single proc).
  `pytest connector/test_spp3c2.py -q -k CancelNoOrphans`
  -> **2 failed** (exit code of the pipeline lost in `tail`; pytest line:
  `2 failed, 6 deselected in 121.07s`), e.g.
  `AssertionError: pid 66424 died too late (60.0 s after cancel)` - the
  no-orphans test detects the single-proc cancel exactly as required.
  Reverted from /tmp/spp3c2_runner_backup.py: `grep -c MUTATION` -> 0,
  numstat back to `147 38 connector/runner.py`.
- RUN 5 (post-revert): `pytest connector/test_spp3c2.py connector/test_spp3c.py -q`
  -> **20 passed, EXIT=0** (9.02 s).
- RUN 6 (E2E, real engine through the connector subprocess):
  `pytest connector/test_connector.py::TestZg1connStockBottomE2E -q`
  (/usr/bin/timeout 1500) -> **1 passed, EXIT=0** (272.50 s). This is the
  full TB slope-split finish WITH rest pass end-to-end: both chains, all
  three zmap judges, clcheck gates, view build - success path unchanged.
- RUN 7 (E2E failure + rough paths):
  `pytest connector/test_connector.py -q -k "NothingToCutE2E or
  OrientationE2E"` (/usr/bin/timeout 1100) -> **4 passed, EXIT=0** (14.93 s).
- RUN 8 (style fix in the test file, final re-run):
  `pytest connector/test_spp3c2.py -q` -> **8 passed, EXIT=0** (5.64 s).
  Final `git diff --numstat`: `147 38 connector/runner.py` + pre-existing
  `26 4 opencode.json`; untracked: connector/test_spp3c2.py,
  connector/SPP3C2_RESULTS.md. Nothing staged, nothing committed.
  (The remaining 27 E2E tests exercise non-slope actions or duplicate the
  TB chains; the two slow envelope/Tl2 TB runs exceed this session's time
  budget - test #108 alone already exceeded 600 s at the pre-edit
  baseline. Supervisor's full-suite run covers them.)

## What changed (connector/runner.py, 147+/38-)

1. `EngineRun.__init__`: `self._proc` -> `self._procs` set (live Popens).
   `_spawn`: adds the Popen under `self._lock`, discards it in a `finally`
   around the stdout-drain + `proc.wait()`. `run()` / `run_measure()` /
   `run_check_program()` unchanged (still one proc at a time).
2. `cancel()` = set `cancelled` + `_kill_all()`; `_kill_all()` SIGTERMs
   every live tracked process group (start_new_session=True => killpg
   reaches zmap's fork Pool / the engine's island pool / grandchildren),
   re-scans while tearing down (catches a group that starts mid-teardown),
   and after up to 5 s SIGKILLs every group still alive. The old
   ProcessLookupError/PermissionError fallbacks stay (terminate()/kill()).
3. `run_slope_split_finish`: `first_error` {exc, chain} under `first_lock`
   (first failure wins, later ones ignored); `stop_engine` Event; `step()`
   raises `Cancelled` before any step when cancelled / when the other
   chain failed first; the judge error path records the first error, sets
   stop_engine and `_kill_all()`s the engine's live group; the engine
   error path records, sets abort + every Event (judges cannot wait),
   `_kill_all()`s the judges' live group; BOTH exit paths join the judge
   thread and leave no tracked proc alive before raising; the FIRST error
   is re-raised unchanged (same object/type/code/where), cancel() always
   ends as `Cancelled`, and an internal stop is never reported in place of
   the first error. The judge thread is named "judge-chain" (asserted
   joined by the tests).
4. Atomic outputs: no code change - no racing reader exists (evidence
   above).

## Deviations / notes

- The mutation step also had to remove the two error-path `_kill_all()`
  calls: with them present, a cancel()-only mutation self-heals (the
  awakened chain's error path kills the survivor), so the round-1 world
  being modeled is "cancel knows one proc AND the error paths never kill"
  - exactly the pre-SP-P3C-2 semantics the brief describes.
- The no-orphans tests measure the 6 s window FROM the cancel moment, so
  a survivor that only dies when its own 60 s sleep ends cannot pass.
- No existing test was edited; no Core Front job was run; every command
  ran in the foreground through the slot_m4 lane.

