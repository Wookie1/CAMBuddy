# Task SHOW3D: "Show 3D" for any recent run (incl. agent-started) via a panel-owned view.load run. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough or chain. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh). If a run would exceed 10 min,
don't start it; write what you would have run into the results file.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only. (If an existing exact
pin of a catalog/event/file list breaks, STOP and report it - do not edit it.)
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT edit verify/,
engine/ or opencode.json; install NOTHING; display only (nothing feeds the engine); posted programs (*.nc) BYTE-IDENTICAL; do NOT
publish the panel or contact STEVE; no run-retention/cleanup changes; NO auto-start of runs from the panel (button only).
SCRATCH: scratch files only in /Users/James/ai-sandbox/stevecam-s3d2/scratch/ - never /tmp.
RESULTS: create connector/SHOW3D_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and what
it printed. Report only numbers you measured, name only tests that exist, give real clock times (`date`).
FRESH session, TIME BUDGET 45 min, HARD STOP 70 min (run `date` at start and check it). Worktree /Users/James/ai-sandbox/stevecam-s3d2,
branch show3d-2 at the commit carrying this brief (= main d3a5bae + brief). Report changed non-test line counts.
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Connector test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"
Panel tests (Playwright with this Mac's installed Chrome; nothing to install), from panel_tests/:
  NODE_PATH=/Users/James/.hermes/hermes-agent/node_modules /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh node /Users/James/ai-sandbox/stevecam-ops/pw_chrome.js run_tests.js
  (main: 45 passed; ONLY='<prefix>' runs a subset; SCREENS=<dir> for screenshots - use scratch/screens)

## Facts (supervisor)
- STEVE panel bridge (docs/steve_panel_bridge.md): run.get/run.file work only for runs the panel STARTED; there is no runs.list.
  A panel can start runs of its own connector's actions (allowed for the panel) and receives the connector's events.
- The connector keeps every run's work dir at <home>/runs/<run_id> (connector.py _run_job ~L309); since VIEW3D/VIEW3D-IMG each
  cutting/check run there has view.bin, view.json, view_iso.png, view_top.png (older runs may have none).
- Actions: catalog.py (ACTIONS, ENGINE_ACTIONS, TOOL_ACTIONS ~L20; CATALOG ~L473 with "actions" and "events"); connector.py
  dispatches ~L229 (_run_job for engine actions, _run_tool_action for tool actions) and uploads a run's files ~L403
  (files dict {name: (path, media)}). Events: connector.py emit_state posts EVENT "engine_state"; event data <= 8 kB.
## Items
1. New action "view.load" {run_id: string}: no document input; validates run_id STRICTLY - format (the connector's own run-id
   format, e.g. digits/uuid; reject anything else), the dir <home>/runs/<run_id> must exist and resolve (realpath) INSIDE
   <home>/runs (no traversal, no symlink escape), and must hold view.bin + view.json (else a plain "no 3D view for that run"
   error). On success it uploads COPIES of that run's view.bin and view.json (and the two PNGs if present) as files of the
   view.load run itself. Runs fast (no engine).
2. New declared event "last_runs": after every cutting/check run ends, post the most recent <= 10 runs
   [{run_id, action, document_id, at, has_view}] (newest first), always < 8 kB (assert it). The panel receives it on open.
3. Panel: a "Recent runs" list from the last_runs event (action, time, "has 3D"), each with a "Show 3D" button that starts
   view.load {run_id} (button click only; disabled until its run ends) and opens the existing viewer on that run's files.
   No auto-start. The existing viewer for panel-started runs is unchanged.
RED TESTS (write first, run on the UNCHANGED code, paste numbers):
 (a) connector/test_show3d.py::test_view_load_returns_run_files: a run dir with view.* -> view.load succeeds and uploads
     byte-identical copies.
 (b) ::test_view_load_refuses_bad_ids: unknown id, malformed ids, "../x", absolute paths, a symlink in runs/ pointing outside,
     a run without view.* -> each refused with a clear code, nothing uploaded, no file read outside <home>/runs.
 (c) ::test_last_runs_event_shape: <= 10 newest first, fields present, json size < 8 kB even with long ids/doc ids.
 (d) panel_tests: "show3d: recent runs list from last_runs event", "show3d: Show 3D starts view.load and draws the viewer"
     (mock serves the view.load run's files), "show3d: no auto-start on open" (no run started without a click).
MUTATIONS (scratch copies; each must make a test fail by a MEASURED value - paste it): M1 drop the traversal/realpath check,
M2 drop the 10-entry cap, M3 auto-start view.load on panel open.
AT-RISK (must stay green; run ALL, paste exit codes): the whole panel_tests suite, connector/test_view3d.py, connector/test_view3dimg.py,
connector/test_toollib.py, connector/test_track2.py, connector/test_flload_conn.py, connector/test_rrstock2.py, connector/test_tlg1.py,
connector/test_panel_inputs.py, and connector/test_connector.py -k "catalog or event or panel".
## connector/SHOW3D_RESULTS.md: change (file:line), line counts, red tests before/after, mutation table, PASTED exit codes,
screenshot paths. Then stop.
