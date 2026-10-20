# RT2a — helixes and ramps honor the ramp angle (default 2°)

Judge = `verify/zmap.py` exit code + JSON only (commands exactly as in
TASK_RT2.md). Diff: +36/−12 lines, `engine/rough.py` + `engine/cli.py` only.
Not committed. Programmed engagement unchanged (optimal load 2.032), no
post-pass, verify/ untouched, no tests relaxed, no bypass flags.

## What changed

1. **`--ramp-angle-deg` (default 2.0)** — `engine/cli.py` →
   `rough(ramp_angle_deg=...)`: `<= 0` rejected (`ValueError`, exit 1),
   clamped to `[0.5, 15]` (verified: 30 → stats `ramp_angle_deg = 15.0`),
   reported in stats.
2. **`_helix_turns(r, dz, angle_deg)`** — integer turns round UP so
   pitch per turn ≤ `2*pi*r*tan(angle)` at the helix radius, plus a
   chord/coordinate-rounding guard so **no emitted G1 segment descends
   steeper than angle + 0.05°**. Unit-checked over
   angle ∈ {0.5,2,5,10,15} × r ∈ {0.2…5.074} × dz ∈ {0.3…40}: 0 violations
   of either the pitch cap or the segment-slope limit.
3. **Straight ramps**: every straight descent into stock already goes through
   `feed_down`'s axial checks (stock under the flat-bottom disk ⇒ helix entry,
   offset descent or self-abort), so straight feeds never cut stock steeper
   than the angle; the remaining steep descents in the programs are vertical
   air links through verified-cleared columns (unchanged from RT2, zmap
   axial = 0). No straight diagonal descent into stock exists to re-angle.

## Judge results at default 2°

| metric | Core Front T13 | test block |
|---|---|---|
| **zmap exit code** | **0** | **0** |
| axial plunges | 0 | 0 |
| gouges / rapid collisions / outside_grid | 0 / 0 / 0 | 0 / 0 / 0 |
| entry moves (zmap n) | 26,870 (RT2: 4,176) | 5,919 (RT2: 934) |
| entry time (helix arc @ F1270) | 122.7 m = **96.6 min** (RT2: 18.0 min) | 13.5 m = **10.7 min** |
| rapids | 78.3 m (RT2: 78.7) | 10.6 m |
| horizontal p50 / p95 / p99 | 2.082 / 2.414 / 12.686 | 2.10 / 2.97 / 11.82 |
| total cycle time (zmap) | **7,710 s = 128.5 min** (RT2: 2,878 s) | **840 s** |
| engine self-checks | n_axial_plunge 0, clcheck 0 | same |

Descending-feed angle audit (modal replay of the emitted G1s):
Core Front @2° — **116,471 segments ≤ 2.05°, 0 at 2–15°, 0 helical > 15°**;
the only >15° descents are 2,296 vertical air links (2.6 m) plus the 3
pre-existing air tool-down diagonals (~82–87°, also in RT-after, no stock
contact — zmap gouge/axial 0). Test block @2° — 12,854 ≤ 2.05°, worst
diagonal 2.01°.

## Entry time vs ramp angle (Core Front T13 / test block)

| --ramp-angle-deg | CF helix segs | CF entry len | **CF entry time** | block entry time |
|---|---|---|---|---|
| 2 (default) | 116,471 | 122.7 m | **96.6 min** | 10.7 min |
| 5 | 48,513 | 51.2 m | **40.4 min** | 4.4 min |
| 10 | 26,287 | 28.0 m | **22.1 min** | 2.4 min |
| 15 | 18,248 | 19.7 m | **15.5 min** | 1.7 min |

(Entry time = descending diagonal feed length / ramp feed 1270 mm/min, the
supervisor's measure; RT-after measured ~15.9 min at 5–15° with a ~14° pitch
cap, matching the 15° row.) Worst helix segment slope in every run ≤
angle + 0.05°. Choice for James: honoring 2° exactly costs ~97 min of entry
on Core Front (~3.5× the whole RT2 cycle); 10° recovers to ~22 min at a
pitch still far below the old 14° cap.

## Regression status

- `engine/test_engine.py` (VibeCAD python): 0 failures — incl. the
  zmap-based `test_rough_rt_entries` (axial 0).
- `engine/test_finish.py`: ALL PASS. `engine/test_post.py` (connector e2e):
  0 failures.
- `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py`:
  **203 passed** (verify/test_zmap.py untouched, still green).

Outputs: `out/rt2a_cf.ngc` + `out/rt2a_zmap_cf.json`,
`out/rt2a_block.ngc` + `out/rt2a_zmap_block.json`, sweep programs
`out/rt2a_cf_a{5,10,15}.ngc`, `out/rt2a_block_a{5,10,15}.ngc` (+ stats).
