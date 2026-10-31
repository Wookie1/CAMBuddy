# SP-P3C-1 RESULTS (round 1)

Task: run the zmap judges as their own chain beside the engine chain
(connector/runner.py only; same verdicts). Two chains, progress text,
judge --jobs, per-step timestamps.

Status: IN PROGRESS. Do not commit; supervisor runs the full suites.

## Plan
1. Module constants: ZMAP_JOBS stays 12; add ZMAP_JOBS_OVERLAP = 6 and
   CHECKING_FMT = "checking (%d of %d)"; import time.
2. run_slope_split_finish: engine chain = calling thread (prepare, rough,
   tess, finish, post, clcheck, [rest, post_rest, clcheck_rest]); judge
   chain = one threading.Thread (hf01 + require_fresh, zmap rough, zmap
   finish, [rest sidecar merge, zmap rest]). threading.Event per producing
   engine step (ev_rough after rough accepted, ev_finish after post
   accepted, ev_rest after clcheck_rest); judges also serialize because
   they run sequentially in the one judge thread. Judge errors captured in
   a list and re-raised in the main thread after join; engine errors set
   abort + all events, join, re-raise.
3. Progress: one sink (prog = None-safe) under prog_lock; values clamped
   monotone; after the engine chain ends the only messages are
   CHECKING_FMT % (n, total), n = running judge (1-based), total = 2 or 3.
4. steps.log: "<step> <start epoch s> <end epoch s> <chain>" appended per
   step of both chains under prog_lock.
5. --jobs: ZMAP_JOBS_OVERLAP if engine_done not set at judge start, else
   ZMAP_JOBS; every other argv token byte-identical to the serial runner.
6. New tests: connector/test_spp3c.py (ordering, judge exception, progress
   text, jobs, identical outputs vs a serial reference copy kept in the
   test, steps.log) + mutation check.

## Environment / lane
- All tests via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
- Targeted only: connector/test_spp3c.py + the at-risk slope-split unit
  tests in connector/test_connector.py (live/E2E and full suites are the
  supervisor's).

## Baseline
- Start commit: 52a73a8 (brief), code base 2da9125.
- git diff --numstat at start (pre-existing, not mine):
  1	0	opencode.json  (modified in the worktree before this task began)

## Test runs (append after every run: exit codes + git diff --numstat)
(none yet)

### Run 3 (new test file, first run)
connector/test_spp3c.py: 1 failed, 12 passed, exit 1. Only failure was in my
own test (argv comparison compared the two runs' work-dir paths); fixed by
normalizing the work-dir prefix in the comparison. No runner change.

### Run 4 (new test file, 3 consecutive runs)
connector/test_spp3c.py: 12 passed x3, exit 0 each (threading tests stable).

### Run 5 (new tests + all at-risk TestRestPass incl. its live e2e tests +
TestEngageThresholdArgs + TestStaleArtifactsRejected + TestPostedUnitsRunner)
29 passed in 135s, exit 0. (The 135s is TestRestPass's three mock-STEVE
end-to-end runs with the real engine - they exercise the new two-chain
runner end to end and pass. No Core Front job was run.)
git diff --numstat: 479 304 connector/runner.py (plus new untracked files
connector/test_spp3c.py, connector/SPP3C1_RESULTS.md; opencode.json is the
pre-existing worktree change).

### Ordering durations strengthened
DUR_ORDER_REST made zmap_rough long (0.30 s) so finish.nc/rest.nc are ready
while the rough judge still runs: the ordering assertions then really prove
"each judge starts after the PREVIOUS judge finished".
Run 6: connector/test_spp3c.py 12 passed, exit 0.

### Mutation check (scratch, then reverted) - brief item "mutation"
The judges run sequentially in the one judge thread, so the "previous judge
finished" wait is that sequence. Mutation applied to connector/runner.py:
run the zmap_rough judge in its own sub-thread and let zmap_finish/zmap_rest
start as soon as their program event fires (sequence wait dropped).
Run 7 (MUTATED): TestChainOrdering 2 failed, exit 1 -
test_judges_follow_programs_and_each_other_rest and
..._no_rest both failed on "zmap_finish started before zmap_rough ended"
(start 1793406340.154 < end 1793406340.375). The mutation IS caught.
Reverted runner.py from a snapshot; git diff --numstat back to 479 304.
Run 8 (reverted): connector/test_spp3c.py 12 passed, exit 0.

### Run 9 (other existing connector tests that fake-spawn the slope chain)
test_rrstock2 + test_flload_conn + test_zg1conn + test_toollib +
test_view3d + test_view3dimg + test_tlg1 + test_track2:
104 passed, exit 0.

### Run 10 (remaining fast connector unit files)
test_pidstatus + test_units_publish + test_show3d + test_panel_inputs:
39 passed, exit 0.

## Final state
- Changed: connector/runner.py only (git diff --numstat 479 304).
- New: connector/test_spp3c.py (12 tests, incl. the byte-identical-outputs
  test against a verbatim reference copy of the serial runner kept in the
  test), connector/SPP3C1_RESULTS.md.
- No existing test edited. Nothing staged, nothing committed. No Core Front
  job run. All commands run in the foreground through the slot_m4 lane.

## Implementation notes (deviations / judgement calls)
1. The readiness Events fire right after the producing step is ACCEPTED:
   ev_rough/ev_finish after posted_units() validated the posted program,
   ev_rest after the rest probe_clcheck gate - so a judge never runs on a
   program the runner itself rejected. The engine chain still sets them
   "right after the step returned successfully"; with a valid program the
   acceptance code cannot fail.
2. ev_rest is set AFTER engine_done (clcheck_rest is the engine chain's
   last step), which is what makes the rest judge deterministically get
   ZMAP_JOBS=12 (item 3).
3. probe_clcheck failure formatting now uses cl.get("below_cl", 1): with
   hf01 moved to the judge chain, the engine chain can now reach clcheck
   while a fake/silent probe produced no JSON; in every real run probe
   emits the key, so verdicts and messages are unchanged (see Run 1).
4. Judge steps pass on_progress=None to _spawn; the only judge-chain
   progress is CHECKING_FMT through the locked sink (item 2). Values rise
   monotonically from the engine chain's last value to exactly 1.0 with
   the last judge.
5. steps.log lines: "<step> <start epoch s> <end epoch s> <chain>" with
   %.3f-second timestamps, appended under the same prog_lock, one line per
   _spawn of either chain (also for a step that failed, written in
   finally). Names: prepare rough tess finish post clcheck rest post_rest
   clcheck_rest (engine); hf01 zmap_rough zmap_finish zmap_rest (judge).
   steps.log is not added to result["files"] (byte-identical outputs).
6. Round 1 per the brief: a failure in either chain re-raises after both
   chains join (engine error wins if both fail); cancel/atomic-output
   hardening is round 2.
