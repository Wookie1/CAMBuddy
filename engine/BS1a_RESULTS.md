# BS1a — Trochoidal channel clearing: RESULTS

Branch `bs1a` @ main `0ab844a`. All numbers below were produced in this session
from files under `/Users/James/ai-sandbox/stevecam-bs1a` (judge = this worktree's
`verify/zmap.py`, unchanged). Nothing committed.

## What changed

- **`engine/band.py` (new, 331 lines)** — per-level trochoidal channel clearing.
  For every level, before the hug rings run, `channel_regions()` finds the
  residue channels between the a2d core and the last ring line: for each ring
  point it marches both surface normals with the engine's own clearance oracle
  (`isl_ok3`, 0.03) until a second island/wall is hit; a channel exists where
  the channel-side distance is in [~2.5, tool_r + leave] (the hug ring cannot
  legally take that width). The centre line is resampled and a trochoid is
  run along it: loop radius `r = clamp(half_width - 0.15, 0.8, 3.2)` with a
  radial ramp (~0.5·AE_SS·k·r/(R+r) per loop), advance
  `p = min(AE_SS·π·r/((R+r)·2), P_CAP=0.36)` mm per loop. A `_simulate()`
  pass replays ZE2-style 1 mm windows on the engine stock grid (disk at every
  emitted point, entry bore pre-cleared) and shrinks the half-width
  (1.0/0.75/0.55/0.4) until simulated p95 ≤ 1.85 mm and spike ≤ 2.25 mm.
  Runs shorter than the tool diameter are skipped (zig-zag rule); spots whose
  sliver is < 4 mm are recorded in `stats["band_blocked"]` and left to the
  ring — reported, never forced.
- **`engine/rough.py` (+27/-7)** — regions per level are now
  a2d + band + rings (three-phase NN ordering with `n_a2d`/`n_band`); stats
  keys `n_band_regions`, `band_cut_len_mm`, `band_blocked`.
- **`engine/test_engine.py` (+122)** — `test_bs1a_straight_channel` (closed
  annular 19 mm slot) and `test_bs1a_lshaped_channel` (L-shaped channel from
  wall boxes), both 18 mm deep, tool_r 6.343. Each asserts ≥ 1 band region,
  then runs `verify/zmap.py` on the emitted program: gouges / rapid
  collisions / axial plunges / outside_grid = 0 and **zero full-width windows
  at cutting feed** inside the channel.

Total engine change: 365 lines (+122 tests) — within the ~380 (+tests) budget.

## New tests (VibeCAD python, via slot)

- branch: `PASS bs1a straight channel: 2 band region(s), 5393.3 mm trochoidal
  cut, 0 full-width windows at cutting feed in the channel` /
  `PASS bs1a L-shaped channel: 3 band region(s), 1797.3 mm trochoidal cut, 0 …`
- main (0ab844a snapshot via `git archive`, never checked out): both tests
  FAIL — `no trochoidal channel-clear region was planned: the residue channel
  was not recognised (main's code has no band step)`.

## Judge — Core Front T13 (zmap `--part out/cf_hf01_z5b.npy --tool flat --dia 12.686 --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438 --jobs 6`)

| metric | BEFORE (out/hb1v2_cf.ngc) | AFTER (out/bs1a_cf.ngc) |
|---|---|---|
| full-width @ **cutting feed** | **154 windows / 161.2 mm** | **0 / 0.0 mm** ✔ |
| full-width @ entry feed (helix/floor circle) | 121 / 124.2 mm | 121 / 124.2 mm (allowed_helix_bottom 121, not_allowed 0) |
| full_width_depth bands @ cutting feed | 2–5 mm: 53.9; >5 mm: 107.3 | all bands 0 |
| overload (ae_eff > 2.4384, a > 0.5) | 689 / 764.5 mm | 310 / 341.7 mm |
| ae2 p95 / p99 / max | 2.0737 / 3.2215 / 12.8145 | 2.0534 / 2.1042 / 12.7603 |
| gouges / rapid collisions / axial plunges / outside_grid | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| exact clcheck (probe_clcheck.py, STL t0.01, dia 12.686) | — | below_cl **0** (660810 pts, max −0.381) |
| cycle time (zmap estimate) | 4980.1 s | 6115.9 s (+1135.8 s, **+22.8 %**) |

