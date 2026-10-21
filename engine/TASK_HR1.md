# Task HR1: per level, emit the hug rings AFTER that level's Adaptive2d regions. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ (read and run it only). Edit engine/rough.py and engine/test_engine.py (add a test) only. Do NOT touch
opencode.json. Budget: about 40 changed lines plus the test; if it overruns ~60, STOP and report why.
Change NOTHING else: links and rapids keep going through the existing verified paths (retract_to / enter_at /
descend_feed / link checks) unchanged; ramp angle, helix, side entries, clip logic untouched.
Report ONLY numbers you produced this session from files under /Users/James (this worktree:
/Users/James/ai-sandbox/stevecam-hr1, branch hr1 = main 9ba2f88). Long runs: nohup + short polling; never end your turn
while one runs. ONE-JOB SLOT - EVERY heavy run (engine, zmap, pytest, test_engine, test_finish) goes through
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
then poll the log. Never run two at once, never run one outside the slot.

## The problem (measured by the supervisor on main's Core Front rough)
engine/rough.py, per level: regions = _run_a2d(...) then regions.extend(hug_regions(...)); the RT travel ordering
(nearest-neighbour over `cand`, "order" list) then interleaves the hug rings with the a2d regions. For 808 of the 970
full-width hug-ring windows (876.8 mm) an a2d centre passes within R of the ring (median 1.67 mm away) but only AFTER
the ring in NC order, so the ring slots full width at the full stepdown (18.6 mm at Z 42.354, 7.05 at 35.306).
With the a2d regions first, the ring is the thin skim R4 intended.

## Change
Per level: order all a2d regions exactly as today (NN among them), then ALL hug-ring regions after them, NN among the
rings starting from the position after the last a2d region. (n_a2d = len of _run_a2d's result splits the list.)
Test (engine/test_engine.py): on a synthetic level with an island and a2d territory, assert in the emitted program that
no hug-ring cutting move at a Z comes before an a2d cutting move at the same Z whose tool disk it touches (or simply that
every ring move at that Z follows the last a2d move at that Z). Must fail on main's code.

## Judge (ZE2 zmap = this worktree's verify/zmap.py)
Core Front T13: engine.cli rough --step samples/core_front_setup.step --stock -128.651 128.651 -82.55 82.55 0.0 60.96
  --tool flat:12.686:0.0 --floor 24.765 --leave 0.381 --stepdown 19.05 --optimal-load-mm 2.032 --stepup 1.905
  --hf out/core_front_setup_hf.npy --min-rest 0.5 ; zmap --part out/cf_hf01_z5b.npy --tool flat --dia 12.686
  --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438 --jobs 6 --ae2-dump out/<name>_ae2.json
Test block: engine.cli rough --step samples/test_block.step --stock -50 50 -40 40 0 38 --tool flat:12.686 --floor 20
  --leave 0.381 --final-zmin 20.381 --stepdown 19.05 --optimal-load-mm 2.032 --hf out/test_block_hf_0.5.npy ;
  zmap --part out/test_block_hf_0.1.npy --tool flat --dia 12.686 --stock -50 50 -40 40 0 38 --engage-max 2.438
  --ae2-dump out/<name>_ae2.json
BEFORE values (main, same commands): Core Front out/ze2_main_ae2.json (+ owners from out/ov0_cf_labels.json, which
match main's program byte for byte); test block out/hb1_tb_before_ae2.json. Owners AFTER: the ring moves are the
regions you append after a2d - tag them yourself in your own analysis script under out/ (no engine change for tags).
PASS (both parts):
- hug-ring full-width (ae_eff >= 0.9*12.686 and a > 0.5) length <= 170 mm on Core Front; report test block too
- no owner's overload length (ae_eff > 2.4384, a > 0.5) goes up vs before
- ring ae_eff p95 and max (all ring windows) - report
- zmap gouges / rapid collisions / axial plunges / outside_grid = 0
- cycle time before vs after (report)
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python
  /Applications/VibeCAD.app/Contents/Resources/bin/python, as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, ALL via the slot.
Write engine/HR1_RESULTS.md with every number and the exact commands. Then stop.
