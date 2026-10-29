# VIEW3D RESULTS

Session: Wed Oct 28 14:39:39 MST 2026 (`date` at start) → finished 14:59 MST (inside the
60 min budget). Worktree /Users/James/ai-sandbox/stevecam-v3d, branch view3d @ d45cfa6.
Every command ran in the FOREGROUND through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh;
nothing exceeded 10 min; no Core Front job; no locks touched; nothing installed; nothing
published; no commit made.

## What changed (non-test lines)

| file | change |
|---|---|
| connector/view.py | NEW, 235 lines — view.bin/view.json builder (display only) |
| connector/runner.py | +65 / −15 — `import view`; `--stock-out` added to the judging zmap call of adaptive_rough (stock_after_rough.npy), of EVERY check_program program (stock_after_<pname>.npy) and of the slope chain's rest zmap (stock_after_rest.npy; finish now always exports stock_after_finish.npy); build + register view.bin/view.json for all three actions |
| connector/panel/viewer.js | NEW, 412 lines — WebGL viewer (orbit/pan/zoom, layer toggles part / stock-left heat map with below-part red / per-program path / markers, STEVE light/dark) + automatic 2D fallback (height-shaded top view of stock left + draggable X-section strip) |
| connector/panel/panel.js | +3 — hooks: `SteveCAMViewer.attach` in showResults (runs the panel started), `SteveCAMViewer.noteInto` in paintCheckRun (runs it did not start), `SteveCAMViewer.theme()` in applyTheme |
| connector/panel/index.html | +1 — `<script src="viewer.js">` |
| connector/panel/panel.css | +8 — .v3d styles (var(--…), theme-following) |

Test-side (allowed additions only): connector/test_view3d.py NEW; panel_tests/run_tests.js
+104 (6 new viewer tests + additive `opts.init` hook in Env.open + viewFixture/canvasFp
helpers); panel_tests/mock_bridge.js +2 (serve view.bin/view.json blobs when a test config
provides them); connector/testdata/view_fixture.{bin,json} new fixtures (generator:
scratch/gen_view_fixture.py).

## Format decisions (as required by the brief)

- grid: both heightfields downsampled to **0.5 mm** — part keeps the cell **max**
  (conservative), stock keeps the cell **min** (conservative); stored uint16,
  z = offset + q*scale with fixed **scale = 0.01 mm/step** (≤ 0.01; a taller-than-655 mm
  scene would record a larger scale in view.json — not hit in any test scene).
- paths: verify.zmap parse_gcode + resolve_moves + its own arc sampling (_move_samples,
  ≤ 0.125 mm spacing at cell 0.5); feed/rapid flagged per point; flag changes are forced
  anchors; Douglas-Peucker decimation, **tolerance 0.05 mm**, raised by doubling only to
  fit the **cap of 200 000 points per program**, and the tolerance actually used is
  recorded per program in view.json; points float32.
- markers: gate entries with count>0 and a worst_xy (gouges, rapid_collisions, over_flute,
  holder_hits, axial_plunges) → {code, x, y, z} in view.json (xyz triple also in view.bin).
- view.bin: part uint16, stock uint16, per program float32 xyz + uint8 flags, markers
  float32; offsets in view.json; deterministic bytes; target cap MAX_BYTES = 8 MiB.

## RED tests on UNCHANGED code (pasted)

- `slot_m4.sh … pytest -q -p no:cacheprovider connector/test_view3d.py` → **exit 1**,
  `5 failed, 1 passed` (5 × ModuleNotFoundError: No module named 'view' etc; the 1 pass is
  test_view3d_programs_byte_identical, which compares 7326fec against itself on main).
- `ONLY='viewer:' … node pw_chrome.js run_tests.js` → **exit 1**,
  `1 passed, 5 failed, 44 total` (4 × "fixture view.bin/view.json missing", 1 × note-test
  waitForFunction timeout; the 1 pass is the bundle-size test, which re-checks the
  existing static limit and cannot fail on main).

## Test runs after implementation (pasted exit codes)