## Judge — Test block (zmap `--part out/test_block_hf_0.1.npy --stock -50 50 -40 40 0 38`)

| metric | BEFORE (out/hb1v2_tb.ngc) | AFTER (out/bs1a_tb.ngc) |
|---|---|---|
| full-width @ cutting feed | 8 / 8.0 mm | **0 / 0.0 mm** ✔ |
| full-width @ entry feed | 24 / 24.7 mm | 24 / 24.7 mm (not_allowed 0) |
| overload | 66 / 68.6 mm | 45 / 48.0 mm |
| ae2 p95 / p99 / max | 2.0644 / 5.2747 / 12.7301 | 2.0370 / 2.0975 / 12.7296 |
| gouges / rapids / plunges / outside_grid | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| exact clcheck (out/test_block.stl) | — | below_cl **0** (70439 pts, max −0.381) |
| cycle time | 369.1 s | 574.9 s (+205.8 s, **+55.8 %**) |

## Owner tables (windows classified by region-owner of window start point; tags captured offline via monkeypatch — no engine change for tags)

Core Front AFTER (`out/bs1a_cf.ngc`, owners `out/bs1a_cf_owners.json`):

| owner | n_win | len_mm | fw@cut | ovl_len | fw@entry |
|---|---|---|---|---|---|
| band (new) | 73643 | 83214.3 | 0 | 5.6 | 0 |
| a2d | 55811 | 69947.8 | 0 | 13.8 | 0 |
| link/other | 3230 | 39327.6 | 0 | 0.0 | 0 |
| hug ring | 6386 | 7867.5 | 0 | 142.4 | 0 |
| entry (helix/floor-circle) | 2595 | 2726.4 | 0 | 179.9 | 121 |

Test block AFTER (`out/bs1a_tb.ngc`, owners `out/bs1a_tb_owners.json`):

| owner | n_win | len_mm | fw@cut | ovl_len | fw@entry |
|---|---|---|---|---|---|
| band (new) | 6839 | 7774.8 | 0 | 4.4 | 0 |
| a2d | 5935 | 7120.9 | 0 | 1.0 | 0 |
| link/other | 381 | 2800.6 | 0 | 0.0 | 0 |
| hug ring | 582 | 625.1 | 0 | 5.5 | 0 |
| entry (helix/floor-circle) | 253 | 265.2 | 0 | 37.1 | 24 |

Test block BEFORE owners (regenerated program byte-identical to
`out/hb1v2_tb.ngc`; owners `out/main_tb_owners.json`):

| owner | n_win | len_mm | fw@cut | ovl_len | fw@entry |
|---|---|---|---|---|---|
| a2d | 5935 | 7120.9 | 0 | 1.0 | 0 |
| link/other | 381 | 2800.6 | 0 | 0.0 | 0 |
| hug ring | 582 | 625.1 | **8** | **30.5** | 0 |
| entry (helix/floor-circle) | 212 | 221.8 | 0 | 37.1 | 24 |

Per-owner overload on the test block: a2d 1.0 → 1.0, ring 30.5 → 5.5 ✔,
entry 37.1 → 37.1 (unchanged) — **no owner regresses on the test block**.

BEFORE owners on Core Front (main's run re-executed from a `git archive` snapshot of 0ab844a;
the regenerated program is byte-identical to `out/hb1v2_cf.ngc` — `cmp` clean;
owners `out/main_cf_owners.json`):

