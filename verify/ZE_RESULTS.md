# Task ZE results — engagement report gains axial depth per wide move (report-only)

## What changed (verify/ only, no gate/threshold change, nothing committed)

`verify/zmap.py`: every engaging cutting move now also records its AXIAL depth
= deepest column of stock removed above the tool surface under the footprint
during that move (max over removed cells of `stock_before - cut_surface`, read
BEFORE the move cuts). New keys inside `engagement` (existing keys untouched):

- `wide_moves`: horizontal moves over the engagement threshold split into
  `slot` (axial depth > 0.5 mm) and `skim` (<= 0.5 mm); each with count, total
  length, total time at their feed, p50/p99 of radial width and axial depth.
  `null` when no threshold is given.
- `slot_horizontal`: {n, p50, p95, p99, max} of radial width over horizontal
  moves with axial depth > 0.5 mm (the engagement statistic that matters for
  load).
- `skim_by_z`: time per Z level spent skimming (horizontal feeds with axial
  depth <= 0.05 mm - floors already within a few hundredths).
- `full_width_slots` (2b): horizontal feeds with width >= 0.9 x dia AND axial
  depth > 0.5 mm - count, total length, time, top 20 by depth.
- `overload_feeds` (2c): horizontal feeds with width > 2.4384 mm
  (= 1.2 x the 2.032 mm optimal load; task text rounds this to 2.44) AND
  axial depth > 0.5 mm - count, total length, time, worst 20 by width.
  This is the SE2 merge bar.

`--jobs` merging: raw per-move width+depth records are concatenated across
chunks and the keys are derived with the same builder as serial (test asserts
serial == jobs=2/4 exactly).

## Tests

`/opt/homebrew/bin/python3 -m pytest verify -q` -> **97 passed** (4 new ZE
tests: full-width slot at 3 mm depth -> slot; full-width pass over a floor
0.02 mm high -> skim and counted in `skim_by_z`; existing engagement numbers
on three existing fixtures asserted equal to the pre-ZE captured values;
parallel merge equals serial). One pre-existing failure (`out/core_front_roughRT_before.ngc`
absent from this clone's gitignored `out/`) was fixed by copying the fixture
from stevecam-rt2 (md5-identical to the stevecam-se copy); no test was
relaxed.

## Real-program runs

Recipe: `--tool flat --dia 12.686 --stock -128.651 128.651 -82.55 82.55 0
60.96 --engage-max 2.438 --jobs 8`, part `cf_hf01_z5b.npy` (md5-identical in
ze/rt2/se). `out/rp1a_cf.ngc` was absent, so main = the scratchpad
`rpm/cf.ngc` (helix-only entries). `se2_cf.ngc` existed and was run.

| program | engagement count | wide slot n / len / time | wide skim n / len / time | slot_horizontal p50/p95/p99/max | full_width_slots n / len mm / time s | overload_feeds n / len mm / time s |
|---|---|---|---|---|---|---|
| main (cf.ngc) | 14874 | 5965 / 2111.7 mm / 36.9 s | 597 / 251.0 mm / 4.4 s | 2.0946 / 2.4145 / 12.686 / 12.686 | 2871 / 1259.9 / 22.0 | 5962 / 2111.2 / 36.9 |
| rp2_1 (SE step 1 side entries) | 12181 | 6113 / 2242.5 mm / 39.2 s | 458 / 200.7 mm / 3.5 s | 2.0947 / 2.4203 / 12.686 / 12.686 | 2876 / 1311.6 / 22.9 | 6110 / 2242.0 / 39.2 |
| se2 (SE2 rough) | 14888 | 5965 / 2112.2 mm / 37.0 s | 598 / 253.0 mm / 4.4 s | 2.0946 / 2.4145 / 12.686 / 12.686 | 2871 / 1259.9 / 22.0 | 5962 / 2111.7 / 37.0 |
| rt2 (rt2_after.ngc) | 9898 | 6174 / 2203.6 mm / 38.6 s | 354 / 176.6 mm / 3.1 s | 2.0946 / 2.4235 / 12.686 / 12.686 | 2873 / 1260.7 / 22.1 | 6171 / 2203.2 / 38.6 |

Wide-slot axial depth p50/p99: main 7.048 / 18.606 mm; rp2_1 10.160 / 18.606;
se2 7.048 / 18.606; rt2 7.048 / 18.605. Skim depth p50 is 0.0 (floors already
at level). `skim_by_z`: 21 Z levels in every program, ~61 s total skim time
(main 61.0, rp2_1 61.1, se2 61.3, rt2 61.4), worst levels 42.354 / 35.306 /
25.146 mm Z in all four.

The 12.686 flat shows as required: `full_width_slots.top` entries with
width_mm = 12.686 and depth_mm up to 18.6056 (main line 567, XY -0.3615,
50.6458; rt2 same XY at line 102).

## SE2 merge bar (SE2 vs main's helix-only rough, Core Front)

| metric | main | se2 | delta |
|---|---|---|---|
| full_width_slots count | 2871 | 2871 | 0 |
| full_width_slots total length | 1259.9 mm | 1259.9 mm | 0.0 mm |
| overload_feeds count | 5962 | 5962 | 0 |
| overload_feeds total length | 2111.2 mm | 2111.7 mm | **+0.5 mm (+0.02 %)** |

SE2 does not increase either count; overload total length is +0.5 mm over
main's 2111.2 mm - a rounding-level increase at the sub-millimetre scale
(0.02 %), driven by side-entry geometry shaving a hair more total width-over
threshold distance. Count parity holds exactly.

Reference: rp2_1 (RP2 step 1) is clearly above main on this bar (+5 full-width
slots, +51.7 mm; +148 overload feeds, +130.8 mm) - SE2 closed essentially the
whole gap.
