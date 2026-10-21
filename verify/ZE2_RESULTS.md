# Task ZE2 results — radial engagement by AREA (ae2), report-only

All numbers below were produced this session in this worktree
(`/Users/James/ai-sandbox/stevecam-ze2`). Nothing committed; only
`verify/zmap.py` and `verify/test_zmap.py` edited (plus a report-only
`--ae2-dump` CLI addition and the gitignored `out/` fixtures/results).

## What changed (verify/ only, no gate/threshold change)

`verify/zmap.py`: new AREA-based engagement on top of the existing keys.
For every horizontal feed move (|dz| <= 1e-6) the plan area of the cells the
move removes material from (cells counted once) is recorded; consecutive
horizontal feeds at the same Z along the same path are combined into windows
of >= 1 mm travel (`AE2_WINDOW_MM = 1.0`). A window ends at a non-horizontal
move, a Z change, a rapid, or a direction change > 45 deg
(`AE2_DIR_MAX_DEG = 45`). ae_eff = area_sum / length_sum; `a` = max removed
height above the tool bottom in the window (ZE's depth_mm); the old max-chord
`width_mm` is kept on every window. Windows are the minimal runs of >= 1 mm
travel; a trailing run below 1 mm is dropped (grid noise). New keys inside
`engagement` (every existing key keeps its value):

- `ae2`: {n, p50, p95, p99, max} of ae_eff over all windows.
- `full_width_slots_ae2`: ae_eff >= 0.9 x dia AND a > 0.5 - count, total
  length, worst 10 (line, x, y, z, ae_eff, a, old width).
- `overload_feeds_ae2`: ae_eff > 2.4384 AND a > 0.5 (the SE2 merge bar,
  area form) - same fields.
- Raw window records in `res["_ae2_raw"]` (also writable to a file with the
  new report-only `--ae2-dump <path>` flag).

`--jobs` merging: raw per-feed area records carry the global move index and
are concatenated across chunks; windows are rebuilt with the same builder as
serial -> jobs result identical to serial (test asserts equality of
`_ae2_raw` and the whole `engagement` dict for jobs=2/4).

## Synthetic validation (FIRST, per task) - flat D 12.686, cell 0.1, solid stock

New tests in `verify/test_zmap.py` (all pass):

| case | ae_eff | old max-chord width | verdict |
|---|---|---|---|
| straight full slot in solid, 0.1 mm segments | every window within 5 % of D (p50 ~12.6) | ~D | both metrics OK (slot front crescent IS full width) |
| straight full slot in solid, 5 mm segments | every window within 5 % of D | ~D | both metrics OK |
| curved full slot (arc r 40 mm, 0.5 mm chords) | every window within 5 % of D | ~D | both metrics OK |
| straight side cut along a wall at 2.032 mm radial | 2.032 +- 0.1 | ~2.0 (cells above the tip span only the wall strip) | both metrics OK |
| 0.1 mm skim of an 18 mm tall wall (floor at tip) | <= 0.2, a = 18 +- 0.2 | ~0.1 | both metrics OK |
| slot rim skim, line-567 form: tool along a slot, both walls standing 18 mm above the tip, floor level with the tip | ~0.2 (max <= 0.3) | ~full diameter (>= 0.9 x D); old `full_width_slots` counts EVERY window | **OLD METRIC FAILS, ae2 correct** |
| window breaking: 90 deg turn breaks, <= 45 deg turn merges, Z change breaks, rapid+plunge break | - | - | 5 windows exactly as designed |

**Which cases the old max-chord width fails:** of the four task-mandated
synthetic cases, none - the old metric reads ~D on both full slots (correct),
~2.0 on the 2.032 side cut (correct, because it measures only cells standing
above the tip), and ~0.1 on the single-wall 0.1 mm skim (correct). The old
metric fails the real-program form, which is added as a fifth synthetic case:
the slot rim skim (line-567 form), where thin rim rows at radial ~6.2-6.3
stand 18 mm tall on BOTH sides of the path - the cells above the tip span
nearly the full diameter, so ZE's width reads ~12.686 (every window counted
as a full-width slot) while the removed AREA is only ~0.2 mm of width. The
same mis-score is what the ae2 metric fixes on line 567 of the real program
(below).

## Main rescore - Core Front T13 rough at main d1542dd

Command (via the one-job slot):

```
nohup .../slot.sh /opt/homebrew/bin/python3 verify/zmap.py \
  out/main_d1542dd_cf.ngc --part out/cf_hf01_z5b.npy --tool flat \
  --dia 12.686 --stock -128.651 128.651 -82.55 82.55 0 60.96 \
  --engage-max 2.438 --jobs 6 --out-json out/ze2_main.json \
  --ae2-dump out/ze2_main_ae2.json > out/ze2_main.log 2>&1 &
```

Exit code 0.

### Gates unchanged vs ZE: 0 / 0 / 0 / 0

