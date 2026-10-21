# SE2 — side entries only through already-cleared material

All numbers below were produced this session from files in this repo
(`out/se2_*`); judge = `verify/zmap.py` exit code + JSON on the exact task
commands. Nothing committed. Programmed engagement 2.032, ramp angle default
2 deg untouched; no post-pass; verify/ untouched; no tests relaxed; no bypass
flags.

## Change (engine/rough.py +13 lines; engine/test_engine.py +97 test lines)

1. `AXIAL_FLOOR = 0.2` added as engine constant (same name/value as
   verify/zmap.py's; the engine had none).
2. `find_shift(flank=True)`: new gate — the whole sideways feed-in
   (descent column -> region start, swept by `tool_r`) must run through
   material ALREADY cleared at that level: `stock.link_clear(path,
   Z + AXIAL_FLOOR)` on the engine's live stock model. Any standing stock
   above Z + 0.2 mm under the swept feed-in rejects that side entry and the
   region takes the existing 2-deg helix unchanged (no reduced-feed variant).
   `link_clear` returns False when the path leaves the tracked stock grid ->
   fail closed. Existing checks (judge-disk-clear column, island legality,
   part-hf backstop, rapid-clear descent column) unchanged; the descent stays
   judge-disk-clear (rule 3).

## Core Front T13 (out/se2_cf.ngc / out/se2_cf_stats.json / out/se2_cf_zmap.json)

| metric | value | (RP2_1 ref, prior session) |
|---|---:|---:|
| **zmap exit code** | **0** | 0 |
| gouges / rapid collisions / axial plunges / outside_grid | **0 / 0 / 0 / 0** | 0/0/0/0 |
| regions executed | 213 | 213 |
| side entries used (entry + re-entry) | **145** | 187 |
| remaining region entries | 68 via 2-deg helix/ramp descent | 26+8 |
| region-entry feed | 34,440 mm = 27.1 min @ F1270 (208 descents) | 29,404 = 23.2 min |
| mid-region re-entry feed | 20,325 mm = 16.0 min (160 descents) | 15,410 = 12.1 min |
| total descending feed | **54,771 mm** = 43.1 min | 44,819 = 35.3 min |
| total cycle (zmap) | **4,893 s = 81.6 min** | 73.9 min |
| rapids (zmap) | **24.15 m** | 23.95 m |
| horizontal engagement p50 / p95 / p99 | 2.082 / 2.415 / 12.686 | 2.416 / 12.686 |
| engine self-checks | n_axial_plunge 0, clcheck_violations 0 | same |

42 previously-side-entering approaches (187 -> 145) now helix; the +9,952 mm
of descending feed costs +7.7 min of cycle — that is the overload the rule
removes (sideways slots of standing material at up to full stepdown at cut
feed, prevented by forcing the ramped helix instead).

## Test block (TASK_R6 command; out/se2_tb.ngc / out/se2_tb_stats.json / out/se2_tb_zmap.json)

| metric | value | (RP2_1 ref) |
|---|---:|---:|
| **zmap exit code** | **0** | 0 |
| gouges / rapid collisions / axial plunges / outside_grid | **0 / 0 / 0 / 0** | 0/0/0/0 |
| regions executed | 11 | 11 |
| side entries used | **5** | 9 |
| region-entry feed | 2,215.9 mm = 104.8 s (10 descents) | 969.7 = 45.8 s |
| mid-region re-entry feed | 1,327.2 mm = 62.7 s (14) | 1,327.2 = 62.7 s |
| total descending feed | **3,543.1 mm** = 167.2 s | 2,296.9 = 108.5 s |
| total cycle (zmap) | **358.7 s = 6.0 min** | 5.0 min |
| rapids (zmap) | 1,048.5 mm | 1,040 mm |
| horizontal engagement p50 / p95 / p99 | 2.10 / 2.97 / 11.82 | 2.97 / 11.82 |

Re-entry feed is unchanged (1,327.2 mm): every blocked approach here was a
region entry; mid-region re-entries that survive all cross floors milled at
or below their own level (live stock top <= Z + 0.2).

## Tests

- `scripts/check_fixtures.py`: 10 ok, 0 bad.
- `engine/test_engine.py` (VibeCAD python): 24 PASS, **0 failures**, incl. new
  `test_se2_side_entries_only_through_cleared`:
  * two-floor synthetic (`_two_floor_pocket_stl`): the shelf level's only
    side approach crosses the step wall standing above Z -> 0 side entries,
    entries descend by feed (helix). Meaningful check: with the new gate
    temporarily disabled the same part produced 1 side entry across that wall.
  * test block: regions with cleared approaches still side-enter (5 > 0).
- `engine/test_finish.py`: ALL FINISH TESTS PASSED.
- `/opt/homebrew/bin/python3 -m pytest verify engine/test_post.py -q`:
  **109 passed** in 223 s.

## Notes

- Core Front ran only after the M4 `title task FE4` process exited (wait loop
  per task); long runs were nohup + polling.
- `side_entry_feed_mm` stays ~0 because side entries flow through the
  `enter_at` step-3 path (which does not accumulate that counter); the feed
  they carry is inside `entry_feed_mm`/`reentry_feed_mm`.
- Not committed.
