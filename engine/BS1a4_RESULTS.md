# BS1a4 results

Session start: Fri Oct 23 18:19 MST (hard cap ~20:19). Worktree
`/Users/James/ai-sandbox/stevecam-bs1a4`, branch bs1a4 @ a93b05c (code = e5e783e).
No commits made. All tests/jobs run through `slot_m4.sh` (ENGINE_WORKERS=4);
no Core Front engine or zmap job.

## STOP - triggered (see section 6) - RESOLVED by BS1a4b (sections 7-9)

Fix 1 + Fix 2 are implemented and behave as specified on the TEST BLOCK, but
**FW at cutting feed rises 0 -> 8 and spike-overload windows rise 14 -> 32**
when the ungated region is dropped (the hug ring slots that stock at ae_eff up
to 12.60 mm = full width). Per the brief's STOP rule I halted **before any
further change**: no new tests were added to engine/test_engine.py, and the
engine code is left as described below pending supervisor decision.

**BS1a4b follow-up (this session, branch bs1a4 @ d41c89d + uncommitted):** the
supervisor decision arrived as TASK_BS1a4b.md - a gate-failing region now takes
its LIGHTEST measured option among {each shrink level, dropping to the ring}
and is never silent. See sections (1) [updated count], (4), (5), (7), (8), (9).

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
BS1a4 WIP: `38 14 engine/band.py` = 52 changed lines.
After BS1a4b (revised Fix 1 + alignment split in `_simulate`):
**`61 15 engine/band.py` = 76 changed non-test lines** (budget <= ~80 vs
e5e783e IN TOTAL). engine/rough.py unchanged.

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

Measured on the TEST BLOCK, emitted band region (start 6.276,-2.078, Z27.381),
engine `_simulate` on the EMITTED moves vs zmap `--ae2-dump`, both on the
0.5 mm grid (the same cell the engine stock model uses; the 0.5 hf padded
tool_r+5 mm like the judge grid) - from `test_bs1a4b_windows_align_zmap` /
scratchpad `bs1a4b_diag2.py`:

- **Window boundaries: IDENTICAL** - 791 engine windows vs 791 zmap windows,
  closing-move index equal for every window (after Fix 2 + the >45 deg
  chord-break link rule added in BS1a4b; on e5e783e the counts were 555 vs
  529 and every boundary was shifted).
- **max (engine - zmap) = +3.883 mm** (window k=17, xy~(8.52,-3.76): engine
  counts 4.00 mm2 removed where zmap had already counted those cells in an
  earlier window - engine live-stock vs judge-replay divergence).
- **max (zmap - engine) = +3.865 mm** (window k=1, xy~(6.59,-3.66): zmap
  counts 5.00 mm2 at a=10.62 mm that `_simulate`'s entry-bore pre-clear
  (1.3 x tool_r assumed pre-cut by the helix) makes the engine blind to).

The 0.15 mm bar is **NOT met**: the residual is not windowing (boundaries are
exact) but the bore pre-clear convention + disk-sampling/stock-model
divergence - the planner blind spot already documented in Step 0, present on
e5e783e as well (there it is compounded by the one-move boundary offset).
Closing this needs a measurement change in `_simulate` (real bore geometry /
swept-disk on the judge grid), outside this task's budget and scope.

## (5) Existing test suite

Full `engine/test_engine.py` (34 tests incl. the 2 new BS1a4b tests) via
slot_m4.sh on the fixed tree: **SUITE_EXIT=__** (per-test lines in
scratchpad `bs1a4b_fullsuite.log`; exit codes pasted in section (8)).

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

## (7) BS1a4b - revised Fix 1 (supervisor decision), file:line

All in engine/band.py (engine/rough.py untouched; no zmap/verify import):

- `engine/band.py:44-45` - constants `SPIKE_MM = 2.44` (judge overload bar,
  zmap OVERLOAD_WIDTH_MM) and `DIR_COS = cos(45 deg)` (zmap AE2_DIR_MAX_DEG
  link rule).
- `engine/band.py:168-177` - `_simulate` now breaks a window at a chord
  direction change > 45 deg and drops the sub-1 mm fragment there, exactly
  like zmap `_ae2_windows` link/close; with Fix 2's non-zero first window
  (`:165`) every engine window spans what the judge's window spans.
- `engine/band.py:199-206` - `_opt_key(wins, ends, fw_min)`: rank key of an
  option = (# windows >= FW_TRIGGER x D at cutting feed, max ae, travel in
  windows over SPIKE_MM), measured on the aligned `_simulate` windows.
- `engine/band.py:292` - the DROP option per ring path = the ring's own
  simulated windows over the live stock (`wins`/`wb`, already computed for FW
  marking) keyed by `_opt_key` -> `("drop_ring", None, wins)`.
- `engine/band.py:344-360` - the shrink ladder records every tried level
  (`opts`: shrink, path, wins, ends) and `best_area`.
- `engine/band.py:364-381` - supervisor decision, replacing the WIP reject:
  when NO shrink level passes the gate, take `min` of
  {each tried level, drop_ring} by (FW windows, max ae, over-2.44 travel);
  ties keep the trochoid (drop is last). The region is recorded in
  `stats["failed_region_emitted"]` as `{x, y, z, area, option, max_ae}`
  (place = segment start, Z, best removed area, chosen option, engine max ae
  of the chosen option) - never silent. `option == "drop_ring"` emits
  nothing (stock stays live for the ring, seg not marked done); a
  `shrink*` option emits that level's trochoid (marked done, counted in
  n_band_regions / band_cut_len_mm). `bs1a_rejected` (WIP) is subsumed by
  this ledger's option field.
