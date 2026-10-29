# Task VIEW3D-IMG: attach rendered 3D pictures (view_iso.png, view_top.png) to every run. Display only. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough or chain. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh). If a run would exceed 10 min,
don't start it; write what you would have run into the results file.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances, with ONE coordinator-approved exception:
the three exact upload pins in connector/test_connector.py (test_enroll_confirm_run file_names(501), test_check_program_ok
file_names(910), test_two_programs_stock_carries_forward file_names(913)) and the exact result["files"] pin in
TestRestPass::test_rest_chain_argv grow by "view_iso.png", "view_top.png" in their real order - exact lists, nothing else changed.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT edit verify/,
engine/ or opencode.json; install NOTHING; display only (nothing feeds the engine); posted programs (*.nc) BYTE-IDENTICAL; a picture
failure must never fail a run (same rule as view.bin: drop the files, one-line note in run.log, gates/check.json untouched); do
NOT publish the panel or contact STEVE.
SCRATCH: scratch files only in /Users/James/ai-sandbox/stevecam-v3i/scratch/ - never /tmp.
RESULTS: create connector/VIEW3DIMG_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and
what it printed. Report only numbers you measured, name only tests that exist, give real clock times (`date`).
FRESH session, TIME BUDGET 45 min, HARD STOP 70 min (run `date` at start and check it). Worktree /Users/James/ai-sandbox/stevecam-v3i,
branch view3d-img at the commit carrying this brief (= main 42a39d7 + brief). Report changed non-test line counts.
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Connector test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- connector/view.py (VIEW3D, merged) writes view.bin/view.json per run; runner.py's _build_view wraps it (failure -> view.*
  dropped, note in run.log). Reuse view.json/view.bin as the image source (decode with the header: nodata 65535, offset/scale).
- Libraries already present, NO installs: the connector runs on /opt/homebrew/bin/python3 (numpy 2.4, PIL 12.1, NO
  matplotlib); the engine python /Applications/VibeCAD.app/Contents/Resources/bin/python has matplotlib 3.10 and is already
  used through a subprocess for preview.png (verify/zmap.py write_png, called by runner with --png). Either render in a
  subprocess with the engine python + matplotlib (like preview.png), or in-process with PIL + numpy. Your choice; say why.
- Agents receive a run's png files as images (up to 4 per answer, scaled to <= 1600 px); STEVE attaches run files to the run
  whoever starts it. The pictures are what James and his agents see for agent-started runs.
- A real Core Front view.bin/json sample is in scratch/view_cf.{bin,json} (3.7 MB; 561x376 grid, 4 programs) - not for git
  (James's part data stays out of git); use it for a local check of render time and readability only.
## Item
1. Render two PNGs per run from view.bin/view.json: view_iso.png (an angled 3D view) and view_top.png (top view), each
   ~1600 px on the long side and readable at that size: the part shaded; the stock left as a heat map with a colour key in mm
   (below-part in red, and keyed as such); toolpaths thin and see-through, coloured per program with a legend naming each
   program/op and its tool (from the run's result/check data you already have); check.json markers drawn and NUMBERED,
   with the same numbers listed in a small caption next to their codes. Register both as run files of adaptive_rough,
   slope_split_finish and check_program after view.json; failure-tolerant as above.
RED TESTS (connector/test_view3dimg.py; write first, run on the UNCHANGED code, paste numbers):
 (a) test_view3dimg_written_readable: on a fake-spawn run (test_toollib._fake_spawn) and on the committed synthetic fixture
     connector/testdata/view_fixture.*, both PNGs exist, are valid PNGs, long side 1500-1700 px, non-blank (distinct colours
     > 20), deterministic bytes across two renders, each <= 3 MB; registered in result["files"] after view.json.
 (b) test_view3dimg_failure_never_fails_the_run: forced render failure -> run succeeds, view_*.png absent from result["files"]
     and the uploads, check.json and gates unchanged, a one-line note in run.log; view.bin/view.json still present.
 (c) test_view3dimg_markers_numbered: a fixture with 2 markers -> the caption lists "1" and "2" with their codes (check the
     text you render, e.g. by also writing the caption strings into view.json or a returned dict - no OCR).
MUTATIONS (scratch copies; each must make a test fail by a MEASURED value - paste it): M1 render a blank image, M2 drop the
failure guard, M3 non-deterministic output (e.g. a timestamp in the PNG).
AT-RISK (must stay green; run ALL, paste exit codes): connector/test_view3d.py, connector/test_toollib.py, connector/test_track2.py,
connector/test_flload_conn.py, connector/test_rrstock2.py, connector/test_tlg1.py, connector/test_panel_inputs.py, and
connector/test_connector.py -k "rest_chain_argv or enroll_confirm_run or check_program_ok or two_programs_stock_carries_forward".
## connector/VIEW3DIMG_RESULTS.md: change (file:line), line counts, red tests before/after, mutation table, render time and PNG
sizes on the fixture AND on scratch/view_cf (local only), PASTED exit codes, and the paths of the CF PNGs you rendered to
scratch/. Then stop.