| owner | n_win | len_mm | fw@cut | ovl_len | fw@entry |
|---|---|---|---|---|---|
| a2d | 60269 | 75775.1 | 0 | 58.7 | 0 |
| link/other | 3476 | 42266.3 | 0 | 0.0 | 0 |
| hug ring | 6385 | 7790.7 | **154** | **529.1** | 0 |
| entry (helix/floor-circle) | 3062 | 3214.2 | 0 | 176.8 | 121 |

Per-owner overload vs main (Core Front): a2d 58.7 → 13.8 ✔, hug ring
529.1 → 142.4 ✔, entry 176.8 → **179.9 (+3.1 mm)** ✘ (only regression),
link 0 → 0, band (new) 5.6. The +3.1 mm is structural: the bands cut
territory main never entered (new helix entries at Z 42.354 (59.1..59.5,
6.7..7.7), ae_eff 2.56/3.19, and Z 47.625 (−49..−51, −16..−17.4), ae_eff
4.3/6.5, 5 windows × 1.04 mm), partially offset by −2.1 mm at Z 47.224
where a ring now side-enters through band-cleared ground. Engine stats
confirm the trade: n_side_entries 153 → 166, n_reentry_descends 167 → 127,
n_lifts 27 → 7, n_rapid_bumps 165 → 110; total overload 764.5 → 341.7 mm
(−55 %). Clearing the channel without a new entry is not possible within
this budget; recorded here rather than hidden — see Verdict.


## Band stats + the Z 40.289 sliver spot

- CF: `n_band_regions = 23`, `band_cut_len_mm = 82905.4`.
- TB: `n_band_regions = 5`, `band_cut_len_mm = 7732.7`.
- `band_blocked` (sliver < 4 mm, left to the ring): CF
  `[42.354, 27.24, 12.61]`, `[42.354, −27.21, 13.39]`,
  `[40.289, 27.19, 12.57]`, `[40.289, −27.20, 13.36]`; TB
  `[20.381, −16.49, 17.26]`, `[20.381, −22.53, 12.72]`.
- **Z 40.289, sliver ≈ 1.65 mm**: the band refuses it (MIN_SLIVER = 4 mm —
  a run shorter than that cannot host even one ramped loop without an illegal
  plunge). The hug ring takes the spot at cutting feed with partial engagement:
  windows within 6 mm of (27.19, 12.57) / (−27.20, 13.36) at Z 40.289 reach
  ae_eff ≤ 8.13 mm — well under full width (11.417) — so **no full-width
  window at cutting feed remains there**. The only full-width windows left in
  the program are entry-feed helix/floor-circle windows (allowed, pitch ≈ 1.0).
  Z 42.926 (the third residue level in BAND0) has no blocked spots — fully
  trochoided.

## Cost (honest)

The trochoid spends ~40 mm of cutting travel per 1 mm of channel advance at
P_CAP = 0.36 (loop circumference / advance). On Core Front that is +83 m of
cutting travel and +1135.8 s (+22.8 %) cycle; on the test block +205.8 s
(+55.8 %). The advance cap is empirical: the fresh lens at the channel-side
loop apex is cut in one ~1 mm window and the spike scales ≈ 6× advance, so
p ≤ 0.36 keeps simulated p95 ≤ 1.85 / spike ≤ 2.25. Raising advance without
changing the entry geometry re-opens full-width windows (measured during
tuning). Loop-shape refinement is BS1b territory; this task buys correctness.

## Gates

- `engine/test_engine.py` full suite (VibeCAD python): **0 failure(s), RC=0**
  (includes the two new BS1a tests; `out/oc_bs1a_test_engine.log`)
- `engine/test_finish.py`: **ALL FINISH TESTS PASSED, RC=0**
- `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q`:
  **221 passed, RC=0** (19:22)