gouges = 0, rapid_collisions = 0, axial_plunges = 0, outside_grid = 0.
Old engagement keys reproduce the ZE values exactly:
horizontal n/p50/p95/p99/max = 140328 / 2.0824 / 2.4149 / 12.686 / 12.686;
`full_width_slots` = **2871 moves / 1259.9 mm**;
`overload_feeds` = **5962 moves / 2111.7 mm** (both equal to the expected
2,871 / 1,259.9 mm and 5,962 / 2,111.7 mm).

### Old vs ae2

| metric | count | total length |
|---|---|---|
| full_width_slots (old, max chord >= 0.9 D, a > 0.5) | 2871 | 1259.9 mm |
| full_width_slots_ae2 (ae_eff >= 0.9 D, a > 0.5) | **1049** | **1139.0 mm** |
| overload_feeds (old, width > 2.4384, a > 0.5) | 5962 | 2111.7 mm |
| overload_feeds_ae2 (ae_eff > 2.4384, a > 0.5) | **1563** | **1737.2 mm** |

So the area form keeps ~37 % of the old full-width-slot count (1049 vs 2871)
and ~26 % of the overload count: most old "wide" moves were short
<1 mm segments whose front crescent spans the chord while the removed area
per travel is far below D (grid-noise / skim-like), and windows that merge
through them average their area down.

### ae2 distribution

ae2: n = 70155 windows, p50 = **1.2731**, p95 = **2.0802**, p99 =
**12.6658**, max = **12.8179** mm (max slightly over D: a window's removed
area includes the chord-end bulges of short-step slotting; +1.0 % over D).

Worst 10 ae2 windows (line, x, y, z, ae_eff, a, old width):

```
124574   83.921  -37.537  35.306  ae_eff 12.8179  a  7.0484  old 12.6860
 73120  -38.066  -28.773  42.926  ae_eff 12.8145  a 18.0340  old 12.6860
124306  -13.573  -17.717  35.306  ae_eff 12.8055  a  7.0484  old 12.6860
124689  110.622   -4.577  35.306  ae_eff 12.8047  a  7.0484  old 12.6860
124917   44.470   31.449  35.306  ae_eff 12.8034  a  7.0484  old 12.6860
125248  -98.431   29.448  35.306  ae_eff 12.8000  a  7.0484  old 12.6860
124588   88.925  -35.273  35.306  ae_eff 12.7959  a  7.0484  old 12.6860
125230  -93.462   33.451  35.306  ae_eff 12.7939  a  7.0484  old 12.6860
124695  110.860   -1.575  35.306  ae_eff 12.7919  a  7.0484  old 12.6860
125125  -52.575   36.130  35.306  ae_eff 12.7915  a  7.0484  old 12.6860
```

These are genuine full-width slotting passes (ae_eff ~ D at axial depth
7.05 mm and 18.03 mm), not crescent artifacts - the top of the ae2 list is
real load.

## Line 567 under BOTH metrics

(`out/ze2_line567.log`; serial replay of lines 1..567 only)

The move on line 567: `G1 X-0.3615 Y50.6458 Z42.3544 F3429` from
(-0.4521, 50.7385, 42.3544):

- move length: **0.1296 mm** (horizontal, dz = 0)
- old width: **12.686 mm** (= D -> ZE counts it as full-width)
- its ae2 window: lines **567..573** (7 short feeds), travel
  **1.1441 mm**, removed area **14.30 mm^2**, **ae_eff = 12.4987 mm**
  (98.5 % of D), **a = 18.6056 mm**, old width 12.686
- cells the move removes: **166**, all at radial **6.219..6.342 mm**
  (the rim band, exactly the ZE observation); 153 of them stand > 0.5 mm
  above the tool bottom, up to 18.606 mm
- **angular range of the standing cells** around the tool centre relative to
  travel direction: **-56.1 deg .. +84.9 deg = RANGE 141.0 deg** (measured
  at the move end centre; at the start centre -55.1..+83.7 = 138.8 deg).
  119 of the 153 standing cells lie forward (+-45 deg of travel).

Interpretation: "only cells at radial ~6.2-6.3 stand" is true for BOTH a
short-step slot cut and a rim skim, but the angular range separates them -
line 567's standing cells sweep ~141 deg centred on the FRONT of the tool
(the crescent ahead of the tool as it advances into fresh material), while a
rim skim along a wall would concentrate its standing cells near +-90 deg (the
sides). Consistently, ae_eff = 12.50 ~ D: line 567's window is genuine
full-width slotting (a slot being cut in ~0.13 mm steps at full depth,
a = 18.6), not a rim skim - the area form agrees with the old width here,
and both count it as a full-width slot.

## Tests

`/opt/homebrew/bin/python3 -m pytest verify -q` -> **105 passed, real exit
code 0** (`out/ze2_pytest_final.log`, `EXIT=0`; 8 new ZE2 tests).
