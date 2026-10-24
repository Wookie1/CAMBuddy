# Task BS1a3: trochoid ONLY where the ring is really full-width against the stock AFTER a2d. Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/. Edit engine/band.py, engine/rough.py, engine/test_engine.py only. Do NOT touch opencode.json. Budget ~120 changed
lines plus tests; if it overruns ~180, STOP and report why. Never post-edit Adaptive2d's moves.
Report ONLY numbers you produced this session under /Users/James (worktree /Users/James/ai-sandbox/stevecam-bs1a, branch
bs1a = c074148: BS1a 823d438 + main 6b931ae merged in). Cite only files that exist and commits `git log` shows. NEVER print
NGC/G-code or other large outputs into your context: use cmp, diff --stat, wc and head -3 only. Long runs: nohup + short
polling; never end your turn while one runs. ONE-JOB SLOT - every heavy run via
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
If blocked, write the question into engine/BS1a3_RESULTS.md and stop. If the bar cannot be reached, SAY SO - never relax.

## Defect (measured by the supervisor on out/bs1a_cf.ngc + out/bs1a_cf_ae2.json + out/bs1a_cf_owners.json)
BS1a's trochoids are 83,214 mm of cutting-feed path; 96.4% of it has ZE2 ae_eff < 0.1 (air), 97.9% < 0.5; p50 = p95 = 0.
Levels Z 35.306 and Z 25.146 are 100% air. Main had only ~161 mm of full-width ring. Two causes in the code:
1. engine/rough.py:1948-1950 calls channel_regions BEFORE the emit loop (`for k in order`, rough.py:2010); this level's
   a2d cuts are only milled into the stock inside that loop (stock.mill_path, rough.py:2153). So the detector judges the
   stock as it stood at the START of the level, before any a2d pass - nearly every ring looks like a channel.
2. engine/band.py:277 `_strip_engage(stock, pts, z, tool_r)` (rough.py:765) is the MAX perpendicular chord of standing
   stock over the WHOLE ring path; one full-width sample anywhere makes band.py treat the ENTIRE ring centre line.

## Change
1. Run the channel detection AFTER every a2d region of the level has been emitted and milled (i.e. when the emit loop
   reaches the first non-a2d index, on the LIVE stock), then order bands then rings with _nn_order as today.
2. Select per stretch, not per ring: simulate the RING's own path against that live stock the way ZE2 does (band.py
   _simulate already replays ZE2 1 mm windows on the engine stock grid) and trochoid ONLY the windows (plus a small
   lead-in/out) where ae_eff >= 0.9 x D (FW_FRAC). Drop the overload-only and light treatments (those are BS1b's job).
3. Keep P_CAP 0.36 and the other constants. Delete the BS1A_WHATIF env block (band.py:53-61, _ADV) - it was report-only.
4. Entries, CL legality, links: unchanged from BS1a.

## Tests (engine/test_engine.py)
Keep test_bs1a_straight_channel / test_bs1a_lshaped_channel green. ADD: a synthetic level where a2d clears a pocket
fully except a ring that is NOT full width after a2d -> BS1a3 emits ZERO band regions there (must FAIL on c074148's code,
which judges the pre-a2d stock).

## Judge (main's verify/zmap.py; commands as in engine/BS1a_RESULTS.md, with --ae2-dump and --out-json)
BEFORE = main 6b931ae regenerated this session by the supervisor: out/bs1a3_main_{cf,tb}.ngc, _stats.json, _ae2.json,
_zmap.json (do not regenerate them; if missing, wait for them). AFTER = this branch's code via out/bs1a_run.py.
- Core Front and test block: cutting-feed full-width (engagement.full_width_slots_ae2_cutting_feed) = 0; zmap gouges /
  rapid collisions / axial plunges / outside_grid = 0; exact clcheck (engine/probe_clcheck.py <ngc> <stl> 12.686) = 0
- trochoid owner: length, ae_eff p50/p95/max, share of length with ae_eff < 0.1 and < 0.5 (target: little air)
- treated ring length (centre line) and how many stretches; overload length by owner vs BEFORE; cycle time vs BEFORE
  and vs BS1a (out/bs1a_cf.ngc.stats / out/bs1a_cf_stats.json)
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, all via the slot.
- Regenerate the final Core Front program once more from the FINAL code and cmp it against the one you judged; report.
Write engine/BS1a3_RESULTS.md with every number and the exact commands. Then stop.