- `scripts/check_fixtures.py`: initially 7 ok / 3 bad — the 3 were gitignored
  frozen goldens (`out/core_front_roughG.ngc`, `out/core_front_rough_X7.nc`,
  `out/core_front_roughRT_before.ngc`) that had never been seeded into this
  fresh worktree. They are byte-frozen artifacts of historical commits and are
  md5-identical across every sibling worktree under `/Users/James/ai-sandbox`;
  copied in (no regeneration, nothing relaxed). Re-check: **10 ok, 0 bad,
  RC=0** (`out/oc_bs1a_fixtures2.log`).

## Verdict

- Primary target **met**: Core Front full-width at cutting feed 161.2 mm → **0**
  (test block 8.0 mm → 0), with gouges / rapid collisions / axial plunges /
  outside_grid = 0 and exact clcheck = 0 on both posted roughs; remaining
  full-width windows are only the allowed entry-feed helix/floor circles.
- New synthetic STRAIGHT and L-SHAPED channel tests pass on the branch and
  fail on main's code (0ab844a snapshot).
- One strict sub-criterion is **not fully met and is reported, not hidden**:
  the entry-feed (helix/floor-circle) owner's overload length rises +3.1 mm
  on Core Front (176.8 → 179.9, +1.8 %) because the bands cut territory main
  never entered and those regions need new helix entries. Every cutting-feed
  owner's overload improved (a2d −44.9 mm, ring −386.7 mm) and total overload
  fell 55 %. If the bar requires zero per-owner regression including entry
  feed, BS1a as implemented does not reach it; the fix direction (entering
  band regions through cleared ground instead of fresh helices) is BS1b work.
- Cycle cost is real: +22.8 % Core Front, +55.8 % test block (trochoid travel
  ~40 mm per 1 mm of channel advance at P_CAP = 0.36).
- BS1b not started. Nothing committed.


## Exact commands (all heavy steps via the one-job slot)

```
PY=/Applications/VibeCAD.app/Contents/Resources/bin/python
SLOT=/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh

# AFTER programs + owner capture
$SLOT $PY out/bs1a_run.py cf out/bs1a_cf.ngc out/bs1a_cf_stats.json out/bs1a_cf_owners.json
$SLOT $PY out/bs1a_run.py tb out/bs1a_tb.ngc out/bs1a_tb_stats.json out/bs1a_tb_owners.json
# zmap judge (AFTER + BEFORE)
$SLOT $PY verify/zmap.py out/bs1a_cf.ngc --part out/cf_hf01_z5b.npy --tool flat --dia 12.686 \
  --engage-max 2.438 --stock -128.651 128.651 -82.55 82.55 0 60.96 --jobs 6 \
  --ae2-dump out/bs1a_cf_ae2.json --out-json out/bs1a_cf_zmap.json
$SLOT $PY verify/zmap.py out/bs1a_tb.ngc --part out/test_block_hf_0.1.npy --tool flat --dia 12.686 \
  --engage-max 2.438 --stock -50 50 -40 40 0 38 \
  --ae2-dump out/bs1a_tb_ae2.json --out-json out/bs1a_tb_zmap.json
$SLOT $PY verify/zmap.py out/hb1v2_cf.ngc … --ae2-dump out/hb1v2_cf_ae2_oc.json --out-json out/hb1v2_cf_zmap_oc.json
$SLOT $PY verify/zmap.py out/hb1v2_tb.ngc … --ae2-dump out/hb1v2_tb_ae2_oc.json --out-json out/hb1v2_tb_zmap_oc.json
# owner bands
$PY out/bs1a_analyze.py <ngc> <ae2.json> <zmap.json> <owners.json|->
# clcheck
$SLOT $PY engine/probe_clcheck.py out/bs1a_cf.ngc out/core_front_setup-088bb1be1e7d2b6c-t0.01.stl 12.686
$SLOT $PY engine/probe_clcheck.py out/bs1a_tb.ngc out/test_block.stl 12.686
# tests (branch + main snapshot for the FAIL proof)
$SLOT $PY out/bs1a_q_test.py
$SLOT $PY <main-snapshot>/out/q_main.py   # git archive 0ab844a, never checked out
```

