# RT2 — roughing travel: finish report

Judge = `verify/zmap.py` exit code + JSON only. Commands exactly as in
TASK_RT2.md; outputs in `out/rt2_after.ngc`, `out/rt2_zmap_cf_after.json`,
`out/rt2_block_after.ngc`, `out/rt2_zmap_block_after.json`.
Programmed engagement unchanged (optimal load 2.032 mm). Diff: +162/−41
lines, engine/rough.py only. Not committed.

## Step 0 — classification of the RT-after program (before any RT2 change)

`out/core_front_roughRT_after.ngc` replayed against the live stock model:

- **111,584 descending G1 segments in 2,889 descents**: 2,505 straight
  (air) plunges and 332 helix runs. Helix-run radius buckets: r≈0.25 → 76,
  r≈0.5 → 97, r≈2 → 87, r≈3 → 112, r=5 → 10. **33,959 helix segments
  descend steeper than 15°** — all at r≈0.2–0.5 mm: the micro-helix tiers
  descended at 0.5 mm/turn regardless of radius (≈22° at r=0.4).
- **The 343 judged axial plunges** trace to three causes: (a) those
  pitch-uncapped micro-helix tiers; (b) the radius-mismatch bug — candidate
  circles were *validated* at a probe radius but *emitted* at
  `helix_dia/2`, so the real path could cross islands and leave stock under
  the flat bottom; (c) straight-feed fallbacks at wall slivers when no
  helix/shift was found.
- **Full-width horizontal moves** (engagement = 12.686): B=35 helix return
  feeds, C=807 first loops after a helix entry, E=2,359 loops crossing an
  uncut step mid-region. Concentrated at the mandatory flat levels
  Z = 35.306 / 42.354 / 40.289 / 42.926 / 25.146 — boundary-parallel
  passes over a still-uncut floor read full width because zmap's ew is the
  lateral extent of *any* cell above the tip.
- **~109k "entry" moves** = over-fine helix segmentation (up to 36 segments
  per turn at r=0.2) plus the separate depth circle emitted after every
  helix — not 109k distinct plunges.

## What changed (engine/rough.py)

1. **Integer-turn helices** (`_helix_turns`/`_helix_moves`): pitch capped so
   no segment descends steeper than ~14° at *any* radius; the final full turn
   completes the bore at z_bot (no separate depth circle). Entries: 13,325 →
   4,176 (zmap-judged).
2. **Helix used at every layer thickness** — a thin layer (e.g. 0.6 mm) now
   gets one shallow-pitch turn instead of falling through to a straight
   feed-down (the last test-block plunge).
3. **Honest helix stock model**: the helix is milled segment-by-segment at
   each segment's START z. The old model milled the ideal circle at z_bot,
   but a ring point is under the disk only during part of each turn — where
   that angular window closes above z_bot a crescent of stock really remains
   (this was the test-block's final 0.615 mm plunge).
4. **No corridor pre-write at z_top**: the entry corridor is cut by the
   return feed at Z, not claimed before the helix runs (fixes a rapid that
   rode below stock — CF rapidx 1 → 0).
5. **Corridor-aware traverse height** in `try_cand`: the G0 from the entry to
   the helix start is raised to clear the whole corridor, not just the entry
   column (emit's endpoint bump could not fix a diagonal sweep starting below
   material).
6. **Helix descends from the post-bump height** (`zt = prev.z` when the R5
   rapid bump lifted the start move) — otherwise the first helix segment
   bridged the lift at ~90°.
7. Return-feed containment inside the bore, `grown` prefilter removed on
   helix candidate points, judge-mimic disk widened (`r_wide`), wide feed
   links over stock take the lift branch (`_strip_engage`), honest
   self-abort counter `n_axial_plunge` instead of emitting a judged plunge.

## Results — Core Front T13 (judge: exit code)

| metric | before (RT-after) | after (RT2) | target | met |
|---|---|---|---|---|
| **zmap exit code** | 1 (343 axial) | **0** | 0 | **✓** |
| **axial plunges** | 343 | **0** | 0 | **✓** |
| gouges / rapid collisions / outside_grid | 0 / 0 / 0 | 0 / 0 / 0 | 0 | ✓ |
| rapids | 89.8 m | 78.7 m | ≤57 m | ✗ |
| plunge time (F1270 arc) | 17.3 m / 13.6 min (111,548 segs) | 22.9 m / 18.0 min (21,095 segs) | <5 min | ✗ |
| entry moves (zmap n) | 16,809 | 4,176 | — | −75% |
| horiz p50 / p95 / p99 | 2.080 / 2.392 / 12.686 | 2.082 / 2.413 / 12.686 | p99 ≤6.7 | ✗ |
| cycle time | 2,710 s | 2,878 s | — | +6% |
| leftover max / p95 / within-0.5 | 39.54 / 5.461 / 0.6812 | identical | — | = |

(Round-G reference on the same part: axial 84, rapids 38.2 m, cycle 1,360 s,
horiz p99 5.03 — G met the travel targets but fails today's axial gate.)

## Results — test block

| metric | before (R6cn) | after (RT2) |
|---|---|---|
| **zmap exit code** | — | **0** |
| axial plunges | not counted pre-ZA | **0** |
| gouges / rapid collisions / outside_grid | 0 | 0 / 0 / 0 |
| rapids | — | 10.6 m |
| cycle time | — | 306.4 s |
| horiz p50 / p95 / p99 | 8.50 (p99) | 2.10 / 2.97 / 11.82 |
| entry n | 226 | 934 |

## Regression status

- `engine/test_engine.py`: 0 failures (incl. zmap-based
  `test_rough_rt_entries` on synth_pocket).
- `engine/test_post.py` connector e2e: 0 failures (zmap equivalence).
- `engine/test_finish.py`: ALL PASS.
- Engine self-checks intact: hf backstop, CLCHECK, `n_axial_plunge` abort
  (0 on both parts).

## STOP report — unreachable targets within budget

The axial gate (the pass/fail criterion) is **met on both parts**. The
secondary travel targets (rapids ≤57 m, plunge time <5 min, horizontal
p99 ≤6.7) are **not reachable** in RT's current region architecture without
exceeding the ~200-line budget:

- The remaining full-width horizontals are C+E class (first loops after a
  helix + loops crossing uncut steps) at the *mandatory* flat levels, and
  their count scales with RT's region explosion: **213 regions / 2,342 clip
  breaks** on Core Front vs **14 regions** in the round-G planner that
  achieved p99 5.03 and 38.2 m rapids. Fixing p99 means redesigning the
  region/clip-break planning (merge territories, carry uncut-step maps into
  loop ordering), not link-level tuning — a separate task.
- Plunge time is dominated by integer-turn helix arcs at many small bores;
  cutting the entry count further requires fewer regions (same redesign).
- No tests were relaxed, no bypass flags used, verify/ untouched, engagement
  left at optimal load 2.032, no post-pass editing of Adaptive2d moves.
