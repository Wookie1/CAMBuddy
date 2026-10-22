# RR1a results — rough fails CLOSED on any non-flat tool (ball refused)

Branch `rr1a` (= main @ 25acd51), worktree /Users/James/ai-sandbox/stevecam-rr1a.
Not committed (per task). All numbers below produced in this session; logs in `out/`.

## What it did TODAY (main, verified this session)
- CLI: `rough --tool ball:9.525` parses kind=ball but carries only dia/2 +
  corner(=0) into `rough()` → `big_cutter`/`actual_cutter`
  (engine/rough.py:95-109) build an `ocl.CylCutter`: verified in this
  session — `parse_tool("ball:9.525") -> ('ball', 9.525, 0.0)`,
  `big_cutter -> CylCutter`, `actual_cutter -> CylCutter`. A ball request
  silently became a FLAT rough.
- Connector: `catalog.validate_inputs` ACCEPTED `tool_type="ball"`
  (enum listed ball; corner silently coerced to dia/2) — verified this
  session: `adaptive_rough ball: True ('ball', 4.7625)` and same for
  `rough_tool_type` on slope_split_finish; the runner then spawned
  `engine.cli rough --tool ball:D:cr`. e2e proof on a pristine main copy
  (main source + new tests): run 606 was NOT rejected — it went to
  `running` and the refusal test failed (`1 failed in 31.51s`,
  out/rr1a_gate.log `BASE_E2E_RC=1`).

## What it does AFTER
- CLI rough (engine/cli.py, guard right after `parse_tool`, before any
  work — the STEP file is never opened): any kind other than flat/bull →
  stderr `rough: tool kind 'ball' refused (ball:9.525): adaptive rough
  cuts flat or bull end mills only ...`, exit **1**, no program written.
  A corner-less `bull:DIA` (would also silently run flat) is refused the
  same way. Bull with corner is genuinely supported end to end
  (`bull:*:cr>0` → `ocl.BullCutter(dia, cr)` in big_cutter/actual_cutter)
  and is kept. `--tool` help updated (ball no longer advertised).
- Connector: ball removed from the roughing `tool_type` enum in
  connector/catalog.py `_ROUGHING_INPUTS` (shared by adaptive_rough and
  slope_split_finish's `rough_tool_type`) → STEVE gets validation error
  `tool_type='ball' not in enum ['flat', 'bull']`
  (code `input_out_of_range`, message now carries the allowed values),
  run state `rejected` before any engine spawn; the dead ball→dia/2 corner
  coercion is removed. The panel no longer offers Ball for roughing
  (connector/panel/index.html). The slope action's own finishing ball and
  the rest-ball path are untouched.

## Tests (each fails on main, passes here)
- engine/test_engine.py `test_rr1a_rough_cli_refuses_ball`: ball → nonzero
  + refusal on stderr + no .ngc; corner-less bull refused; flat still
  roughs end to end (363550-byte program). Fails on main
  (`no clear ball refusal on stderr`, verified against a main-code copy);
  passes: `PASS rr1a rough cli ...` `CLI_TEST_RC=0` (out/rr1a_gate.log).
- connector/test_connector.py `test_ball_rough_rejected_before_running`
  (e2e, run 606): rejected with `input_out_of_range`, never `running`.
  Fails on main (`1 failed in 31.51s` / rerun `32.11s`, BASE_E2E_RC=1);
  passes inside the suite (PYTEST_RC=0 below) and standalone via the slot:
  both new connector tests `PASSED`, **NAMED_RC=0** (out/rr1a_named.log).
- connector/test_connector.py `test_rough_refuses_ball` (catalog unit):
  ball refused on ACTION and SLOPE_ACTION rough tool, bull/flat still
  clean, panel option gone. Fails on main (`1 failed`, AssertionError at
  the ball-accepted assert); passes here.

## Suites (via the ONE-JOB SLOT, real exit codes; out/rr1a_gate.log)
- scripts/check_fixtures.py: **FIXTURES_RC=0** (10 fixtures ok — restored
  frozen goldens from /Users/James/ai-sandbox/stevecam/out, same as HR1)
- engine/test_engine.py (VibeCAD python): `0 failure(s)` **ENGINE_RC=0**
- engine/test_finish.py (VibeCAD python): `ALL FINISH TESTS PASSED`
  **FINISH_RC=0**
- /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q:
  **222 passed**, 32 warnings in 961.56 s, **PYTEST_RC=0**

## Diff (git diff --numstat, this session)
engine/cli.py +14/-1 · connector/catalog.py +8/-8 · connector/panel/index.html -1
(= 22 insertions / 10 deletions non-test) · tests: engine/test_engine.py
+46/-1, connector/test_connector.py +33.
Note: opencode.json shows a pre-existing baseURL edit (192.168.0.14 →
127.0.0.1) that was already in the worktree at session start — untouched by me.
