# Task RR1b: T20 rest-rough generator. Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ (read and run it only). Edit/add engine/ files (a new engine/rest_rough.py is fine), engine/cli.py (a new
`rest-rough` subcommand), connector/catalog.py + connector/runner.py (parameters + defaults only), and tests. Do NOT
touch opencode.json. Budget ~450 changed lines plus tests; if it overruns ~550, STOP and report why.
Report ONLY numbers you produced this session from files under /Users/James (worktree /Users/James/ai-sandbox/stevecam-rr1b,
branch rr1b = main 98bdb99). Cite only files that exist and commits `git log` shows - never invent a hash. NEVER print NGC/
G-code contents or other large outputs into your context: use cmp, diff --stat, wc and head -3 only. Long runs: nohup +
short polling; never end your turn while one runs. ONE-JOB SLOT - every heavy run via
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
If blocked, write the question into engine/RR1b_RESULTS.md and stop. If the bar cannot be reached, SAY SO - never relax.

## Inputs / decisions
- engine/RR0_RESULTS.md on branch rr0 (read: `git show rr0:engine/RR0_RESULTS.md`): zones, existing-code gaps with
  file:line, strategy. out/rr0_ref/ has its artefacts (stock after main's rough, T20 reach map, excess map, zones).
- James confirmed (use as CONNECTOR DEFAULTS and in judging; engine code takes them as PARAMETERS, no T20 numbers in
  engine code): T20 = 3/8" ball (tools/x7_tools.json #20: dia 9.525, flute 22.225, stickout 46.2, holder BT30-ER20-60),
  aluminium, ae 1.905 mm, stepdown 2.0 mm, S9500, F2280 mm/min, ramp F850 mm/min, rest leave <= 0.2 mm.
- The rest-rough clears every zone (including the closed pockets / membranes over openings) down to the setup floor
  floor_z like everything else; the floor decides scope.
- Reuse what exists: ocl BallCutter + cl_grid / batch_drop (engine/finish.py), compute_rest_mask, waterline/march_level
  slicing, Adaptive2d (engine/rough.py _run_a2d) for clearing where it fits, and the FE5 live-stock estimator: copy
  engine/entry_depth.py and engine/test_entry_depth.py BYTE-IDENTICAL from branch fe5 (`git show fe5:engine/entry_depth.py`,
  commit 8a2a9a0) - do not modify them.
- Seed: the rest-rough starts from the ROUGH's stock (zmap --stock-out of the rough program, or the rough engine's
  --stock-out) - add a --stock-from on the new subcommand; never assume a full block.

## Generator (z-level, restricted to the zones where live stock - T20 finish-ball reach > 0.5 mm, above floor_z)
- levels every `stepdown`, ae <= `ae` (1.905 default); ball CL from OCL BallCutter; every CL point legal against the
  part (clcheck-exact); leave `rest_leave` (0.2) on the part.
- ENTRIES: for each closed pocket/zone report the largest CL circle radius the T20 ball fits at leave 0.2. If r >= 1.903:
  a 2-degree helix + one flat floor circle at the helix bottom at ramp feed (as the rough), depth judged by the FE5
  estimator. Else REPORT that pocket (no entry). No bored or plunge entries (the ZB 0.5 floor stands); zig-zags only if
  their run >= D (9.525). Side entries only through cleared stock (SE2 rule).
- links: rapid-rise + swept rapid check as in the rough.
## Bar (Core Front, the rest-rough program posted as its own T20 program)
- all zmap gates 0 with the T20 geometry: gouges, rapid collisions, outside_grid, shank/over-flute and holder against the
  22.225 flute (--flute 22.225 --shank-dia 9.525 --holder BT30-ER20-60 --stickout 46.2), axial plunges (ball, ZB 0.5) = 0;
  exact clcheck (engine/probe_clcheck.py) 0
- ZE2 on the T20 program (ball): 0 full-width windows at cutting feed; steady ae (p95) <= 1.905; spikes (max) <= 1.2 x 1.905
- then re-judge the chain rough -> rest-rough -> finish (T20, main's finish command with --stock-from) -> small-ball rest
  (T33) with the zmap chain (--stock-in), and report: ZB gate counts on the finish and the rest (> 0.5), what is left over
  0.2 mm above the part (area, volume, max, by zone), cycle times of every program
- per-zone: levels, cut length, time at F2280 / F850; pockets with no legal entry (and their max CL circle r)
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, all via the slot.
- Tests: a synthetic pocket with a 6 mm rest band: rest-rough leaves <= 0.2 mm (+ tolerance) everywhere the T20 reaches,
  0 gouges, 0 axial plunges; a closed pocket too small for r 1.903 is reported, not entered. Each must fail on main.
Write engine/RR1b_RESULTS.md with every number and the exact commands. Then stop.

## Addition (supervisor, before you started)
- The finish's remaining ZB entries are 20 fragment entries inside your zones (fins at the corner pockets (+-107.8, ~49)
  and the centre-south pocket (-0.8, -37.6); bays at X +-71). The chain re-judge must show ALL of them at <= 0.5 mm
  (list each with its depth after the rest-rough).
- Report the rest-rough's leftover above the part in its zones FROM ZMAP (stock after the rest-rough minus part):
  area / volume / max per zone, INCLUDING z-level terraces on shallow areas left by the 2.0 stepdown, since those become
  finish entries.
