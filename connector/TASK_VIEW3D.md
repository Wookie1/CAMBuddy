# Task VIEW3D: a 3D viewer in the SteveCAM panel (WebGL, automatic 2D fallback). Display only. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough or a Core Front chain. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh). If a run would
exceed 10 min, don't start it; write what you would have run into the results file. The supervisor measures the CF view.bin.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT edit verify/,
engine/ or opencode.json; install NOTHING (no npm/pip installs, no vendored libraries such as three.js - plain WebGL/Canvas you
write); nothing in view.bin may feed engine planning (display only); posted programs (*.nc) must stay BYTE-IDENTICAL; do NOT
publish the panel to STEVE or contact any server (that is James's action).
SCRATCH: scratch files only in /Users/James/ai-sandbox/stevecam-v3d/scratch/ - never /tmp.
RESULTS: create connector/VIEW3D_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and what
it printed. Report only numbers you measured, name only tests that exist, give real clock times (`date`).
CONTINUE: continue from your plan; don't stop before every red test exists and has run on the UNCHANGED code, and every test below
has run.
FRESH session, TIME BUDGET 60 min, HARD STOP 90 min (run `date` at start and check it). Worktree /Users/James/ai-sandbox/stevecam-v3d,
branch view3d at the commit carrying this brief (= main 7326fec + brief). Report changed non-test line counts.
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Connector test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"
Panel tests (Playwright with this Mac's installed Chrome; nothing to install), from panel_tests/:
  NODE_PATH=/Users/James/.hermes/hermes-agent/node_modules /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh node /Users/James/ai-sandbox/stevecam-ops/pw_chrome.js run_tests.js
  (main: 38 passed, 0 failed, ~40 s; SCREENS=<dir> sets where screenshots go - use scratch/screens)

## Facts (supervisor)
- STEVE panels (docs/steve_connector_protocol.md "Panels"): sandboxed iframe, no network; data only via postMessage to STEVE.
  connector/panel/panel.js `call("run.file", {id, name})` returns a Blob of a file of a run the panel started (it already loads
  preview.png and check.json this way, ~L886-910). Panel bundle limit: <= 2 MB, <= 50 files. Run files: <= 20 per run, <= 50 MB
  each. A panel can show files only for runs it started: on any other run the viewer shows a plain note instead.
- The runner registers each action's files in connector/runner.py: adaptive_rough ~L640 ("rough.nc", "check.json",
  "preview.png"), check_program ~L867, slope_split_finish ~L1434. Each action already runs verify.zmap (the connector may import
  verify for DISPLAY data); where a zmap call lacks --stock-out, add it to that same call (no extra judge pass) to get the final
  judged stock.
- panel_tests/run_tests.js already enforces no network, no storage/cookies/popups, no navigation, no console errors, with a mock
  STEVE parent (mock_parent.html / mock_bridge.js) that serves run files; add new tests there in the same style.
## Items
1. connector/view.py: write view.bin (+ view.json header: version, grid x0/y0/cell/nx/ny, z offset/scale, per-program point
   counts, byte offsets, units) for each cutting/check run, from data the run already has:
   - part heightfield (the run's hf_zmap) and the final judged stock (zmap --stock-out), both downsampled to 0.5 mm by a
     conservative rule (part: max; stock: min within the cell is fine - say which), stored uint16 (z = offset + q*scale,
     scale <= 0.01 mm);
   - each posted program's path (verify.zmap.parse_gcode + its arc resolution), feed vs rapid flagged, decimated so every
     dropped point lies within 0.05 mm of the kept polyline, float32, capped per program (state the cap; downsample further
     only by raising the tolerance, and record the tolerance used in view.json);
   - check.json attention items as markers (code, xyz).
   Register view.bin/view.json as run files of adaptive_rough, slope_split_finish and check_program. Total <= 8 MB target.
2. connector/panel/viewer.js (+ minimal panel.js/index.html/panel.css hooks): a "3D" view of a selected finished run started by
   the panel: WebGL (orbit/pan/zoom, layer toggles: part, stock-left heat map with below-part in red, each program's path,
   markers; STEVE light/dark). If canvas.getContext("webgl") is null, an automatic 2D fallback: height-shaded top view of
   stock-left plus one section slice (X or Y, draggable), same data. Runs not started by the panel: a plain note.
RED TESTS (write first, run on the UNCHANGED code, paste numbers):
 (a) connector/test_view3d.py::test_view3d_file_written_and_bounded (a fake-spawn run as in connector/test_rrstock2.py /
     test_toollib._fake_spawn, plus a small real scene where cheap): view.bin/view.json registered and written; header schema;
     size cap; deterministic bytes (two runs equal); heightfield round-trip error <= scale/2 + conservative-rule bound; every
     source path point within the recorded tolerance of the decimated polyline (densely sampled). Must FAIL on main (no file).
 (b) connector/test_view3d.py::test_view3d_programs_byte_identical: the posted *.nc of a fake/small run are byte-identical with
     and without the viewer change (compare against a git-archive copy of 7326fec or a stored hash).
 (c) panel_tests: "viewer: WebGL draws non-blank canvas from a fixture view.bin" (pixel check), "viewer: forced 2D fallback"
     (make getContext('webgl') return null in the page) draws a non-blank 2D canvas, "viewer: non-panel run shows the note",
     toggles change pixels, no network/storage/console errors, "panel bundle <= 2 MB". Screenshots of WebGL and fallback saved.
MUTATIONS (scratch copies; each must make a test fail by a MEASURED value - paste it): M1 widen the decimation tolerance (e.g.
0.5 mm) without recording it, M2 drop the stock layer, M3 break the uint16 scale (e.g. scale x10).
AT-RISK (must stay green; run ALL, paste exit codes): the whole panel_tests suite (38 existing + new), connector/test_toollib.py,
connector/test_track2.py, connector/test_flload_conn.py, connector/test_rrstock2.py, connector/test_tlg1.py, connector/test_panel_inputs.py.
## connector/VIEW3D_RESULTS.md: change (file:line), line counts, red tests before/after, mutation table, panel bundle size,
view.bin size on the test scenes, PASTED exit codes, screenshot paths. Then stop.
(Supervisor: CF chain run's view.bin size and programs byte-identical; full suites; screenshots WebGL + fallback.)
