# RP1 step 1 — (a) keep-tool-down links, measured. Do not commit.

Judge = `verify/zmap.py` exit code + JSON only. Baseline = supervisor's
`scratchpad/rp1base/` (branch HEAD + RT_RP instrumentation, 2 deg). All RP1
numbers below are from this session's runs under
`scratchpad/rp1a/` (`rp1a_fix.ngc` = final code; `rp1a_k{3,6,10,15}.ngc` =
sweep). Engagement programmed load unchanged (2.032), ramp angle default 2 deg,
no post-pass on Adaptive2d moves, `verify/` untouched, no tests relaxed.

## What (a) does

1. **`--keep-tool-down` (default 3.0)** → `a2d.keepToolDownDistRatio`
   (`engine/cli.py` → `rough(keep_tool_down=...)`).
2. **At-depth deep links** (`engine/rough.py`, `linkclear` branch): an
   Adaptive2d link whose corridor (a) starts at the level's cutting Z, (b) is
   island-clear (`isl_ok3` + `corridor_ok` 0.4 mm samples + midpoints),
   (c) passes the verified `stock.link_clear(corridor, z)` at cutting height,
   (d) passes `stock.link_clear(corridor, z + lift)` so the tool body clears
   everything a lift would have cleared, and (e) shears no wide face
   (`_strip_engage <= 2.438`) is emitted as a feed traverse at Z
   (`n_deep_links`). The tool stays down: no link split, no re-entry helix.
   Anything failing any check takes the existing lift/retract path unchanged.
   Guards (d)+(e) were added after the first CF run: without them the
   two-level synthetic `test_rough_rapids_clear_stock` failed (14 links routed
   through the step wall at depth, `n_rapid_bumps` 0 — R5 never engaged).
   With them the synthetic test passes (1 bump restored) and CF deep links are
   unchanged (all 2,560 already satisfied both).

## Sweep: keepToolDownDistRatio (deep links active in all rows)

| ratio | deep links | clip breaks (engine) | rapids m (zmap) | cycle s (zmap) | engine plan s |
|---|---|---|---|---|---|
| baseline (no deep links, ratio 3) | — | 2,342 | **78.28** | 7,710.3 | 787 |
| 3 | 2,560 | 169 | 24.28 | 6,183.4 | 814 |
| 6 | 2,533 | 167 | 23.85 | 6,180.1 | 814 |
| 10 | 2,533 | 167 | 23.86 | 6,180.1 | 1,099 |
| 15 | 2,533 | 167 | 23.86 | 6,180.1 | 1,225 |
| **3 (final, guarded)** | 2,554 | 175 | **24.44** | **6,243.4** | 805 |

The ratio is inert beyond 3: the engine-side deep link already absorbs every
link Adaptive2d resolves tool-down at level; 6/10/15 emit byte-equivalent
programs and only burn planning time (ratio 10/15 = identical output to 6).
**Keep default ratio 3.**

## Final run (guarded code, ratio 3) vs baseline — zmap judge

| metric | baseline | RP1(a) | target |
|---|---|---|---|
| zmap exit code | 0 | **0** | 0 |
| gouges / rapid collisions / outside-grid | 0 / 0 / 0 | **0 / 0 / 0** | 0 |
| axial plunges (zmap / engine) | 0 / 0 | **0 / 0** | 0 |
| rapids | 78.28 m | **24.44 m** | ≤ 57 m ✓ |
| total cycle time | 7,710 s | **6,243 s** | — |
| entry time @ 2 deg (desc. feed ÷ F1270) | 125.3 m = 98.7 min | 83.4 m = **65.6 min** | < 5 min ✗ |
| horizontal p50 / p95 / p99 | 2.082 / 2.414 / 12.686 | 2.082 / 2.415 / **12.686** | p99 ≤ 6.7 ✗ |
| engagement > 2.438 count | 27,939 | 14,874 | — |
| air fraction | 0.614 | 0.688 | — |
| engine clcheck violations | 0 | 0 | 0 |

Per-level (RT_RP, final run): regions **213 unchanged**; tool-up link splits
**2,213 → 46**; deep links absorb the rest. Worst levels:

| z | baseline regs / breaks | RP1(a) regs / breaks | deep links at level |
|---|---|---|---|
| 35.306 | 5 / 565 | 5 / **0** | 650 |
| 42.354 | 10 / 550 | 10 / **2** | 626 |
| 47.625 | 5 / 404 | 5 / 7 | 472 |
| 25.146 | 4 / 488 | 4 / 2 | 557 |
| 45.72 | 9 / 134 | 9 / 23 (27 lifts kept: step-ups) | 143 |

Regions stay 213 because region count is set by island/territory splitting
upstream of Adaptive2d linking; deep links remove the *splits*, not regions.

## Verdict: targets NOT met by (a) — STOP per task line 26

Met: rapids (24.4 ≤ 57 m), axial 0, all safety gates 0, cycle −19 %.
Not met, and not reachable by (b):

- **Entry time 65.6 min vs < 5 min.** The remaining descending feed is the
  per-region entry helix: ~213 mandatory level/region entries at 2 deg
  (pitch cap 2·pi·r·tan 2°, ≈0.54 m per full 19.05 mm level) ≈ 83 m floor.
  < 5 min (< 6.4 m descending feed) would require abandoning the 2 deg ramp
  or plunging — both forbidden. RP0 already showed (b) does not change region
  count, so it cannot cut these entries either.
- **Horizontal p99 = 12.686 unchanged** (baseline identical): the spikes are
  full-diameter engagements on wide-face cutting at level, not links — (a)
  removed every link-caused spike it could (engagements 27,939 → 14,874) and
  p99 did not move. Slot-p99 per ZE report pending; this lever is separate.

(b) (safe-region input boundary + clip-as-assertion) would remove the residual
1597 clip/tail categories and the under-areas but cannot move either missed
target; not attempted this session.

## Regression status

- `engine/test_engine.py` (VibeCAD python): **0 failures** — incl.
  `test_rough_rapids_clear_stock` (fixed by guards d/e) and
  `test_rough_rt_entries` (axial 0).
- `engine/test_finish.py`: exit 0. `/opt/homebrew/bin/python3 -m pytest verify
  connector engine/test_post.py`: **203 passed** (fixtures: 10 ok, 0 bad).
- Diff: `engine/rough.py` +30/−2, `engine/cli.py` +5/−0. Not committed.