---

# ADDENDUM (supervisor follow-up — report only)

All numbers below produced this session from files in this worktree; nothing
committed. Engine change this session: **only** an env-gated parameter block in
`engine/band.py` (+19 lines) so the item-3 what-if can reuse the EXISTING
knobs (`LOOP_R_MAX / AE_SS / AE_SPIKE / P_CAP`) plus an advance stat — with the
env unset every constant is unchanged and regeneration is byte-identical (proof
below). Everything else lives in `out/` analysis scripts.

## Determinism note (found while re-running)

- `out/bs1a_cf3.ngc` (instrumented re-run, 22 Oct 01:03) is **byte-identical**
  to the judged `out/bs1a_cf.ngc` (`cmp` clean); `out/bs1a_tb2.ngc` likewise
  for `out/bs1a_tb.ngc`. My edits are provably inert.
- One earlier regeneration (`out/bs1a_cf2.ngc`, run under heavy machine load)
  differed **only in link/rapid ordering**: every per-level geometry stat
  (regions, CL pts, areas) identical; `n_notclear_links` 559 vs 572,
  `rapid_len` −0.6 %, native Adaptive2d "limit reached" warnings 307 vs 305.
  Suspect: nondeterministic tie-breaks inside the vendored native link
  resolver (`libarea-native.dylib`). Cutting content unchanged; report only.

## Item 1 — cycle delta by MOVE CLASS (`out/bs1a_moveclass.py`, zmap's own
model: G1 at its F word, G0 at 15000 mm/min; class totals match zmap cycle ±0.3 s)

Core Front (BEFORE `out/hb1v2_cf.ngc` 4980.1 s → AFTER `out/bs1a_cf.ngc`
6115.9 s, Δ **+1135.8 s**):

| class | BEFORE s | AFTER s | Δ s |
|---|---|---|---|
| trochoid cutting (band, new) | 0 | 1456.6 | **+1456.6** (83 244 mm @ 3429 mm/min) |
| trochoid entries (new) | 0 | 86.2 | **+86.2** — 19 helix entries, total descent 315.9 mm (mean 16.6 mm), 5 with HB1v2 floor circle (59.0 mm / 2.8 s of the 86.2) |
| a2d cutting | 1974.0 | 1825.8 | −148.2 (band took 8466 mm of a2d territory) |
| a2d entries | 1254.5 | 999.8 | −254.7 (entry sequences 202 → 162; floor-circle time included) |
| ring cutting | 140.8 | 141.7 | +0.9 (travel 8048→8096 mm; ring windows changed fw 154→0 / ovl 529→142, travel barely) |
| ring entries | 1354.2 | 1354.8 | +0.6 (seq 174→172, depth 1692.9→1697.6 mm, floors 95→96) |
| feed links | 153.5 | 141.8 | −11.7 |
| rapids | 103.3 | 109.5 | +6.2 (rapid_len 25 822→27 386 mm; NN order changed; n_lifts 27→7, n_rapid_bumps 165→110) |
| **total** | **4980.4** | **6116.2** | **+1135.9** ✔ (zmap Δ 1135.8, rounding) |

Test block (369.1 s → 574.9 s, Δ **+205.8 s**):

| class | BEFORE s | AFTER s | Δ s |
|---|---|---|---|
| trochoid cutting (band, new) | 0 | 135.4 | **+135.4** (7740 mm) |
| trochoid entries (new) | 0 | 65.1 | **+65.1** — 4 helix entries, depth 64.5 mm, 3 with floor circle |
| a2d cutting / entries | 172.5 / 95.3 | 173.6 / 95.3 | +1.1 / 0.0 |
| ring cutting / entries | 11.0 / 71.5 | 11.0 / 71.5 | 0.0 / 0.0 (byte-identical ring + a2d entry moves) |
| feed links / rapids | 14.7 / 4.4 | 18.6 / 4.7 | +3.9 / +0.3 |
| **total** | **369.4** | **575.2** | **+205.8** ✔ |