| run | result | exit |
|---|---|---|
| connector/test_view3d.py (6 tests) | `6 passed in 0.54s` | **0** |
| panel ONLY='viewer:' (6 new tests) | `6 passed, 0 failed` | **0** |
| full panel_tests suite | `44 passed, 0 failed, 44 total (42.8 s)` — 38 existing + 6 new | **0** |
| at-risk: test_toollib + test_track2 + test_flload_conn + test_rrstock2 + test_tlg1 + test_panel_inputs + test_view3d | `95 passed in 1.08s` | **0** |
| scratch/gen_view_fixture.py | fixture written | **0** |

Note: an intermediate run of test_panel_inputs failed once (`KeyError: 'inch'`) because my
own earlier `ONLY=viewer:` panel run truncated connector/testdata/panel_default_inputs.json
(the harness rewrites that file with only the inputs its filtered tests captured). The full
44-test suite regenerated it byte-identical to HEAD; the re-run above is green.

## Collateral (not at-risk, not editable per TESTS rule)

`connector/test_connector.py::TestRestPass::test_rest_chain_argv` asserts
`result["files"] == ["rough.nc","finish.nc","rest.nc","check.json","preview.png"]`
(test_connector.py:1055) — exact equality with the OLD file list. The brief mandates
registering view.bin/view.json, so this assertion must gain them; I was forbidden from
rewriting existing tests, so I left it. Measured: `1 failed`, "Left contains 2 more items,
first extra item: 'view.bin'", **exit 1**. The E2E exact-equality file list in the same
file (test_enroll_confirm_run, ~L318) will be affected the same way; that E2E run exceeds
the 10-minute small-lane rule so I did not start it.

## Mutations (scratch copies of connector/, run against the same tests)

| mutation | test(s) that failed | measured value | exit |
|---|---|---|---|
| M1 decimation tol widened to 0.5 mm, still recorded as 0.05 | test_view3d_path_decimation_within_tolerance | `stored polyline deviates 0.3360 mm > recorded tolerance 0.0500 mm` | **1** |
| M2 stock layer dropped (stock grid written as part grid) | test_view3d_file_written_and_bounded, test_view3d_heightfield_roundtrip_bounds | stock decodes to 0.4 where −1.0 ± 0.005 expected (1.4 mm off); round-trip min mismatch | **1** |
| M3 uint16 scale ×10 (SCALE = 0.1) | test_view3d_file_written_and_bounded, test_view3d_heightfield_roundtrip_bounds | `assert 0.1 <= (0.01 + 1e-12)` | **1** |

(logs: scratch/m1/out.log, scratch/m2/out.log, scratch/m3/out.log; the byte-identical test
was deselected there — it needs the real git repo)

## Sizes

- panel bundle: **7 files, 143 836 bytes** (limit 50 files / 2 MB) — measured by the suite.
- view.bin + view.json on the test scenes: fake adaptive_rough **256 B + 398 B**;
  fake slope_split_finish **16 B + 531 B**; panel fixture (100×100 grid at 0.5 mm,
  real check_ok.nc path decimated 3297→18 pts at 0.05 mm, 2 markers) **40 258 B + 543 B**.
  All far below the 8 MB target. The CF chain run's view.bin is for the supervisor to
  measure on Core Front.

## Screenshots

- scratch/screens/viewer_webgl.png (WebGL, 339 distinct colors measured)
- scratch/screens/viewer_fallback.png (forced-2D fallback, 757 distinct colors measured)

## git diff --numstat (tracked files, at finish)

```
1	0	connector/panel/index.html
8	0	connector/panel/panel.css
3	0	connector/panel/panel.js
65	15	connector/runner.py
2	0	panel_tests/mock_bridge.js
104	0	panel_tests/run_tests.js
```
(opencode.json shows as modified in git status — that predates this session; I did not
touch it. connector/testdata/panel_default_inputs.json is byte-identical to HEAD again.)
Untracked new files: connector/VIEW3D_RESULTS.md, connector/view.py,
connector/test_view3d.py, connector/panel/viewer.js, connector/testdata/view_fixture.bin,
connector/testdata/view_fixture.json, scratch/* (gen_view_fixture.py, m1–m3, screens, logs).

## Not done (by design / by rule)

- Core Front view.bin size, full connector suite, CF programs byte-identical check: the
  supervisor's (brief: "The supervisor measures the CF view.bin"; CF lane is theirs).
- test_connector.py's two exact file-list assertions: editing existing tests is forbidden;
  flagged above for the supervisor.
