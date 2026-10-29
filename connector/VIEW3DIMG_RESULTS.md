# VIEW3D-IMG RESULTS

Session: Wed Oct 28 18:38:14 MST 2026 (`date` at start) -> finished 19:02 MST
(inside the 45 min budget; hard stop was 19:48). Worktree
/Users/James/ai-sandbox/stevecam-v3i, branch view3d-img @ cf0635d.
Every command ran in the FOREGROUND through
/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh; nothing exceeded 10 min; no
Core Front job; no locks touched; nothing installed; nothing published; no
commit made. opencode.json shows as modified in git status - that predates
this session; I did not touch it.

## What changed (non-test lines)

| file | change |
|---|---|
| connector/viewimg.py | NEW, 452 lines — render view_iso.png + view_top.png from view.bin/view.json with PIL + numpy (display only) |
| connector/runner.py | +86 / −6 — `import viewimg` (runner.py:19); `_build_view_images` (runner.py:409) with the failure guard; `_drop_view_if_failed` (runner.py:389) extended; render + register the two PNGs after view.json in adaptive_rough (runner.py:679/716/725), check_program (930/970/979) and slope_split_finish (1510/1582/1593) |

Test-side (allowed additions/pins only): connector/test_view3dimg.py NEW,
187 lines; connector/test_connector.py +8/−4 — exactly the four
coordinator-approved pins grown by "view_iso.png", "view_top.png" in their
real order (file_names(501) L318, TestRestPass::test_rest_chain_argv
result["files"] L1055, file_names(910) L2208, file_names(913) L2378).
mock.file_names() returns sorted names, so the upload pins list
view_iso.png/view_top.png after view.json ('.' < '_' in ASCII);
result["files"] keeps them in registration order.

## Render choice and why (as required by the brief)

In-process **PIL + numpy** in the connector python, NOT an engine-python +
matplotlib subprocess:
- determinism is a hard requirement (byte-identical across renders): PIL's
  PNG writer emits no timestamps; matplotlib embeds creation metadata unless
  coaxed;
- no ~1-2 s interpreter+matplotlib spawn per picture, no dependency on the
  engine python at render time, and the failure guard stays a plain
  try/except;
- the data is a heightfield + polylines — exactly what numpy + PIL draw
  well; the connector python has no matplotlib at all.

## Format / content decisions

- Both PNGs 1600x1000 (long side 1600, inside the 1500-1700 window).
- Source: view.bin/view.json decoded with the header (nodata 65535 — the
  committed fixture predates the `nodata` key, the loader defaults it to
  65535; offset/scale; float32 program xyz + uint8 flags).