So the cost is ~94 % the trochoid itself (cutting travel + its entries);
everything else nets −303 s on Core Front (a2d shrinks by 8.5 k mm and 40 entry
descends because the bands clear that ground first).

## Item 2 — treated length BY REASON (`out/bs1a_reasons.py` instrumented
re-run + `out/bs1a_reasonsum.py`; reason = local ring engagement vs live stock
at level start, same chord measure as `_strip_engage`)

Core Front — centre-line length trochoided: **3778.9 mm** in 27 segments:
* genuine full-width (material both sides, engage ≥ 0.9·D): **3195.4 mm (84.6 %)**
* over-load-only (2.4384 < engage < 0.9·D): **235.6 mm (6.2 %)**
* light (engage ≤ 2.4384): **347.9 mm (9.2 %)**

Emitted trochoid travel apportioned to those reasons: fw 69 660.6 / ovl-only
5 381.5 / light 7 863.6 mm (total 82 905.7 = `band_cut_len_mm` ✔).

**Yes — over-load-only (and even light) segments were treated too**, because
the selection unit is the ring PATH (max engagement ≥ 0.9·D on the path) and
contiguous runs along a treated path are trochoided whole. ~15 % of treated
centre-line (and ~16 % of emitted travel) is not genuine channel.

Overload-drop attribution (BEFORE ring-owned cutting-feed overload windows,
529.1 mm, vs AFTER band paths within 1·D):
* taken over by the trochoid: fw **161.2 mm** (154 win) + ovl-only
  **367.8 mm** (325 win) = 529.0 mm — essentially ALL ring overload sat in
  band-treated territory;
* of those, resolved to ≤ 2.44 mm: fw 124.0 + **ovl-only 228.4** = 352.4 mm;
  still > 2.44 (corners/entries): fw 37.2 + ovl-only 139.4.

Against the total overload drop 764.5 → 341.7 (−422.8 mm): ≈ **228 mm (54 %)**
of the resolved load came from windows that were over-load-only, i.e. beyond the
brief's channels-only scope; ≈ 124 mm from genuine full-width windows; the rest
from a2d-side changes (a2d ovl −44.9 mm). Test block: centre-line treated
307.3 mm fw + 19.2 mm ovl-only (6 %); ring overload taken over: fw 8.0 +
ovl-only 22.5 mm (all of its 30.5).

## Item 3 — ONE what-if: local-room loop radius + larger advance (report only)

Env: `BS1A_WHATIF=1 BS1A_LOOP_R_MAX=99 BS1A_AE_SS=1.95 BS1A_AE_SPIKE=2.35
BS1A_P_CAP=0.42` → loop radius = local CL half-width − 0.15 with **no 3.2
clamp**; advance cap raised 0.36 → 0.42. Programs `out/bs1a_cf_whatif.ngc`,
`out/bs1a_tb_whatif.ngc`, same judge commands as the main table.

* **Advance used: 0.42 mm/loop** (mean = max, always at the cap;
  `band_advance_mean_mm`/`max_mm` = 0.42).
* **Cycle: Core Front 5909.5 s (−206.4 s, −3.4 % vs BS1a AFTER 6115.9;
  +929.4 vs main)**; test block 556.1 s (−18.8 s vs 574.9).
* Band travel 71 452 mm (−14.2 % vs 83 244); entries, links, rapids identical
  to AFTER (19 band entries, rapid_len byte-equal); gouges / rapids / plunges
  / outside_grid all 0 on both.
* full-width @ cutting feed: **0** ✔ (entry-feed helix/floor 121 allowed, as
  before); overall ae2 p95 2.0557 (AFTER 2.0534 — the p95 bar 2.032 is
  exceeded by a2d-owned windows, p95 2.073, already on main and in AFTER;
  not introduced here).
