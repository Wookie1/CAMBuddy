# BS1a4 results

Session start: Fri Oct 23 18:19 MST (hard cap ~20:19). Worktree
`/Users/James/ai-sandbox/stevecam-bs1a4`, branch bs1a4 @ a93b05c (code = e5e783e).
No commits made. All tests/jobs run through `slot_m4.sh` (ENGINE_WORKERS=4);
no Core Front engine or zmap job.

## STOP - triggered (see section 6)

Fix 1 + Fix 2 are implemented and behave as specified on the TEST BLOCK, but
**FW at cutting feed rises 0 -> 8 and spike-overload windows rise 14 -> 32**
when the ungated region is dropped (the hug ring slots that stock at ae_eff up
to 12.60 mm = full width). Per the brief's STOP rule I halted **before any
further change**: no new tests were added to engine/test_engine.py, and the
engine code is left as described below pending supervisor decision.

## (0) Step-0 report - TEST BLOCK on main (e5e783e)

Every band region emitted with no shrink level passing its gate (engine
`_simulate` ladder replayed via spies during `rough()` on out/test_block.stl;
judge numbers from verify/zmap.py --ae2-dump on the same NGC, padded grid
out/test_block_hf_0.1):

**Exactly ONE ungated region is emitted on the test block.**

| place (start x,y) | Z | removed area (best level, mm2) | path travel (mm) | best level max ae - engine | zmap max ae, same moves | who cuts its stock if dropped |
|---|---|---|---|---|---|---|
| (6.276, -2.078) | 27.381 | 266.25 (emitted level shrink 0.4) | 618.7 | spike 4.50 / ss 2.75 (emitted level); best spike over levels 4.25 @ shrink 0.55 (ss 2.25) | **12.68** (max over 529 windows; 0.9xD = 11.42 -> 8 of them are FW) | the level's own **hug ring** (same Z, ring points cover the channel; with the band present its windows there read up to 8.87, post-drop they read up to **12.60 = full width at cutting feed**) |

All four shrink levels fail the gate (bars ss<=1.85, spike<=2.25):

| shrink | engine spike | engine ss | verdict |
|---|---|---|---|
| 1.00 | 4.75 | 2.00 | fail |
| 0.75 | 4.50 | 2.25 | fail |
| 0.55 | 4.25 | 2.25 | fail |
| 0.40 | 4.50 | 2.75 | fail -> **emitted anyway** (main's fall-through) |

The emitted path reads max ae_eff **8.467** in zmap on its own moves (still
>> the 2.25 spike bar, but below the 0.9xD FW bar - which is why main shows
FW@cutfeed = 0 here). The engine's ladder sees only 4.25-4.75, i.e. the
planner cannot see what the judge measures (window misalignment + disk-sampling
under-read). Later planners if dropped: same-level hug ring (covers it, see
above); later levels' a2d/rings would reach the deeper stock below.

## (1) Line count

`git diff --numstat e5e783e -- engine/band.py engine/rough.py` ->
`38 14  engine/band.py` = **52 changed non-test lines** (budget <= 60;
STOP at ~80). engine/rough.py unchanged.

## (2) Changes (all in engine/band.py)

Fix 1 - a region that fails its gate at every shrink level is never emitted:
- `engine/band.py:325-327` - `gate_ok` flag + best-level tracking
  (`best_ae`, `best_area`) initialised before the shrink ladder.
- `engine/band.py:340-342` - best level recorded per tried level;
  `gate_ok = True` only when `ss <= AE_SS and spike <= AE_SPIKE`.
- `engine/band.py:350-364` - reject branch after the `pts_out >= 4` filter:
  when no level passed, the region is NOT emitted; it is recorded in
  `stats["bs1a_rejected"]` as `(x, y, z, area, best_ae)`; the seg is NOT
  marked `done`, so another ring can still re-plan the channel at this level,
  and its stock stays in the LIVE model for every later planner (this level's
  rings, link_clear, side entries, a2d, re-mill). There is no other built-in
  fallback in `channel_regions` - the ring IS the fallback (Step-0 above).
- `engine/band.py:376-377` - `stats["failed_region_emitted"]` accounting:
  emissions minus gate-passing emissions; structurally 0, computed not assumed.

Fix 2 - `_simulate` windows match zmap's move-aligned windows:
- `engine/band.py:163-186` - `prev` starts at `path[0]`, so the first move's
  length enters window 0 (was: zero-length first window swallowing the whole
  first-move disk); the `prev is None` special case is gone. A move >= 1 mm is
  now its own window, exactly like zmap `_ae2_windows` (verify/zmap.py:975-1029).

## (3) Exit codes (all run by me, via slot_m4.sh)

- `bs1a4_step0.py` (Step 0 diagnostic, test block): **EXIT=0**
- `bs1a4_check.py <base> base` (e5e783e via `git archive`, never checkout): **BASE_EXIT=0**
- `bs1a4_check.py <worktree> fixed`: **FIXED_EXIT=0**
- `bs1a4_align.py base|fixed` (channel-case window-alignment): see section 4 logs
- full `engine/test_engine.py` on the fixed tree: see section 5

Behaviour contrast (the "fails on e5e783e" evidence, since no new tests were
added - STOP fired first):
- base (e5e783e): `n_band_regions=1`, `stats["failed_region_emitted"]`
  **MISSING** (ungated emit happens, stat does not exist), `bs1a_rejected=[]`
- fixed: `n_band_regions=0`, `failed_region_emitted=0`,
  `bs1a_rejected=[[6.276, -2.878, 27.381, 294.75, 4.25]]`

## (4) Max engine-vs-zmap window difference, both ways

(pending - filled from bs1a4_align_{base,fixed}.json below)

## (5) Existing test suite

(pending - filled from bs1a4_fullsuite_fixed.log)

## (6) STOP report

STOP conditions hit on the TEST BLOCK after Fix 1 (+Fix 2):
- **FW at cutting feed rises: 0 -> 8** (ae_eff >= 0.9xD, a > 0.5, cutting
  feed). The 8 windows are the level-Z27.381 hug ring slotted along
  y=-6.24, x 14.3->19.3 and x=20.24, y 0.3->1.3 (the rejected region's
  channel), ae_eff 11.68-12.60 mm, a = 10.62 mm.
- **spike-overload rises: 14 -> 31** windows with ae_eff > 2.438 (a > 0.5) at
  cutting feed; max 8.87 -> 12.60 mm.
- Not hit: gouges / rapid_collisions / axial_plunges / outside_grid all 0;
  failed_region_emitted = 0.

Interpretation: on this part the ungated trochoid, although it violated its
own gate (engine 4.5 vs bar 2.25; judge 8.47), was still cutting ~3x lighter
than the ring that inherits its stock when it is dropped (judge 12.60 = full
width). A pure reject-with-no-fallback therefore makes the test block WORSE at
the judge. Options for the supervisor (not implemented, per STOP): reject only
when a lighter fallback is confirmed to exist (ring load cap check against the
spike bar before dropping), multi-pass channel clearing, or gate retune. The
dropped region's stock IS seen by a later planner (the ring), so the first
STOP clause ("stock unseen") is not the problem - the load is.
