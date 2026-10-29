# SHOW3D results (branch show3d-2, base ffed52c)

Session start: Wed Oct 28 21:19 MST 2026 (`date`). Budget 45 min, hard stop 70 min.

## Plan
1. Red tests first (connector/test_show3d.py a/b/c + 3 panel_tests) run on UNCHANGED code.
2. Implement: catalog action "view.load" + event "last_runs", connector view.load handler + last_runs posting, panel "Recent runs" list.
3. Mutations M1/M2/M3 in scratch copies, measured values.
4. At-risk suites, all through the lane.

## Log
- 21:19 started; read brief, connector.py, catalog.py, view.py, mock_steve.py, envelope.py, errors.py, panel.js, viewer.js, mock_bridge.js, run_tests.js.
- RED (unchanged code ffed52c):
  - connector/test_show3d.py (NEW): `slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider connector/test_show3d.py` -> **16 failed, exit 1** (view.load unknown action; no record_run_end; last_runs not declared).
  - panel_tests ONLY='show3d': `NODE_PATH=... slot_m4.sh node .../pw_chrome.js run_tests.js` -> **0 passed, 3 failed (of 48), exit 1** (#recent never visible; no view.load run).
  - Test infra additions (not app code): panel_tests/mock_bridge.js serves a view.load run (files view.bin/view.json) and answers events() with last_runs when CFG.lastRuns; 3 new show3d tests in panel_tests/run_tests.js.

## Test runs (all through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh)
| time | run | result | exit |
| --- | --- | --- | --- |
| 21:23 | RED connector/test_show3d.py on ffed52c | 16 failed | 1 |
| 21:24 | RED panel_tests ONLY='show3d' | 0 passed, 3 failed (48 total) | 1 |
| 21:26 | connector/test_show3d.py (implemented) | 16 passed | 0 |
| 21:27 | panel_tests ONLY='show3d' | 3 passed (48 total) | 0 |
| 21:27 | FULL panel_tests suite | **48 passed, 0 failed** | 0 |
| 21:28 | at-risk: test_view3d, test_view3dimg, test_toollib, test_track2, test_flload_conn, test_rrstock2, test_tlg1, test_panel_inputs | 104 passed | 0 |
| 21:28 | test_connector.py -k "catalog or event or panel" | 13 passed, 99 deselected | 0 |
| 21:29 | test_show3d.py + test_connector.py -k "show3d or catalog or event or panel" | 29 passed | 0 |
| 21:30 | test_connector.py::TestEndToEnd::test_enroll_confirm_run (real rough E2E, 37 s) | 1 passed | 0 |

## Event-order decision (measured, not relaxed)
The EXISTING test_connector.py::test_enroll_confirm_run iterates ALL events as
`e["data"]["state"]` and asserts the LAST event is `("engine_state","idle")`.
To coexist without touching that test: last_runs data carries a `state` key
(`{"state":"idle","runs":[...]}`), and the connector posts last_runs BEFORE
the run-ending engine_state idle (end_run() in _run_job). Verified by the
21:30 real-E2E run above (exit 0); the entry shape the brief requires
{run_id, action, document_id, at, has_view} is unchanged.

## Notes
- connector/testdata/panel_default_inputs.json is rewritten by the panel-test
  runner itself; the ONLY= red runs left it briefly subset-empty, the FULL
  suite run (21:27, exit 0) restored it.
- opencode.json was already modified before this session; untouched.

## Implementation (done)
- connector/catalog.py: VIEW_ACTION "view.load" (+spec, appended to TOOL_ACTIONS), LAST_RUNS_EVENT "last_runs" declared in CATALOG events.
- connector/errors.py: code "no_view" ("no 3D view for that run"); docs/agent_guide.md table regenerated via `python3 connector/errors.py` (drift gate green in test_track2, exit 0 above).
- connector/connector.py: RUN_ID_RE strict run-id shape; _view_load_files (realpath inside <home>/runs, no symlink files/dirs, view.bin+view.json required); _run_view_load uploads byte copies as the view.load run's files (media octet-stream/json/png); record_run_end writes <home>/runs/<id>/run_meta.json + posts last_runs (<=10 newest first, <8 kB, fields capped); _run_job end_run() records+posts for every cutting/check run that ended (not for early rejections), before engine_state idle.
- connector/envelope.py: view.load summary.
- connector/panel/index.html + panel.css + panel.js: #recent "Recent runs" section (action, time, "has 3D"), "Show 3D" button per row (disabled unless has_view and view.load allowed; disabled from click until the run ends; button click ONLY), viewer via existing SteveCAMViewer.attach on the panel-started view.load run.
- panel_tests/mock_bridge.js + run_tests.js: mock serves view.load runs and last_runs in events(); 3 new show3d tests (names as briefed).

## Mutations (scratch copies; each fails a test by a MEASURED value)
| # | mutation | run | measured failure | exit |
| --- | --- | --- | --- | --- |
| M1 | drop the traversal/realpath check in _view_load_files (scratch/m1) | pytest scratch/m1/connector/test_show3d.py | `AssertionError: succeeded / assert 'succeeded' in ('rejected', 'failed')` — view.load SUCCEEDS on the runs/ symlink to outside <home>/runs (1 failed, 15 passed) | 1 |
| M2 | drop the 10-entry cap: runs = list(entries) (scratch/m2) | pytest scratch/m2/connector/test_show3d.py::test_last_runs_event_shape | `AssertionError: expected the 10 newest, got 25 / assert 25 == 10` | 1 |
| M3 | auto-start view.load on panel open after renderRecent (scratch/m3) | panel_tests ONLY='no auto-start' on scratch/m3 | `view.load was started without a click / 1 !== 0` (1 view.load run sent on open) | 1 |

## Final verification (after the last code change, 21:31)
- test_view3d + test_view3dimg + test_toollib + test_track2 + test_flload_conn + test_rrstock2 + test_tlg1 + test_panel_inputs + test_show3d: **120 passed, exit 0**
- test_connector.py -k "catalog or event or panel": **13 passed, exit 0**
- FULL panel_tests suite: 48 passed, exit 0 (21:27; panel/mock code unchanged since)
- test_enroll_confirm_run (real rough E2E): passed, exit 0 (21:30)
- Screenshots: scratch/screens/show3d_recent.png, scratch/screens/show3d_viewer.png (+ the suite's panel_* and viewer_* shots)

## Changed lines (git diff --numstat, 21:31)
- Non-test app code: catalog.py +33/-1, connector.py +149/-5, envelope.py +1, errors.py +3, panel/index.html +5, panel/panel.css +5, panel/panel.js +54, docs/agent_guide.md +1 => **+251 / -6**
- Test infra: panel_tests/run_tests.js +57, panel_tests/mock_bridge.js +13/-3
- New test file: connector/test_show3d.py (217 lines)
- opencode.json was already modified before this session (+26/-4) — untouched by me.

## Compliance notes
- Display only: view.load reads view.* and uploads copies; nothing feeds the engine; no *.nc is uploaded or written by any new code (posted programs untouched; byte-identical guarantee untouched).
- No auto-start anywhere: the only view.load trigger is a Show 3D button click (test "no auto-start on open").
- No existing test or assertion was edited; no gate relaxed; no bypass flags; nothing installed; panel not published; no contact with STEVE; no run-retention changes; no Core Front job; nothing >10 min on the small lane (longest: 45 s panel suite, 37 s E2E).
- Lock files in /private/tmp/claude-502 never touched.
- The one interaction the brief flagged (exact event-list pin in test_enroll_confirm_run) did NOT break: it passes unchanged (see Event-order decision above).

End: Wed Oct 28 21:31 MST 2026 (started 21:19; ~13 min of the 45 min budget). Not committed.