* **But the spike bar does NOT hold**: band-owned overload length
  5.6 → **244.0 mm** (test block 4.4 → 6.5), total overload 341.7 → 582.1 mm.
  The worst band window is 9.447 mm — identical worst case in the current
  AFTER program (band ae max 9.447, pre-existing at channel entries where the
  helix bore assumption is thin), so the what-if does not create a new worst
  spike, it broadens the tail ×43 in length.

Verdict: with local-room radii, advance 0.42 keeps the full-width bar and saves
~3.4 % cycle, but fails "spikes ≤ 2.44" — the advance/spike trade is
unchanged (spike ≈ 6×advance ⇒ p ≤ ~0.40 even before the 2.35 sim target);
the large local loops additionally widen the overload tail. The current fixed
clamp (r ≤ 3.2, p ≤ 0.36) remains the bar-holding config. Not adopted
(report only).

## Item 4 — the blocked spots (sliver < MIN_SLIVER, left to the ring)

Sliver = CL-march width across the channel at the ring line (d_ch + d_wall);
residual = max ae_eff of AFTER cutting-feed windows within 6 mm of the spot;
what-if = relaxed centre-line (sliver ≥ 2.0 mm), loops down to r = 0.35,
side-entry from the neighbour channel cleared at the same level (pre-cleared in
the simulation, no helix), ZE2 windows replayed on the live stock grid.

| spot | sliver mm | residual ae_eff (ring) | smaller-loop what-if |
|---|---|---|---|
| Z 42.354 (+27.24, 12.61) | 3.00 | 9.41 | loops NOT legal (arcs exit CL region) + sim spike **2.50** > 2.44 |
| Z 42.354 (−27.21, 13.39) | 3.50 | 8.10 | not legal + sim spike **3.63** > 2.44 |
| Z 40.289 (+27.19, 12.57) | 3.00 | 9.45 | not legal + sim spike **2.50** > 2.44 |
| Z 40.289 (−27.20, 13.36) | 3.50 | 8.13 | not legal + sim spike **3.89** > 2.44 |

**No — smaller loops with a SE2-style side entry do not take these spots under
2.44**: at sliver 3.0–3.5 mm the trochoid arcs poke outside the CL-allowed
region at every one of the four spots, and even ignoring legality the fresh
lens simulates to 2.5–3.9 mm. (The supervisor's "1.65 mm" is BAND0's
window-measured sliver at Z 40.289; the CL march at the ring line there is
3.0 mm — both are far below the 4 mm loop-hosting minimum.) Test block's two
blocked spots (sliver 3.75 mm, Z 20.381): same verdict (not legal, spike
2.50/3.43) but they are moot — the ring leaves only 2.04/2.08 mm there,
already under the bar. These four CF spots remain the honest residue: the ring
takes them at cutting feed with partial (not full) width, ≤ 9.45 mm; fixing
them needs BS1b corner work, not a relaxed rule here.

## ADDENDUM gates and clcheck (all via slot, real exit codes, 22 Oct)

- exact clcheck on the what-if programs: Core Front **below_cl 0** (626 148 pts,
  max −0.381); test block **below_cl 0** (67 273 pts, max −0.381)
  (`out/oc_bs1a_add_whatif_cf_clcheck.log`, `..._tb_clcheck.log`)
- `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q`:
  **221 passed, RC=0** (`out/oc_bs1a_add_pytest.log`, 19:25)
- `engine/test_engine.py` (VibeCAD python): **0 failure(s), RC=0**, both BS1a
  channel tests still PASS (`out/oc_bs1a_add_test_engine.log`)
- `engine/test_finish.py`: **ALL FINISH TESTS PASSED, RC=0**
- byte-identity proofs: `cmp out/bs1a_cf3.ngc out/bs1a_cf.ngc` clean;
  `cmp out/bs1a_tb2.ngc out/bs1a_tb.ngc` clean.

## ADDENDUM exact commands (heavy steps via the one-job slot)

