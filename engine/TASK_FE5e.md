# Task FE5e: ramp tops must be clear of the live stock. Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/. Edit engine/finish.py (and engine/entry_depth.py only if a helper is missing - it is otherwise frozen) and
engine/test_finish.py. Do NOT touch opencode.json. Budget ~80 changed lines plus a test; if it overruns ~130, STOP and
report why. The ramp angle stays 2 deg - NEVER steeper, never a plunge.
Report ONLY numbers you produced this session under /Users/James (worktree /Users/James/ai-sandbox/stevecam-fe5, branch fe5
= e40f664: FE5 + ZB + main 6b931ae merged in). Cite only files that exist and commits `git log` shows. NEVER print NGC/
G-code or other large outputs into your context: use cmp, diff --stat, wc, head -3, grep -n for one line. Long runs: nohup
+ short polling; never end your turn while one runs. ONE-JOB SLOT - every heavy run via
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
If blocked, write the question into engine/FE5e_RESULTS.md and stop. If the bar cannot be reached, SAY SO - never relax.

## Defect (engine/FE5d_RESULTS.md, verified by the supervisor)
engine/finish.py:2192 sizes the ramp from the live depth at the pass start P0 only (d = live.disk_depth(P0); L = d/tan,
:2201) and never checks the stock at the ramp TOP rv[0]. In out/fe5_finish.nc the pass at P0 (-28.57, 17.89, 41.444) has
d 0.70 -> L 20.1 mm; rv[0] = (-8.677, 17.193, 42.145) sits ~2.9 mm under a ridge (live ~45.0), and the link then descends
vertically onto rv[0] (finish.py:2419-2422, emit(1, path[0]...)) - ZB 2.826 at NC line 52593.

## Change
1. Choose the SMALLEST L along the available run for which the ramp top is clear: z0 + L*tan(2 deg) >= live stock at rv[0]
   - 0.25 (the FE5 estimator's live stock, `live`), iterating L along the run.
2. Verify the link's descent onto rv[0] the same way: live depth <= 0.25 over the whole descent column.
3. If no L on that run works: try entering from the pass's OTHER end (reverse the pass, same rule). Else a verified cleared
   side. Else leave the entry exactly as today (so ZB fails on it) and record it in stats (fe5_top_unresolved: x, y, z, d).
   Fail closed; never steeper.
4. The 2-deg chord itself may pass through stock below its top (an allowed <= 15 deg descent): record the max live depth
   along each ramp chord in stats (fe5_chord_max_depth list + max) for the coming ZE2 side-load check on ball programs.

## Test (engine/test_finish.py)
Reproduce the buried-top case synthetically (a pass whose P0 is shallow but whose ramp top lands under a standing ridge):
after FE5e the entry's descent column and ramp top are clear (<= 0.25) or the entry is reported - and the test must FAIL on
e40f664's code.

## Judge (out/fe5_judge.py; it writes out/fe5_finish.nc / fe5_rest.nc - copy BEFORE outputs first)
BEFORE = e40f664's code, run out/fe5_judge.py once, copy its finish/rest programs, stats and zmap json to out/fe5e_before_*.
AFTER = your code, same judge. Report BEFORE vs AFTER:
- finish and rest ZB (ball, > 0.5) count + max, and EVERY remaining finish ZB entry (NC line, x, y, depth) - the bar is that
  only the RR0-zone fragment entries remain (fins at the corner pockets (+-107.8, ~49), the centre-south pocket
  (-0.8, -37.6), bays at X +-71); the entry at (-8.68, 17.19) must be gone
- zmap gates (gouges, rapid collisions, holder / over-flute, outside_grid) 0; exact clcheck (engine/probe_clcheck.py) 0 on
  the POSTED finish and rest; finish and rest cycle times; fe5_top_unresolved; fe5_chord_max_depth max
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, all via the slot.
- Regenerate the finish once more from the FINAL code and cmp it against the one you judged; report.
Write engine/FE5e_RESULTS.md with every number and the exact commands. Then stop.
