# Task RR1c: rest-rough entries by live depth (enter the zones RR1b reported). Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/. Edit engine/rest_rough.py, engine/cli.py (only if a new parameter is needed), engine/test_engine.py. Do NOT touch
opencode.json, engine/entry_depth.py or engine/test_entry_depth.py (byte-identical copies from fe5 - import, never edit).
Budget ~250 MORE changed lines on top of RR1b's WIP (plus tests); if it overruns ~300, STOP and report why.
Report ONLY numbers you produced this session under /Users/James (worktree /Users/James/ai-sandbox/stevecam-rr1b, branch
rr1b = RR1b's WIP commit, see `git log -3`). Cite only files that exist and commits `git log` shows. NEVER print NGC/G-code
or other large outputs into your context: use cmp, diff --stat, wc, head -3, and rg / sed -n with line ranges - never read
a whole big file. Long runs: nohup + short polling; never end your turn while one runs. ONE-JOB SLOT - every heavy run via
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
pytest runs under /opt/homebrew/bin/python3 (NOT the VibeCAD python - it has no pytest).
If blocked, write the question into engine/RR1c_RESULTS.md and stop. If the bar cannot be reached, SAY SO - never relax.

## Why (engine/RR1b_RESULTS.md)
RR1b's exact-CL map finds 54 zones (6,783 mm2 / ~7,100 mm3) but enters only 3 by helix (centre membrane r_max 5.19, bays
X+-71 r 2.16 / 2.13). It REPORTS everything else - corner pockets zones 53/54 (r_max 1.0), centre-south zone 2 (r 1.0),
flank bands 7/8 (~2,286 mm2 each, r 0.72 / 0.57), zone 49 (r 1.2), small zones - so total rest cut is only 698 mm, and
the finish's 20 fragment entries in those zones stay. RR1b never implemented the brief's side entries.

## Change: entries chosen PER PASS by the pass's live depth (FE5 estimator, engine/entry_depth.LiveStock), in this order
1. live depth <= 0.25: no special entry.
2. in-pass 2-degree ramp sized with FE5e's top-clear rule: the SMALLEST L along the pass whose ramp top is within 0.25 of
   the live stock at that point (z0 + L*tan2 >= live - 0.25), and the link's descent column onto the ramp top verified
   live depth <= 0.25. Thin zones (flank bands, 0.5-1 mm) should mostly land here - no helix needed.
3. zig-zag along the pass or the zone's long CL axis, ONLY if each run >= D (9.525).
4. SE2-verified side entry from stock already cleared at that level (the engine's existing SE2 rule).
5. 2-degree helix + floor circle, r >= 1.903 (today's).
6. else REPORT (zone, r_max, run length, depth). No plunges, no smaller helix, never steeper than 2 degrees.
Record per entry which step it took (stats counts + list).

## Tests (engine/test_engine.py) - each must FAIL on RR1b's WIP code
- a thin band (0.6 mm deep, r_max < 1.903) is now cut via an in-pass ramp, every entry <= 0.5 (ZB);
- a narrow pocket entered from a cleared side (step 4), no helix, no plunge.
Keep RR1b's two tests green.

## Also required (coordinator, after RR1b's chain)
1. RR1b's rest-rough program has 7 RAPID COLLISIONS (out/rr1b/zmap_rest.json) - a hard fail. List each (NC line, XY/Z,
   what it hits) and fix it with the engine's existing rapid-rise + whole-G0 swept check against the LIVE stock. No
   exemptions.
2. At the X+-71 bays the finish's first entry depth only drops 2.14 -> 0.83 mm after the rest-rough (supervisor's estimate:
   ball r 4.7625 tip depth over the disk at (-71.21, -1.21, Z 38.145) and (70.30, -1.21, Z 38.146) against
   out/rr1b/stock_after_rest.npy), although the rest leave is <= 0.2. Explain the leftover at those footprints (z-level
   terrace from the 2.0 stepdown, level set stopping above the bay floor, ball scallop, or the leave) and FIX it so every
   finish-entry footprint inside the rest-rough zones ends <= 0.5 live depth. Report the max leftover above the part per
   zone from zmap.

## Judge (as RR1b's pipeline: out/rr1b/pipeline3.sh / pipeline5.sh flags)
- rest-rough program: zmap gates 0 with the T20 geometry (gouges, rapid collisions, outside_grid, shank/over-flute,
  holder), axial plunges (ball, ZB 0.5) 0; exact clcheck 0; ZE2: cutting-feed full-width 0, p95 ae <= 1.905, max <= 2.286
- chain rough -> rest-rough -> finish (T20, --stock-from) -> rest (T33), zmap --stock-in: finish and rest ZB (> 0.5)
  counts, and EACH of the 20 finish fragment entries (corner pockets (+-107.8, ~49), centre-south (-0.8, -37.6), bays
  X +-71) with its depth after the rest-rough; leftover above the part per zone (area / volume / max, incl. terraces)
- per zone: entry step used, levels, cut length, time; zones still at step 6 (r_max, run, depth)
- cycle times of every program
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, all via the slot.
- Regenerate the final rest-rough program once more from the FINAL code and cmp it against the judged one; report.
Write engine/RR1c_RESULTS.md with every number and the exact commands. Then stop.