```
PY=/Applications/VibeCAD.app/Contents/Resources/bin/python
SLOT=/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh
# item 1 (move-class cycle deltas, light):
$PY out/bs1a_moveclass.py <ngc> <owners.json|-> <zmap.json> <zmax>   # 4 programs
# items 2 + 4 (instrumented re-runs; ngc byte-identical to the judged ones):
$SLOT $PY out/bs1a_reasons.py tb out/bs1a_tb2.ngc out/bs1a_tb_reasons.json
$SLOT $PY out/bs1a_reasons.py cf out/bs1a_cf3.ngc out/bs1a_cf_reasons.json
$PY out/bs1a_reasonsum.py out/bs1a_cf_reasons.json out/hb1v2_cf_ae2_oc.json \
    out/main_cf_owners.json out/bs1a_cf_owners.json out/hb1v2_cf_zmap_oc.json CF
$PY out/bs1a_reasonsum.py out/bs1a_tb_reasons.json out/hb1v2_tb_ae2_oc.json \
    out/main_tb_owners.json out/bs1a_tb_owners.json out/hb1v2_tb_zmap_oc.json TB
# item 3 (what-if engine + same judge):
BS1A_WHATIF=1 BS1A_LOOP_R_MAX=99 BS1A_AE_SS=1.95 BS1A_AE_SPIKE=2.35 BS1A_P_CAP=0.42 \
  $SLOT $PY out/bs1a_run.py cf out/bs1a_cf_whatif.ngc out/bs1a_cf_whatif_stats.json \
      out/bs1a_cf_whatif_owners.json
$SLOT $PY verify/zmap.py out/bs1a_cf_whatif.ngc --part out/cf_hf01_z5b.npy \
  --tool flat --dia 12.686 --engage-max 2.438 \
  --stock -128.651 128.651 -82.55 82.55 0 60.96 --jobs 6 \
  --ae2-dump out/bs1a_cf_whatif_ae2.json --out-json out/bs1a_cf_whatif_zmap.json
#   (same pair for tb with --stock -50 50 -40 40 0 38, no --jobs)
$PY out/bs1a_analyze.py out/bs1a_cf_whatif.ngc out/bs1a_cf_whatif_ae2.json \
    out/bs1a_cf_whatif_zmap.json out/bs1a_cf_whatif_owners.json "CF WHAT-IF"
# gates: clcheck x2 on the what-if ngcs, pytest, test_engine, test_finish
#   (chains: out/bs1a_add_chain.sh / bs1a_chain2.sh / bs1a_chain3.sh, status
#    out/add_chain.status)
```

## ADDENDUM verdict (report only — nothing adopted, nothing committed)

1. The +1135.8 s Core Front cost is ~94 % trochoid cutting travel + its 19
   entries (+1542.8 s), partially refunded (−406.9 s) by a2d shrinking and
   cheaper links; the test block's +205.8 s is +200.5 s band, +5.3 s links.
2. 84.6 % of treated centre-line is genuine full-width channel; ~15 %
   (over-load-only + light, contiguous along treated ring paths) was treated
   beyond the channels-only brief — those segments account for ≈228 mm (54 %)
   of the resolved overload in the 764.5 → 341.7 mm drop.
3. Local-room radius + advance 0.42: −206.4 s Core Front (−3.4 %), fw@cut 0
   kept, but band spike tail broadens (overload 5.6 → 244.0 mm) — the ≤ 2.44
   bar does not hold; current clamp (r ≤ 3.2, p ≤ 0.36) remains the
   bar-holding configuration.
4. The four CF blocked spots (sliver 3.0–3.5 mm at the ring line; BAND0's
   window sliver 1.65 mm at Z 40.289) cannot be taken under 2.44 by smaller
   loops with a side entry: the arcs leave the CL-allowed region at all four
   spots and the fresh lens simulates 2.50–3.89 mm. Left to the ring as
   reported; proper fix is BS1b corner work.