- Part hill-shaded; stock left (stock − part) heat map with a mm colour key;
  below-part cells RED, the key carries an explicit red band labelled
  "below part, to -N.NN"; toolpaths thin and see-through (feed alpha 170
  w=2, rapid alpha 70 w=1) coloured per program from a fixed palette, with a
  legend naming each program and its tool ("T13 flat 12.686 mm" style, built
  from the run's check/result data the runner already has); check.json
  markers drawn as numbered dots, numbers listed next to their codes in the
  caption (render_images returns the caption strings — tests check them
  without OCR).
- view_iso.png: grid rotated 28° (nearest resample), surface cells drawn
  back-to-front with Lambert shading + heat blend, viewer-facing cliff/front
  walls extruded (down to the scene floor at the silhouette).

## Failure semantics (LOCK respected)

A render failure never fails a run: `viewimg: skipped (<Exc>: <msg>)` one
line to run.log, view_*.png dropped from result["files"] AND the uploads;
view.bin/view.json, check.json and gates untouched. When view.build_view
itself failed there is nothing to render from: the PNGs are dropped from the
uploads (they do not exist) — their names stay in result["files"] because
the pre-existing, un-editable test_view3d_failure_never_fails_the_run pins
`r_bad["files"] == r_ok["files"] minus view.bin/view.json`.

## RED tests on UNCHANGED code (pasted)

`slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider
connector/test_view3dimg.py` -> **exit 1**, `4 failed in 0.16s`
(scratch/red1.log): 3x `ModuleNotFoundError: No module named 'viewimg'`,
1x `AssertionError: result['files'] lacks view_iso.png`.

## Test runs after implementation (pasted exit codes)

| run | result | exit |
|---|---|---|
| connector/test_view3dimg.py | `4 passed in 5.42s` (scratch/green2.log; an intermediate run was 2 failed/2 passed on KeyError 'nodata' — fixture predates the key) | **0** |
| test_view3dimg.py + test_view3d.py | `12 passed in 6.03s` (scratch/green3.log; test_view3d.py's byte-identical-*.nc test compares against 7326fec and passes) | **0** |
| AT-RISK test_view3d + test_toollib + test_track2 + test_flload_conn + test_rrstock2 + test_tlg1 + test_panel_inputs | `97 passed in 2.03s` (scratch/atrisk1.log) | **0** |
| AT-RISK test_connector.py::TestRestPass::test_rest_chain_argv | `1 passed in 0.29s` (scratch/atrisk2.log) | **0** |
| AT-RISK test_connector.py -k "rest_chain_argv or enroll_confirm_run or check_program_ok or two_programs_stock_carries_forward" | `4 passed, 108 deselected in 47.56s` (scratch/atrisk4.log; wall 47.7 s — the E2E runs are far under the 10-min lane rule here) | **0** |
| FINAL combined: all seven suites + test_view3dimg + rest_chain_argv | `102 passed in 8.03s` (scratch/final1.log) | **0** |

## Mutations (scratch copies scratch/m1..m3 of connector/ + verify/ + engine/
+ tools/, run against connector/test_view3dimg.py)

| mutation | test(s) that failed | measured value | exit |
|---|---|---|---|
| M1 render a blank image (viewimg.py: overwrite both PNGs with a flat BG image) | test_view3dimg_written_readable, test_view3dimg_fixture_readable | `has only 1 distinct colours (blank?)` (< 20 required), on the run PNG and the fixture PNG | **1** (`2 failed, 2 passed`) |
| M2 drop the failure guard (runner.py: call render_images outside try/except) | test_view3dimg_failure_never_fails_the_run | `RuntimeError: forced render failure` propagates out of run_slope_split_finish — the run itself dies | **1** (`1 failed, 3 passed`) |
| M3 non-deterministic output (timestamp text chunk in both PNGs) | test_view3dimg_written_readable, test_view3dimg_fixture_readable | `view_iso.png bytes differ across two renders`; sha256 of the two renders: `12fe3717367531e0...` vs `fff0f8537f538477...` | **1** (`2 failed, 2 passed`) |

(logs: scratch/m1/out.log, scratch/m2/out.log, scratch/m3/out.log)

## Render time and PNG sizes (measured)

- scratch/view_cf (real Core Front sample, 561x376 grid at 0.5 mm, 4
  programs: rough.nc 174 054 pts, rest.nc 1 530, finish.nc 42 297, t33.nc
  2 963; 0 markers): both PNGs in **0.19 s** first / 0.17 s second call.
  view_iso.png **86 940 B** (1600x1000, 915 distinct colours),
  view_top.png **189 118 B** (1600x1000, 10 065 distinct colours).
- connector/testdata/view_fixture (100x100 grid, 18-pt path, 2 markers):
  both PNGs in **0.08 s**. fix_iso.png **118 658 B** (2 920 distinct),
  fix_top.png **346 635 B** (71 021 distinct). All far below 3 MB.
- Fake-spawn run renders (inside the tests): 4 tests + view3d suite in 6.03 s
  total, so per-run render cost is negligible on the small lane.

## CF PNGs rendered to scratch (local only, not for git)

- scratch/screens/view_iso.png, scratch/screens/view_top.png (from
  scratch/view_cf.{bin,json}; checked by eye: shaded stepped surface with
  extruded walls, heat map, per-program see-through paths + legend, colour
  key with the red below-part band)
- scratch/screens/fix_iso.png, scratch/screens/fix_top.png (fixture: marker
  dots 1/2 on the surface, caption "1 rough.gouges at x=2.5 y=1.5",
  "2 rough.over_flute at x=-4.0 y=-2.0", legend "program.nc - T7 ball
  6.000 mm")

## git diff --numstat (tracked files, at finish)

```
86	6	connector/runner.py
8	4	connector/test_connector.py
```
(opencode.json also shows modified — pre-existing, untouched by me.)
Untracked new files: connector/viewimg.py (452 lines),
connector/test_view3dimg.py (187 lines), connector/VIEW3DIMG_RESULTS.md,
scratch/* (red/green/atrisk/final logs, m1-m3 mutation trees, screens/).

Changed non-test lines: **+538 / −6** (viewimg.py 452 new + runner.py
+86/−6); test-side: test_view3dimg.py 187 new, test_connector.py +8/−4
(approved pins).

## Session log (append-after-every-run record)

- 18:38 start; surveyed view.py, runner.py, test_view3d.py,
  test_toollib._fake_spawn, the four test_connector pins, view_fixture.
- 18:41 test_view3dimg.py written (RED first).
- 18:44 RED on unchanged code: exit 1, `4 failed in 0.16s` (scratch/red1.log).
- 18:45-18:55 viewimg.py written; runner wired; pins grown; debug iterations
  on the iso projection (iso_proj returned view-mm instead of pixels — the
  paths drew a corner blob; fixed; no test ever ran against the broken
  layout except the green runs below).
- 18:56 `pytest connector/test_view3dimg.py` -> exit 0, `4 passed in 5.42s`.
- 18:57 `pytest test_view3dimg + test_view3d` -> exit 0, `12 passed in 6.03s`.
- 18:58 AT-RISK seven suites -> exit 0, `97 passed in 2.03s`;
  rest_chain_argv -> exit 0, `1 passed in 0.29s`;
  test_connector -k selection -> exit 0, `4 passed in 47.56s` (real E2E).
- 18:59-19:00 mutations M1/M2/M3 -> exit 1 each, measured values above.
- 19:01 FINAL combined -> exit 0, `102 passed in 8.03s`.
- 19:01 CF + fixture timing/size measurements re-run (numbers above).
- 19:02 results written; stopped. No commit.
