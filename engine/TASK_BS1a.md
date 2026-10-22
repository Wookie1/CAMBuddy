# Task BS1a: trochoidal channel clearing before the hug rings. Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ (read and run it only). Edit engine/rough.py (a new helper module engine/band.py is fine) and engine/test_engine.py.
Do NOT touch opencode.json. Budget ~300 changed lines plus tests; if it overruns ~380, STOP and report why.
Report ONLY numbers you produced this session from files under /Users/James (worktree /Users/James/ai-sandbox/stevecam-bs1a,
branch bs1a = main 0ab844a: HR1 rings after a2d, HB1v2 helix floor circles, ZE2/ZE2F/ZE2F2/ZE2D judge). Cite only files that
exist and commits `git log` shows - never invent a hash. Long runs: nohup + short polling; never end your turn while one
runs. ONE-JOB SLOT - every heavy run (engine, zmap, clcheck, pytest, test_engine, test_finish) via
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
If blocked, write the question into engine/BS1a_RESULTS.md and stop. If BS1a cannot reach the bar, SAY SO - never relax
anything (the fallback, stepped-depth slotting with James's T13 slotting data, is the coordinator's call).

## Problem (measured by the supervisor; out/BAND0_RESULTS_ref.md)
After HR1/HB1v2, main's Core Front rough still has 161.2 mm of full-width windows at CUTTING feed, all hug-ring residue at
Z 40.289 / 42.354 / 42.926: the ring runs along a wall through a CHANNEL with live material on both sides, at the full
stepdown (ZE2D full_width_depth p50 18.0, max 18.5). Adaptive2d cannot clear it (no start point / over the load / gouges).
The CL-allowed centre sliver there is >= 4 mm wide for 150 of 151 windows (p50 6.45 mm).

## Change: per level, AFTER all a2d regions, BEFORE the hug rings
1. Find each hug-ring segment whose engagement against the LIVE stock model (the rough's own stock in emit order, e.g.
   engine/rough.py _strip_engage ~line 765, or the stock's own sweep) would be full width (material on both sides).
2. Clear that channel with TROCHOIDAL loops along its centre line: loop size from the local CL-allowed width, every loop
   point inside the CL-allowed region (checked against the part CL grid exactly like the rings: isl_ok / allowance /
   hf backstop / clcheck), advance per loop chosen so that ZE2 ae_eff <= 2.032 in every 1 mm window and spikes <= 2.44
   (expect a small advance: with ~2 mm loops on the 12.686 tool, area/travel ~ 2.7x the advance). Feed = cut feed.
3. Entry into each channel: a 2-degree helix + floor circle (as the rough's other entries) where a CL circle of r >= 1.903
   fits; else an SE2-verified side entry from cleared stock; else REPORT the spot (no plunge, zig-zag only with run >= D).
4. Then the normal hug ring runs at leave, as today.
No margin cuts (engine/rough.py isl_margin stays as R2 set it), never post-edit Adaptive2d's moves, links follow the
current rules (rapid-rise, RP1a link_clear, swept rapid check).

## Tests (engine/test_engine.py)
Synthetic STRAIGHT and L-SHAPED 19 mm-wide channels, 18 mm deep, with walls on both sides: after the rough, ZE2
(verify/zmap.py, read-only use) shows 0 full-width windows at cutting feed in the channel and every new point is CL-legal.
Each must FAIL on main's code.

## Judge (main's verify/zmap.py; commands as engine/TASK_HR1.md on main, with --ae2-dump and --out-json)
Test block and Core Front, BEFORE = main (out/hb1v2_cf.ngc, out/hb1v2_tb.ngc are main's programs) vs AFTER:
- full-width at CUTTING feed (engagement.full_width_slots_ae2_cutting_feed): Core Front 161.2 mm -> 0 (target)
- full_width_depth bands by owner (hug ring / your channel loops / a2d / helix / floor circle), cutting vs entry feed
- zmap gouges / rapid collisions / axial plunges / outside_grid = 0; exact clcheck (engine/probe_clcheck.py) 0 on the
  posted rough; overload length by owner (not worse than main for any existing owner)
- cycle time before vs after; the one residue window whose sliver is < 4 mm (Z 40.289, sliver 1.65 mm): what happened
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, all via the slot.
Write engine/BS1a_RESULTS.md with every number and the exact commands. Then stop. (BS1b - extra offset rings for
over-load corners - is a later task; do not start it.)

## ADDENDUM (supervisor, after your first report) - REPORT ONLY, no engine change unless item 3's what-if needs a
## parameter you already have; do not commit
Your result (cutting-feed full-width 161.2 -> 0) is the target, but the cost (+1135.8 s Core Front, +205.8 s test block)
must be explained before any merge. Add to engine/BS1a_RESULTS.md:
1. Cycle delta by MOVE CLASS (Core Front and test block): trochoid cutting; trochoid entries (helix + floor circle: count,
   depths, time); links and rapids; ring changes. Numbers must add up to the total delta.
2. Length of ring/channel treated, BY REASON: genuine full-width channel (material on both sides) vs over-load-only
   segments. The brief was channels only - if over-load-only segments were treated too, say so, and how much of the
   overload drop 764.5 -> 341.7 mm came from them.
3. ONE what-if, report only: loop radius sized to the local CL room (sliver/2 minus clearance) instead of the fixed
   clamp, and the largest advance that keeps the same ZE2 bar (p95 ae_eff <= 2.032 - your 1.85 margin is fine - and
   spikes <= 2.44 - your 2.25 margin is fine). Give the advance and the cycle (run it; same judge).
4. The 4 band_blocked spots (sliver < 4 mm) left to the ring at ae_eff up to 8.13 - that is > 3x the load and fails the
   over-load bar. For each: its sliver, and whether smaller loops entered from the cleared neighbouring channel
   (SE2-verified side entry, no helix) take it under 2.44.
Same rules: one-job slot, never print G-code or large outputs, cite only real files/commits.