- `engine/band.py:399` - `stats["failed_region_emitted"]` key is always
  present (list, possibly empty).

Decision on the test block: dropping to the ring has FW >= 1 at cutting feed
(it is the FW windows that proposed the region; judge reads them at 12.60 =
full width), every shrink level has FW = 0 with max ae 4.25-4.75 -> lightest
= **shrink0.55** (max ae 4.25): the trochoid (zmap 8.47 there) is kept over
the ring slot, and FW at cutting feed on the padded 0.1 judge grid stays 0 =
main's level. Gates AE_SS / AE_SPIKE untouched; no feed/margin/leave change.

New tests (engine/test_engine.py, both registered in `_main()`):
`test_bs1a4b_failed_region_lightest` (region listed with all fields, option
is a trochoid not drop_ring, FW@cutfeed == main's 0 on the padded 0.1 grid)
and `test_bs1a4b_windows_align_zmap` (boundaries identical, max difference
both ways reported - see section (4) for why the 0.15 mm area bar is not met
and is reported rather than asserted).

## (8) BS1a4b exit codes (all run by me via slot_m4.sh, ENGINE_WORKERS=4)

- `test_bs1a4b_failed_region_lightest` (fixed tree, standalone): **T1_EXIT=0**
- full `engine/test_engine.py` (fixed tree): **SUITE_EXIT=__**
- fail-on-e5e783e (`git archive e5e783e` into scratchpad `bs1a4b_e5e`, my
  test file copied in, never a checkout):
  - `test_bs1a4b_failed_region_lightest`: **BASE_T1_EXIT=__**, assertion:
    `__`
  - `test_bs1a4b_windows_align_zmap`: **BASE_T2_EXIT=__**, assertion:
    `__`

## (9) failed_region_emitted on the test block

One region (the only ungated one, matching Step 0):
`{x: 6.276, y: -2.878, z: 27.381, area: __ mm2, option: "shrink0.55",
max_ae: 4.25 mm}` - emitted as a trochoid (zmap max 8.47 on its own moves,
below the 11.42 mm FW bar), ring keeps its lighter skim; FW at cutting feed
over the whole program: 0 (= main).

## (10) BS1a4c - honest (backed) entry credit + alignment bar

Session start Fri Oct 23 19:51 MST (hard cap ~21:51), branch bs1a4 @ 39c01b4,
no commits. All tests via slot_m4.sh (ENGINE_WORKERS=4); no Core Front engine
or zmap job. Reference f3f2165 read with `git show` only (never
cherry-pick/checkout).

### Change (45 non-test lines vs 72ea825: band.py +18/-1, rough.py +24/-2;
### 30-line target exceeded by the mandated emit-time backing - stopped at the
### ~45 hard stop, no further engine change)

engine/band.py:
- `engine/band.py:199-211` - `entry_credit(stock, p0, z, tool_r)`, ported to
  MATCH bs1b f3f2165 (`git show f3f2165:engine/band.py` lines 192-206):
  credit exactly the radius-tool_r disk an emitted helix really bores -
  `tool_r` ONLY where standing material (`top > z + 0.05`) under the start
  disk forces that helix at emit time, else 0. The synthetic 1.3 x tool_r
  pre-clear is gone from the region planning sims.
- `engine/band.py:367-369` - the shrink ladder simulates with
  `cr = entry_credit(stock, path[0], z, tool_r)` instead of `1.3 * tool_r`.
- `engine/band.py:410-411` - every emitted band region carries
  `"credit"` = entry_credit at the EMITTED start point (backed at emit time).

engine/rough.py (emit-time backing of BAND regions ONLY; `_stepdown_rings`
sims ~959/~994 untouched - BS1b's):
- `engine/rough.py:1121` - `stats["credit_fallback"]` always present (list);
  `:1123` `helix_n` counter of emitted entry helices; `:1516` successful
  `helix_entry` increments it.
- `engine/rough.py:2065,2068-2085` - after `enter_at`: a region carrying
  credit whose entry emitted NO helix (`helix_n` unchanged) must have a
  live-clear start disk (`stock.link_clear([q4,q4], z)`); otherwise
  `ladder_helix` (emit the helix now), else credit-0 re-check of the region's
  cutting path against AE_SS/AE_SPIKE -> `replan0_ok`, else `replan0_drop`
  and the cutting path is NOT emitted (`:2111`). Every fallback recorded in
  `stats["credit_fallback"]` as `(x, y, z, act)`.
- `engine/rough.py:2023-2024` - imports `_simulate`, `AE_SS`, `AE_SPIKE`
  from engine.band (engine -> engine only; no zmap/verify import).

Tests (engine/test_engine.py, registered in `_main()`):
- NEW `test_bs1a4c_backed_credit`: `stats["credit_fallback"]` exists; every
  emitted band region carries a credit in {0, tool_r} EQUAL to
  `entry_credit` on the live planning stock (never the synthetic bore); every
  recorded fallback act is one of ladder_helix/replan0_ok/replan0_drop.
- `test_bs1a4b_windows_align_zmap` (new in this branch, mine): spy replay now
  uses the region's carried credit instead of `1.3 * tool_r`; stale root-cause
  comment replaced with the BS1a4c finding. The 0.15 mm bar is NOT asserted
  - the STOP below fired.

### Both max differences (test block, emitted region start (6.276,-2.0778),
### Z 27.381, credit 6.343 = tool_r, `credit_fallback = []` - the credit was
### backed at emit by the entry helix actually emitted; boundaries identical,
### option unchanged `shrink0.55`):

- max (engine - zmap) = **+14.070 mm** (over-read, REPORT-ONLY per brief;
  145 windows > 0.15). Worst at k=0, xy (7.10,-2.63): the engine counts the
  fresh channel disk in the region's first window while zmap's replay had
  already removed those cells during the emitted entry (helix + floor circle
  sweep an offset-centre stadium, not the credit disk about the start point).
- max (zmap - engine) = **+1.488 mm** (under-read; was +3.865 in BS1a4b -
  the entry-bore pre-clear under-read at k=1 is GONE, replaced by an
  over-read there; the remaining under-read moved to the light-load windows).

### STOP (brief item 3): under-read still over 0.15 -> no more fixes.
All 70 windows over 0.15 BELOW zmap (full listing scratchpad
`bs1a4c_diag.log`, cause per window):
- **credit / bore geometry - 1 window**: k=19, xy (6.72,-4.00), -0.250 mm:
  the tool_r credit disk about the START pre-clears a cell that the emitted
  helix's real bore (offset centre + floor circle) left standing, so zmap
  re-counts it inside the region.
- **grid resolution / disk sampling - 69 windows**: k=163..714 along the
  trochoid advance (x 14.2..20.2, y -5.9..+2.2), diffs -0.188..-1.488 mm,
  all light-load (both engine and zmap ae <= 1.5 mm; deltas are single
  0.25 mm2 cells over ~1 mm windows): the engine's cell-centre disk sampling
  on its 0.5 mm stock grid misses partial cells zmap's replay counts - the
  disk-sampling under-read documented in BS1a4 Step 0. No earlier MOVE KIND
  is missed by the engine stock here (engine cumulative removed area tracks
  zmap's; no stock-divergence class window appeared), and NO windowing cause
  remains (boundaries identical, asserted).

### Exit codes (all run by me via slot_m4.sh, ENGINE_WORKERS=4)
PENDING_PLACEHOLDER_EXITCODES

### fail-on-e5e783e (`git archive e5e783e` -> scratchpad `bs1a4c_e5e`, my
### test file copied in, never a checkout)
PENDING_PLACEHOLDER_BASE

`git diff e5e783e -- engine/test_engine.py` has exactly ONE "-" line - the
old `_main()` tuple closing line `test_rr1a_rough_cli_refuses_ball):` - no
existing test or assertion changed.


## (12) BS1a4c-2 - every emitted band cutting chord is CL-checked; a
## discontinuous trochoid is split or rejected

Session Fri Oct 23 21:00 - 22:15 MST (hard cap 23:00), worktree
stevecam-bs1a4 branch bs1a4, base 351ce50 read with `git show` (never
checkout). NO commits. All tests via slot_m4.sh (ENGINE_WORKERS=4); NO Core
Front engine or zmap job. No lock files touched; no stuck slot.

### Change (40 non-test lines vs 351ce50: band.py +35/-5, rough.py +0/-0;
### 30-line target exceeded by the mandated reject-and-list bookkeeping,
### kept under the ~45 hard stop; rough.py unchanged - the fix sits at the
### emitter source, band-path emission only)

engine/band.py:
- `engine/band.py:89-101` - `_split_at_jumps(isl_ok3, pts)`: splits a band
  path at every chord that fails a segment-sampled CL check, sampling every
  <= 0.25 mm (n = ceil(dist/0.25), endpoints inclusive) - the way
  validate_exact samples segments. Every chord that survives into emission is
  therefore segment-sampled CL-clean, not just its two points.
- `engine/band.py:418` - the chosen (gate-passed or lightest gate-failed)
  shrink path is split with `_split_at_jumps` after the existing isl_ok3
  point filter (filter first, so chords created by dropping forbidden points
  are the jumps the splitter sees).
- `engine/band.py:419-431` - a piece shorter than 4 points has no legal join
  (cannot host a loop and is not worth an entry): REJECTED, never silent -
  place/Z/area/option (+ " split") appended to
  stats["failed_region_emitted"]; if every piece is a stub the whole seg is
  skipped (stock stays live for the ring, done-marking not applied).
- `engine/band.py:437-441` - each surviving piece is emitted as its OWN
  region (own honest `credit`, own start): rough.py's existing per-region
  `enter_at` ladder (link / side / helix, each CL-checked) joins the pieces
  in place of the raw chord. Per-region stats needed no change (a region
  still carries exactly one cutting path).

### (a) max window = FIRST window at entry? (instrumented `_simulate` on the
### L-channel case, Z 0.381, honest credit bore = tool_r = 6.343)
- region (-18.724,-0.115) shrink1, max_ae 15.25: FIRST window IS the max -
  argmax = 0, w0 = 15.25 (window 0 of 996/743/502/348 at shrink
  1.0/0.75/0.55/0.4 - the same 15.25 at EVERY shrink level).
- region (-2.09,5.742) shrink0.4, max_ae 13.5: argmax = 1 (second window),
  w0 = 12.75 - the max sits in the first ~2 mm of travel at entry, and is
  likewise identical (13.50) at every shrink level.
Both maxima are INVARIANT under trochoid shrinkage - the load is fixed by the
entry geometry, not by the loops: consistent with the suspected start-centred
credit disk vs the real off-centre helix bore + floor circle over-read (the
sim pre-clears a tool_r disk about path[0]; the actual entry bores about the
helix centre and the floor circle sweeps an annulus, so cells the disk missed
are counted as fresh loop cut). Confirms the BS1a4d target; no engine change
made here for it (report only).

### (b) other emit paths checked only by their points (or sampled coarser
### than the judge's 0.25 mm), grep of engine/rough.py + engine/band.py
- engine/rough.py:2112 - generic cutting-run emit for EVERY non-band region
  (a2d paths AND hug rings): `good = isl_ok(pts)` gates POINTS only; chords
  between consecutive good points are emitted as G1 cutting moves without
  segment sampling (band paths now arrive chord-clean from band.py:89).
- engine/rough.py:2137-2147 - clip-bridge chord sampled at ~0.5 mm
  (`ns = ceil(d/0.5)`, isl_ok3) - coarser than 0.25 mm.
- engine/rough.py:2233 - a2d deep linkclear corridor: isl_ok3 on corridor
  POINTS + corridor_ok per segment (engine/rough.py:1885-1900, 0.4 mm +
  midpoints) - coarser than 0.25 mm.
- engine/rough.py:2269 - RT at-depth feed link: `all(isl_ok(corridor))` on
  corridor points only (+ stock.link_clear at z+lift); chords not
  part-sampled.
- engine/rough.py:2301 - link landing point checked by isl_ok([land]) alone.
- engine/rough.py:1634,1642 - enter_at ladder steps 1-2 straight links use
  corridor_ok = 0.4 mm + midpoint sampling - coarser than 0.25 mm.
- engine/rough.py:1246 - HB1v2 floor circle: isl_ok(circ) with
  n = max(16, 2*pi*r/0.5) -> ~0.5 mm point spacing.
- engine/rough.py:1284 - helix candidate return segment: sampled at 0.4 mm.
- engine/rough.py:1438 - SE2 side feed-in path: isl_ok3 at ~0.4 mm spacing.
- engine/rough.py:864 - hug_regions keeps ring points by isl_ok at POINTS
  only (ring chords are later emitted through rough.py:2112 unchecked).
- engine/rough.py:1997, 2034 - region entry candidates chosen by isl_ok on
  points only (the entry move itself still passes the enter_at ladder).
- engine/band.py:412-415 - band path points gated by isl_ok3 (points only);
  as of this task complemented by the chord splitter at engine/band.py:418.
- (not a gap) engine/band.py:64 `_march` samples at MARCH_STEP = 0.25 mm -
  already judge resolution.

### Test (NEW, no existing test/assertion/tolerance touched)
`test_bs1a4c2_band_chord_cl_checked` (engine/test_engine.py:2142, registered
in `_main()` engine/test_engine.py:1100): L-channel part; spies
channel_regions and asserts EVERY emitted band cutting chord passes the
segment-sampled (<= 0.25 mm) isl_ok3 check; rough() must complete without a
CL refusal and with clcheck_violations == 0; failed_region_emitted present.

### Exit codes (all run by me via slot_m4.sh, ENGINE_WORKERS=4)
- test_bs1a_lshaped_channel BEFORE the change (tree @ 351ce50 + briefs):
  RuntimeError "rough CLCHECK FAILED: 28 sample(s) ... worst move 2068 at
  X-4.208 Y-0.704 Z0.381 sits 18.000 mm below CL -17.238" (exit 1,
  uncaught traceback).
- test_bs1a_lshaped_channel AFTER the change: PASS (25 band region(s),
  1628.9 mm trochoidal cut, 0 full-width windows) - PIPESTATUS EXIT=0.
- test_bs1a4c2_band_chord_cl_checked AFTER the change: PASS (25 band
  region(s), 2 listed failed piece(s)) - EXIT=0.
- full engine/test_engine.py AFTER the change: `37 PASS`, `0 failure(s)` -
  SUITE_EXIT=0.

### fail-on-351ce50 (`git archive 351ce50` -> tmp `bs1a4c2_base351`, my new
### test file copied in, never a checkout)
```
AssertionError: rough refused on CL (an unsegment-checked chord gouged):
rough CLCHECK FAILED: 28 sample(s) below CL + axial_leave 0.381 - 0.005,
worst move 2068 at X-4.208 Y-0.704 Z0.381 sits 18.000 mm below CL -17.238
EXIT=1
```
(the spy's chord assertion also fires on that tree; the CL-refusal
AssertionError is raised first, from the except-runtimeerror guard).
`git diff 351ce50 -- engine/test_engine.py` has exactly ONE "-" line - the
old `_main()` tuple closing line `test_bs1a4c_fix_no_post_entry_helix):` -
no existing test or assertion changed.

STOP rule check: test_bs1a_lshaped_channel passes (not a LOAD failure), so no
STOP; (a) confirms the first-window over-read is BS1a4d's job.
Note: during this session `engine/TASK_BS1a4d.md` appeared modified and
`engine/TASK_BS1a4e.md` untracked in the worktree - NOT my edits; left
untouched. No commits made.

## (14) BS1a4d-f - finish BS1a4d: call-compatible bore credit + real fail-on-base tests

Session start Sat Oct 24 02:09 MST (hard cap ~04:09), worktree
stevecam-bs1a4d branch bs1a4 @ 5f7ba45, no commits. All tests via
slot_m4.sh (ENGINE_WORKERS=4); NO Core Front engine or zmap job. No lock
files touched; no stuck slot.

### (14a) Change - 22 changed non-test lines vs 5896dbf

`git diff --numstat 5896dbf -- engine/band.py engine/rough.py`:
`9 2 engine/band.py` + `5 6 engine/rough.py` = **22** (adds+dels).
Budget was <= 20, STOP ~30: the +2 is because `ContextVar.context(value)`
does NOT exist in VibeCAD python 3.11 (verified: `dir(ContextVar) = get,
name, reset, set`), so the scoped context manager had to be written by hand
(class + 3 methods) instead of a one-line alias. No signature introspection,
no bare module global (the ContextVar lives inside `bore_context`).

engine/band.py:
- `engine/band.py:30` - `from contextvars import ContextVar`.
- `engine/band.py:57-61` - `class bore_context` with class attribute
  `_B = ContextVar("bs1a4d_borefn", default=None)`; `__init__` sets,
  `__exit__` resets the token - SCOPED, nest-safe.
- `engine/band.py:154` - `_simulate(path, stock, z, tool_r, cell, bore_r,
  ends=None, *, bore_xy=None)`: bore_xy is now KEYWORD-ONLY (old positional
  calls up to 7 args stay valid; nothing can slip into it positionally).
- `engine/band.py:352-361` - `channel_regions` signature EXACTLY BS1a4c's
  `(rings, stock, isl_ok3, z, tool_r, leave, cell, stats=None)`; the bore fn
  arrives via `borefn = bore_context._B.get()` at :361. Without a context
  (direct callers, test spies with the old signature) it behaves as BS1a4c
  (start-centred entry credit).

engine/rough.py:
- `engine/rough.py:2051` - `bore_context` added to the existing
  `from engine.band import (...)`.
- `engine/rough.py:2053-2056` - the band planning call wrapped:
  `with bore_context(lambda p, zz: _bore_pred(isl_ok, centre_zone, stock,
  p[0], p[1], tool_r)):` around `channel_regions(rings, stock, isl_ok3, z,
  tool_r, leave, stock.cell, stats)` (the `borefn=` kwarg removed).

engine/test_engine.py (only the two NEW tests of this branch, per TESTS rule):
- `sim_spy` (test_bs1a4d_credit_real_bore, :2321) forwards in the caller's
  form (`**kw`): on 22cdff7 the engine never passes `bore_xy`, so base is
  called through its OLD signature there and the test fails BY ASSERTION,
  not with a TypeError.
- test_bs1a4d_credit0_lightest_option: the scenario assertion now requires a
  credit-0 FAILING re-check (`replan0_*` != `replan0_ok`) to have fired and
  be listed - on 22cdff7 the real-bore credit that proposes the failing
  region does not exist, so it fails BY ASSERTION (see (14d)).
- `git diff 22cdff7 -- engine/test_engine.py` has exactly ONE "-" line - the
  old `_main()` tuple closing line `test_bs1a4c2_band_chord_cl_checked):` -
  no existing test or assertion changed.

### (14b) Report - engine max ae and option chosen

Test block region (start area (6.28,-2.08); failed_region_emitted place is
the seg start (6.276,-2.878)), Z 27.381: option **shrink0.55**, engine max
ae **5.75 mm** (area 287.5 mm2); `credit_fallback = []` on the test block
(the credit was backed by an emitted helix).

L-channel regions (this task's scene, Z 0.381, fixed tree):
- (-18.724, -0.115): option **shrink1**, engine max ae **7.25 mm**
  (area 266.25) - BS1a4c read 15.25, halved by the real-bore credit.
- (-2.09, 5.742): option **shrink1**, engine max ae **5.75 mm**
  (area 383.25) - BS1a4c read 13.5 at shrink0.4; with the real bore the
  unshrunk ladder now passes the FW-rank selection.
Plus the (a0) region (-1.7313, 3.7617): `replan0_shrink0.55`, listed with
engine max ae 3.0 mm (area 331.0).

### (14c) Exit codes - fixed tree (all via slot_m4.sh, ENGINE_WORKERS=4)

- test_bs1a4d_credit0_lightest_option: **EXIT=0** (PASS; replan0_shrink0.55
  listed with option + max_ae)
- test_bs1a4d_credit_real_bore: **EXIT=0** (PASS; 1 helix-entered region,
  credit covers the swept helix + floor-circle bore, offset centre)
- test_bs1a4b_windows_align_zmap: **EXIT=0** (boundaries identical; max
  engine-zmap +14.070 mm, max zmap-engine 1.488 mm - unchanged vs section
  (10), no regression)
- test_bs1a4c2_band_chord_cl_checked: **EXIT=0** (41 band regions, 2 listed
  failed pieces)
- test_bs1a_lshaped_channel: **EXIT=0**

### (14d) fail-on-22cdff7 (`git archive 22cdff7` -> tmp `bs22`, my test file
### copied in, never a checkout)

```
RESULT test_bs1a4d_credit_real_bore FAIL: credited plan sim pre-cleared a disk about the path START ((0.381, (-18.724, 0.6852000000000003), 6.343, None)), not the real helix-centred bore
EXIT test_bs1a4d_credit_real_bore = 1
RESULT test_bs1a4d_credit0_lightest_option FAIL: no credit-0 FAILING re-check fired - scenario vacuous: ['replan0_ok', 'replan0_ok', 'replan0_ok', 'replan0_ok', 'replan0_ok', 'replan0_ok', 'replan0_ok', 'replan0_ok', 'replan0_ok']
EXIT test_bs1a4d_credit0_lightest_option = 1
```

Both FAIL BY ASSERTION (exit 1), no TypeError. Note on (a0): the supervisor
fact is confirmed - on 22cdff7 this scene's forced credit-0 re-checks ALL
pass at credit 0 (9x replan0_ok, no drop): the region that fails its
credit-0 re-check (-1.7313, 3.7617) only exists because the real-bore
credit (this task's (c)) proposes it at plan time; on 22cdff7 heavy
stretches there fail the planning gate and get helix-backed entries, so the
silent-drop branch is never reached in this geometry. Two scene variants
(narrowed 15 mm L-corridor, hoping to make the helix CL-fail where a link
entry carries a heavy credit-0 path) emitted ZERO band regions on both trees
and were abandoned. The test therefore asserts the honest non-vacuity that IS
reachable: a credit-0 failing re-check must fire AND be listed with its
option - vacuous (assertion failure) on 22cdff7, satisfied + listed
(`replan0_shrink0.55`, max_ae 3.0) on the fixed tree.

### (14e) Status (final)
- Fixed tree: new tests + all 3 at-risk tests EXIT=0 (above).
- fail-on-22cdff7: both new tests FAIL BY ASSERTION, EXIT=1 (above).
- Final `git diff --numstat 5896dbf -- engine/band.py engine/rough.py`:
  `9 2` / `5 6` = 22 lines. No commits; locks untouched.
- Process note: one lshape run was accidentally launched with `&`; it was
  waited for in-session to completion before proceeding (identical PASS twice,
  log `bs1a4df_lshape.log`); all later commands ran in the foreground.

## (15) BS1a4d2b - band entry bores AT its trochoid start (centred helix)

Session start Sat Oct 24 04:09 MST (hard cap ~06:09), worktree
`stevecam-bs1a4d2b` branch bs1a4d2b @ 0648f72 (code = BS1a4d-f `2c8e11d`),
no commits. All tests via slot_m4.sh (ENGINE_WORKERS=4); NO Core Front engine
or zmap job. Locks untouched; no stuck slot. 667654e not reused.

### STOP - triggered (TESTS rule): test_bs1a4d_credit_real_bore fails on the
### fixed tree; work halted, the test was NOT touched. Details in (15e).

### (15a) Change - 39 changed non-test lines vs 2c8e11d

`git diff --numstat 2c8e11d -- engine/band.py engine/rough.py`:
`25 14 engine/rough.py` = **39** (adds+dels; band.py unchanged). Adds are
exactly 25 (the target); the total sits under the ~40 stop - the excess over
a 25 adds+dels reading is the `_bore_pred` mirror (mandatory so the BS1a4d(c)
planning credit tracks the emitted centred bore) plus comment lines.

engine/rough.py only:
- `engine/rough.py:668-676` - `_bore_pred` (the band-planning bore predictor,
  supplied via `bore_context` to `channel_regions`) now mirrors the centred
  ladder: `for d in (0.0,)` - centre = start + rh*n, the circle passes through
  the start - and shrinking radii `[fr * tool_r for fr in (0.8, 0.5, 0.3)] +
  [0.5, 0.35, 0.2]` (main-tier then fine-tier); same circle guards
  (isl_ok + centre_zone, circle_ok's phase/rounding).
- `engine/rough.py:1252` - `helix_entry(x, y, z, hc, centred=False)`: keyword
  default off, every other caller/fixture byte-unchanged.
- `engine/rough.py:1393-1408` - with centred=True the ladder tries ONLY bores
  whose circle passes through the trochoid start: centre `start + rh*(cos a,
  sin a)` over the same 16 directions, radii shrinking (main-tier radii
  0.8/0.5/0.3 x tool_r, then fine-tier radii 0.5/0.35/0.2), each candidate
  through `try_cand` exactly as today (circle isl_ok + centre_zone, return
  segment isl_ok at 0.4 mm, bore containment `dist <= r + tool_r - corner_r -
  0.25`, honest segment-wise milling). If no centred bore passes it returns
  False - NO fall-through to the non-centred tiers ("the ladder stays the
  only entry"); the existing BS1a4c emit-time backing then gives the region
  credit 0: `engine/rough.py:2116-2148` (unchanged) re-checks at credit 0 on
  the live stock, takes Fix 1's lightest option via `shrink_ladder`, lists
  `(x, y, z, act)` in `stats["credit_fallback"]` and
  `stats["failed_region_emitted"]` when the re-check fails. No new code was
  needed for that - no silent emit is already structural there.
- `engine/rough.py:1527,1553` - `feed_down(..., centred=False)` forwards to
  `helix_entry`.
- `engine/rough.py:1663,1689,1712` - `enter_at(..., centred=False)` forwards
  at the two ladder steps that descend AT the entry point (step 2 traverse +
  feed_down, step 4 retract + feed_down); step 1's descent at the previous
  point is untouched.
- `engine/rough.py:2107-2108` - ONLY the band channel region entry passes
  True: `centred="credit" in res` (the `credit` key is set by
  `channel_regions` on every band region and on no other region - a2d/hug
  regions at :922/:989 carry no `credit`).

### (15b) Report - engine max ae and option (fixed tree)

| region (seg start) | Z | option, engine max ae @ fixed | 2c8e11d | fresh cells under start disk fixed / base |
|---|---|---|---|---|
| test block (6.276,-2.078) | 27.381 | **shrink0.55, max ae 3.0** (area 301.25) | shrink0.55, 5.75 | **0 / 43** |
| L-channel (-18.724,-0.115) | 0.381 | **shrink1, max ae 7.25** (area 284.0) | shrink1, 7.25 | **0** / (base bite - start disk poked past the bore) |
| L-channel (-2.09,5.742) | 0.381 | **shrink1, max ae 4.0** (area 391.5) | shrink1, 5.75 | **0** / (idem) |

Centred vs fell back to credit 0: test block **1 centred bore, 0 fallbacks**
(`credit_fallback = []`); L channel **12 centred bores, 0 credit-0 fallbacks**
(`credit_fallback = []`), plus 29 credited entries entered by tool-down/side
links whose start disk was ALREADY clear at emit time (0 fresh cells under it,
no bore needed - honest credit, nothing to back). The emitted centred bore is
visible in the moves: the TB helix descends THROUGH (6.276,-2.078) (the start
lies on the bore circle) and its floor circle sweeps the whole start disk.

### (15c) New test - engine/test_engine.py:2441
`test_bs1a4d2b_centred_entry_bore` (registered `_main()` :1103; existing
tests/assertions untouched - `git diff 2c8e11d -- engine/test_engine.py` has
exactly ONE "-" line, the old `_main()` tuple closer). On BOTH the test-block
scene and the L-channel scene, for every credited band entry captured at plan
time (snapshot of live stock): its OWN bore = the contiguous ramp-feed run
(helix segments + HB1v2 floor circle) ending before the return link; assert
**0 cells stand above Z + 0.05 inside disk(start, tool_r)** that the entry did
not sweep (plan-time fresh minus every feed move at <= Z before the landing),
and the bore circle passes through the start (|centre - start| <= r + 0.3).
An entry without its own bore must have a clear start disk or be listed in
credit_fallback (never silent). Named-region non-vacuity guards: TB
(6.28,-2.08)@Z27.381 and L (-18.72,0.69)@Z0.381 must be bore-checked, >= 1 /
>= 2 bore entries per scene.

### (15d) Exit codes (all via slot_m4.sh, ENGINE_WORKERS=4)

Fixed tree:
- new test standalone: **EXIT=0** - "PASS bs1a4d2b: centred entry bores - 1
  bore-entered region(s) checked on the test block (+0 link-backed), 12 on
  the L channel (+29 link-backed); credit_fallback TB=[] LS=[]"
- at-risk batch (10 tests, one process, per-test RESULT lines in
  `out/bs1a4d2b_atrisk.log`): **EXIT=1**
  - test_bs1a4d_credit_real_bore FAIL (see (15e))
  - test_bs1a4d_credit0_lightest_option PASS
  - test_bs1a4b_windows_align_zmap PASS (boundaries identical; max
    engine-zmap +14.070 mm, max zmap-engine 1.488 mm - UNCHANGED vs (14c),
    no regression)
  - test_bs1a4c2_band_chord_cl_checked PASS
  - test_bs1a_lshaped_channel PASS
  - test_hb1v2_flat_floor_circle_after_helix PASS
  - test_bs1a4c_fix_no_post_entry_helix PASS
  - test_rough_synth_pocket_repro PASS
  - test_dt1_synthetic_rough_twice_identical PASS
  - test_bs1a4d2b_centred_entry_bore PASS
- test_bs1a4d_credit_real_bore standalone fixed tree: **FIXED_EXIT=1**
- test_bs1a4d_credit_real_bore standalone on base (2c8e11d archive):
  **BASE_EXIT=0** ("PASS bs1a4d(c): 1 helix-entered region(s) ...") - so the
  failure IS caused by this task's change, not pre-existing.

fail-on-2c8e11d (`git archive 2c8e11d` -> tmp `bs1a4d2b_base`, my test file
copied in, never a checkout):
```
AssertionError: bs1a4d2b_tb: 43 cell(s) stand above Z+0.05 under the start
disk (6.276,-2.078)@Z27.381 after its entry bore (centre (10.79,-2.08)
r 3.17): the start disk pokes past the swept bore
EXIT=1
```
FAIL BY ASSERTION, exit 1 - exactly the supervisor's 43 cells at the
test-block region.

### (15e) STOP report - test_bs1a4d_credit_real_bore

`FIXED_EXIT=1`, assertion `no helix-entered credited region was checked`
(its `assert checked >= 1`). Root cause (from `out/bs1a4d2b_diag_tb.py`,
move dump around the TB entry): with centred=True the bore circle passes
THROUGH the start q, so `try_cand`'s helix-start pick `s = min(circ[:-1],
key=dist to (x,y))` selects s == q itself, and `_helix_turns` returns an
INTEGER turn count, so the helix end e sits directly below s: **the final
helix segment ends exactly at q@Z**, before the HB1v2 floor circle (the
return link degenerates to zero length). credit_real_bore's `entry_pts()`
takes the FIRST G1 move ending at q@Z - now that mid-entry helix point - and
requires >= 9 preceding ramp-feed moves at z == Z behind it (the floor
circle), which a descending helix point does not have -> returns None for
every credited region -> `checked == 0`. The credit invariant itself (the
planning bore covering the emitted entry sweep) is NOT shown violated - the
test's move-pattern locator can no longer see the entry. Per the TESTS rule
the test was not touched and engine work stopped.

Supervisor options (NOT implemented): (i) relax `entry_pts` to accept a
helix terminating at the start (test-side change); (ii) engine-side: for
centred bores pick the helix start at the ANTIPODE of the start (s = circle
point farthest from the entry) so q@Z occurs only at the return-link end
after the floor circle - keeps the bore centred (start disk still inside
disk(rh + tool_r)), return link 2*rh long entirely inside the bore at Z,
~+2 lines; (iii) accept the new entry shape and re-anchor credit_real_bore.

### (15f) Status
- Fixed tree: new test EXIT=0; 9/10 at-risk tests PASS; credit_real_bore
  EXIT=1 -> STOP (above). fail-on-2c8e11d: EXIT=1 by assertion, 43 cells.
- `git diff --numstat 2c8e11d -- engine/band.py engine/rough.py` = `25 14`
  = 39 lines; engine/band.py unchanged; no zmap/verify import in engine.
- No commits; locks untouched; no Core Front job.
- Process notes: all commands ran in the FOREGROUND. At session start this
  results file was overwritten with a fresh status log before the original
  content was consulted from context; sections (1)-(14) were then restored
  VERBATIM from `git show 0648f72:engine/BS1a4_RESULTS.md` (539 lines, byte
  count verified) before this section (15) was appended - the final file =
  committed content + section (15). Diagnostics live in `out/`
  (`bs1a4d2b_diag.py`, `bs1a4d2b_diag_tb.py`, logs); base tree copy under
  the approved temp dir `opencode/bs1a4d2b_base`.


---

## (16) BS1a4d3 — non-stock-clear cutting-feed links checked as cuts

Session start: Sat Oct 24 06:51 MST (hard cap ~08:51). Worktree
`/Users/James/ai-sandbox/stevecam-bs1a4d2b`, branch bs1a4d2b @ e8dd1d4
(code = d4ced08). No commits. All tests via slot_m4.sh (ENGINE_WORKERS=4);
NO Core Front engine or zmap job. No lock touched.

### Status (live)
- Implementing: flink / clip-bridge / flank feed-in checked as cuts via
  band._simulate on live stock at Z, credit 0, AE_SPIKE 2.44.
### Change (implemented, 25 lines vs d4ced08: rough.py +23/-2, band.py 0)
- engine/rough.py:1442 `lnk_cut_ok(st, path, z, key)`: not stock-clear at Z
  -> band._simulate on live stock at Z, credit 0; max window > SPIKE_MM (2.44)
  -> caller lifts + re-enters via enter_at's ladder. Counts stats[key+_chk/_cvt].
- engine/rough.py:1509 find_shift flank feed-in: `if not lnk_cut_ok(stock,
  path, z, "fdin"): continue` (candidate rejected -> helix ladder).
- engine/rough.py:2231 clip bridge: chord accepted only if `lnk_cut_ok(stock,
  prev+chord+pts[i], z, "brdg")` (else existing clip-break -> enter_at).
- engine/rough.py:2352 flink gate: `and (top <= z + 0.05 or lnk_cut_ok(
  stock, corridor, z, "flnk"))` (else existing lift path at :2401).
### Scene findings (out/bs1a4d3_diag.py, band._simulate credit 0 on pre-mill
### live-stock snapshots; link kinds identified by their link_clear gate
### fingerprints z / z+lift / z+0.2 and bridge chaining)
- L-channel @ d4ced08: the only >2.44 chained path (14.5, z=0.381) is the
  helix RETURN FEED (rough.py:1386 try_cand) - covered by the brief, excluded.
  flink=0, bridge=0, feed-ins all read 0.00 -> L-channel cannot fail-by-assert.
- test-block @ d4ced08: flink=0, bridge=0, feed-in max 0.00 (3 bridge-chained
  runs read 0.00) -> cannot fail either.
- NEW synthetic pocket (40x30 open pocket, floor -1, stock top 2.0, stepdown
  1.5 -> level links cross the previous level's shelf): @ d4ced08 a FLANK
  FEED-IN link (z=0.381, 3.5 mm) measures max window 4.00 > 2.44.
  Fixed tree: feedin max 1.00; fdin_chk=10, fdin_cvt=6; brdg_chk=2,
  brdg_cvt=1 (a clip bridge converted to lift+re-entry); flnk site not
  exercised by these scenes (no corridor clear at z+lift but not at Z).
  Moves: base 2798 -> fixed 2894 (+3.4%); cut_len 792 -> 812 mm.
