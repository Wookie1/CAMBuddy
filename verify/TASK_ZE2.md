# Task ZE2: zmap radial engagement by AREA (report-only). Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests. Edit ONLY
verify/zmap.py and verify/test_zmap.py (add tests). verify/ must stay independent: no import of engine/ or connector/.
Do NOT touch opencode.json. Report-only: no gate pass/fail changes, every existing key keeps its value.
Report ONLY numbers you produced this session from files under /Users/James (this worktree:
/Users/James/ai-sandbox/stevecam-ze2). Long runs: nohup + short polling; never end your turn while one runs.
ONE-JOB SLOT: this Mac allows one heavy job at a time. Start EVERY zmap/test run through
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
It waits for the slot by itself; just poll the log. Never run two at once.

## Why
ZE's width_mm is the max chord of removed cells projected across travel. A thin crescent at the tool rim (cells at
radial 6.22..6.34 of R 6.343 standing 18.6 mm tall) spans nearly the whole diameter, so a ~0.1 mm rim skim scores
"full width". But a radial-max metric would also be wrong: a real full slot cut in 0.1 mm steps removes only a thin
crescent at the FRONT each step. The AREA form handles both.

## Definition (new keys, alongside the old ones)
For each horizontal feed (|dz| <= 1e-6): ae_eff = (plan area of the cells this move removes material from, cells
counted once) / travel length. Combine consecutive horizontal feeds at the same Z along the same path whose length is
< 1 mm into windows of >= 1 mm travel (area summed, length summed; a window ends at a non-horizontal move, a Z change,
a rapid, or a direction change > 45 deg), so the grid does not add noise. a = max removed height above the tool bottom
in the window (ZE's depth_mm). Keep ZE's old width_mm on every record for comparison.
New keys: engagement.ae2 {p50, p95, p99, max}, engagement.full_width_slots_ae2 (ae_eff >= 0.9 * dia and a > 0.5),
engagement.overload_feeds_ae2 (ae_eff > 2.4384 and a > 0.5); each with count, total length, worst 10
(line, x, y, z, ae_eff, a, old width). Raw window records in res["_ae2_raw"].

## Validate on synthetic cases FIRST (tests in verify/test_zmap.py; flat 12.686, cell 0.1, solid stock)
- straight full slot in solid stock, cut in 0.1 mm segments AND in 5 mm segments: ae_eff = D within 5 %
- curved full slot (an arc as many short chords, radius 40 mm): ae_eff = D within 5 %
- straight side cut along a wall at 2.032 mm radial: ae_eff = 2.032 +- 0.1
- 0.1 mm skim of an 18 mm tall wall: ae_eff <= 0.2 (and a = 18 +- 0.2)
Each must fail if the metric were the old max-chord width (state which of them the old width fails).

## Then rescore main (Core Front T13 rough at main d1542dd = out/main_d1542dd_cf.ngc)
python verify/zmap.py with --part out/cf_hf01_z5b.npy --tool flat --dia 12.686 --stock -128.651 128.651 -82.55 82.55 0
60.96 --engage-max 2.438 --jobs 6 (and the other flags the existing CLI needs for this program). Report:
- gates (gouges, rapid collisions, axial plunges, outside_grid) unchanged vs ZE: must be 0/0/0/0
- old full_width_slots / overload_feeds (expect 2,871 / 1,259.9 mm and 5,962 / 2,111.7 mm) vs the ae2 versions
- line 567 under BOTH metrics: its move length, old width, ae_eff of its window, a, and the ANGULAR range (deg, measured
  around the tool centre relative to travel direction) of the standing cells the move removes. A slot cut in short
  steps and a rim skim both show "only cells at radial ~6.2-6.3 stand"; the angular range tells them apart.
- ae2 distribution p50/p95/p99/max and the 10 worst ae2 windows.
- `/opt/homebrew/bin/python3 -m pytest verify -q` green (real exit code).
Write verify/ZE2_RESULTS.md with every number and the exact commands. Then stop.
