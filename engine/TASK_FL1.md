# Task FL1: the finish and the rest pass respect floor_z in EVERY pass type. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ (read and run it only). Edit engine/finish.py and engine/test_finish.py (add tests) only. Do NOT touch
opencode.json. Budget: about 40 changed lines plus tests; if it overruns ~60, STOP and report why.
Report ONLY numbers you produced this session from files under /Users/James (this worktree:
/Users/James/ai-sandbox/stevecam-fl1, branch fl1 = main 87a7057). Long runs: nohup + short polling; never end your turn
while one runs. ONE-JOB SLOT - EVERY heavy run (engine, zmap, clcheck, pytest, test_engine, test_finish) goes through
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
then poll the log. Never run two at once, never one outside the slot. If you are blocked, write the question into
engine/FL1_RESULTS.md and stop - do not wait for an answer.

## The bug (measured by the supervisor)
The runner passes `--floor 24.765` to `engine.cli finish`, but engine/finish.py uses floor_z ONLY as the waterline
(steep pass) bottom (`ztop, zbot = zmax, floor_z`). The shallow/parallel passes ignore it: the interim FE2 finish has
6,776 feed moves below Z 24.765 (min 19.685), into stock the rough never cut (the rough stops at its floor), e.g. at
(126.33, -29.05). 197 of its 230 ball axial-plunge (ZB) violations are there.

## Rule
In every pass type - shallow/parallel, steep/waterline, rest, links and entries - a CL point whose tool-tip Z is below
floor_z is DROPPED and the pass is split there; it is NEVER raised to the floor (same rule as S4: unreachable points
are dropped, never moved). Links between the split pieces go through the existing verified link paths, unchanged.
Find the one place every pass's CL points go through (or the fewest places) and apply it there.

## Tests (engine/test_finish.py)
A part surface that dips below the floor produces no feed move below the floor (finish AND rest), and the points above
the floor are still cut (the pass is split, not dropped wholesale). Must fail on main's code.

## Judge - the interim chain (templates: out/judge_template.py, out/zrough_template.py - adapt the paths to THIS
worktree; this branch has no --ramp-angle-deg flag, drop it; use --stock-from out/interim_rough_engine_stock.npy)
Finish: engine.cli finish --stl out/interim_model.stl --tool ball:9.525 --stepover 0.3 --stepdown 0.3
  --slope-threshold 40 --floor 24.765 --cut-feed 3429 --ramp-feed 1270 --post-grid-mm 0.001
  --stock-from out/interim_rough_engine_stock.npy ; post as T20 program 1002 (template).
Rest: as the template (T33 ball 3.142, --rest-from the zmap finish stock), post T33 program 1004.
zmap chain: rough out/interim_rough.DO_NOT_RUN.nc (flat 12.686) -> finish (ball 9.525 corner 4.7625) -> rest (ball
3.142 corner 1.571), part out/interim_part_hf01.npy, exactly as the template; exact clcheck engine/probe_clcheck.py.
Run BEFORE (main's code, unchanged) and AFTER for the finish and the rest. Report:
- feed moves (G1/G2/G3) below floor_z - 0.001 in the POSTED finish and rest: after must be 0 (count them with your own
  parser of the posted .nc, and also report main's count)
- ZB axial plunges (ball, 0.5 mm floor) on the finish and the rest, before vs after (expected after ~33 on the finish)
- zmap gouges / rapid collisions / holder / over-flute / outside_grid = 0; exact clcheck below_cl 0 on both
- coverage before vs after: zmap leftover / within_0p5mm_fraction keys of the finish and the rest check json
- cycle time before vs after, finish and rest
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python
  /Applications/VibeCAD.app/Contents/Resources/bin/python, as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, all via the slot.
Write engine/FL1_RESULTS.md with every number and the exact commands. Then stop.
