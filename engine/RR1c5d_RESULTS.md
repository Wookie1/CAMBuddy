# RR1c-5d RESULTS (session 2 - continuation, FINAL)

Started: Sat Oct 24 05:56 MST (`date` at start). HARD CAP 2 h -> stopped 07:10 MST.
Base: HEAD efb9833 (brief) on 035e590 (RR1c-5c), branch rr1b. NO commit made.
Continued the prior attempt's WIP (engine 36/4, tests 90/1); did not start over.
Lane: scratchpad/slot_m4.sh + VibeCAD python (/Applications/VibeCAD.app/Contents/Resources/bin/python,
PYTHONPATH=.../Resources/lib - the only interpreter with numpy+scipy+area). All FOREGROUND.
NO Core Front job. Locks untouched; lane never stuck (one run queued ~14 min behind another
session's live job PID 21607 - waited, did not touch the lock).

## (1) Change - engine/rest_rough.py (file:line at final worktree state)

**Front construction (rest_rough.py:728-766)** - replaces fixed `offset(C, ae/2 + k*ae)`:
- `f1 = []` (:732), `hch = ae/2.0` default (:734) - today's behaviour when the chord path
  does not apply (fronts=False fallback unchanged).
- When `fronts` (:736-754): `e = reg & ~seed & dilation(seed)` = the zone's cleared edge
  (:742). `a1` = max LIVE material height above Z along that edge, read from the PLANNING
  stock Sg (:743-746) - vectorized this session (was a per-pixel `live.disk_depth` loop that
  cost +34% gen time): `D = EDT(~e)*CELL`, then `a1 = max(Sg - (R - sqrt(R^2 - D^2))) - t`
  over cells within R of the edge - the exact disk_depth formula on the planning grid, no new
  0.1 model, no ZE2B call. `hch = sqrt(max(a1*(dia-a1),0))` = c(a1)/2 (:747-748).
  `Sv = F - EDT(seed)*CELL` = SIGNED distance from the cleared edge (:749).
  `cf` = clip region: reg grown into cleared ground (dilation sized to reach |c0|) intersected
  with the leave-legal CL grid `Zraw <= t - rest_leave + 0.005` (:750-752) - the same formula
  reg uses, "CL check and leave exactly as now". Fronts marched at `c = c0 + k*ae`,
  `c0 = ae - hch` SIGNED (negative: CL INSIDE cleared ground) (:753, 755-766).
  Front-1 paths flagged in `f1` (:765); zigzag rebuild `f1 = [False]*len(paths)` (:773).

**Pre-emit engagement check (rest_rough.py:930-943)**: front 1 uses SIGNED
`dv = Sv[ii,jj]` and flags when `dv + hch > ae + CELL`, i.e. `dv > (ae - hch) + CELL`
(:932-935); fronts 2+ keep today's unsigned `EDT(~clm)` vs `ae + CELL`. A flagged front 1
is STILL emitted and listed in `stats["rr_ring_failed"]` with estimated width
(`w_plan = dv + rc`) - nothing silent. `isf1 = f1.pop(k)` at :828.

**Supporting guard `clmn` (rest_rough.py:818, 828, 858-861, 945)** - NOT in the fixed
design, carried from the prior attempt and re-verified needed this session: shifting front 1
moves pass-to-pass links onto the inter-groove cusp ridge; the engine's link check at 0.5 mm
pitch under-reads the ~0.1 mm cusp the judge measures, so a grazing link passed the engine and
was caught by test_rr1c5b_open_edge_proud_block / test_rr1c5b_mixed_band_core_front ("feed
link at depth cuts standing stock"). The guard only TIGHTENS: a depth link may traverse only
columns at/near already-emitted geometry (seed + pass pixels dilated 2 cells), else the frozen
ladder `enter()` is taken. No gate, ZB floor 0.5, validate_exact tolerance or leave relaxed.

## (2) Line count vs 035e590 (`git diff --numstat 035e590`)
- engine/rest_rough.py: **36 adds / 4 dels = 40** (at the ~40 STOP limit; fixed-design part
  ~25 lines: front construction + signed check + f1/isf1 plumbing; clmn guard +5).
  Vectorizing a1 kept the count identical (loop was 3 lines, vector form is 4... net 0 after
  re-flow: still 36/4 - verified below).
- engine/test_engine.py: 90 adds / 1 del (tests do not count against the budget).

## (3) Report - front-1 a1 / c0 / estimated width in the new test scene
Scene (test_rr1c5d_front1_chord_offset_slabs): two closed pockets, floor 24.6, stock tops
27.55 (A) / 28.9 (B), level Z 26.8, ae 1.905, D 9.525:
- pocket A @ Z 26.8: a1 = 0.75, c0 = 1.905 - sqrt(0.75 x 8.775) = **-0.660**, est width = ae
- pocket B @ Z 26.8: a1 = 2.10 (planning), c0 = **-2.044**, est width = ae
- pocket B @ Z 28.8: a1 = 0.10, c0 = **+0.93** (~ae/2 - degenerate, matches today)
These reproduce the CF facts (Z 44.965 a 0.755 -> c0 -0.66; Z 42.965 a ~2.1 -> c0 -2.04).
NOTE: in this closed-pocket scene `fronts = bool((seed & ~reg).any())` is FALSE (bore seed
inside reg), so the fixed-design branch never runs there - see (5).

Generation time of the new test scene (rest_rough only, 3 runs each, slot lane):
- base 035e590: 0.221 s  - fixed (vectorized a1): 0.224 / 0.225 / 0.227 s -> **+1..3%**
  (within the 5% budget; the prior per-pixel loop was +34%, now removed).

## (4) Tests - PASTED exit codes (all FOREGROUND via scratchpad/slot_m4.sh, NO Core Front)

Batch on the FIXED worktree (after vectorizing a1), exit code pasted:
    PASS test_rr1c5b_varying_width_band_fronts (0.9s)
    PASS test_rr1c5b_open_edge_proud_block (1.1s)
    PASS test_rr1c5b_fully_walled_band_bore_seed (0.3s)
    PASS test_rr1c5b_mixed_band_core_front (1.1s)
    PASS test_rr1c5c_closed_pocket_bore_entry_no_deep_axial (0.3s)
    PASS test_rr1c4b_closed_pocket_bore_levels (0.5s)
    PASS test_rr1b_rest_rough_synth_pocket (0.5s)
    PASS test_rr1c2_cf_rapid_shapes_clear_stock (1.2s)
    FAIL test_rr1c5d_front1_chord_offset_slabs: ZE2B: 4.3 mm of wide slots over 2.286 at cutting feed
    TOTAL fails: 1
    FIXED_EXIT=1

Fail-on-035e590 (new test run against `git archive 035e590` engine, never checkout):
    FAIL-BY-ASSERTION on base: ZE2B: 4.3 mm of wide slots over 2.286 at cutting feed
    BASE_EXIT=1

**8/8 at-risk tests PASS on the fixed worktree. The NEW test fails BY ASSERTION on base
(requirement met) but does NOT pass on fixed - see (5).**

## (5) Open issue for the supervisor - the new test scene cannot be made sensitive within
the fixed design (measured this session, three scene families):
- Closed pocket (shipped test scene): reproduces CF-style 4.3 mm wide slots at base, but
  fronts=False (bore seed inside reg) -> the fixed-design branch never runs -> same 4.3 mm
  on base and fixed. Fail-on-base proven; pass-on-fixed impossible without extending the
  design to the inside-out fallback (NOT done - design is fixed).
- Open bay/shelf scenes (Q: bay + two-shelf block; R: two bore-entered pockets beside a
  cleared channel island): `fronts` IS true, the chord fix DOES move front 1 inside cleared
  ground (rr_ring_failed=0, gate clean) - but the scenes are BLIND at base: every level of a
  standing slab is entered by the frozen ladder (step-2 ramp / step-4 SE2) feeding through
  the standing wall AT the cutting Z at ramp_feed, pre-cutting it; ZE2B judges cutting-feed
  windows only. Measured: over ALL cutting-feed windows of Q and R, max a = 0.135 mm
  (inter-pass cusps), ZERO windows with a > 0.3 -> cannot fail by assertion.
- The CF centre band is sensitive because its walls are born from adjacent-zone machining and
  front 1 links directly from cleared ground with no wall-crossing entry. A synthetic
  reproduction needs the same topology; every variant tried (this session and the prior one)
  hits either fronts=False or ladder pre-cut blindness.
Candidate resolutions (both EXCEED the fixed design - supervisor decision, not implemented):
  a) seed fronts for bore-seeded zones (fronts = bool(seed.any())) with a1 read along the
     level-cleared edge; b) judge entry-feed windows in the test gate.

## (6) Rules compliance
- Locks never created/removed/edited (waited out another session's lane job instead).
- No existing test/assertion/tolerance edited; one NEW test added (registered in _main).
- No stash/reset/clean/restore/checkout/rebase/cherry-pick; base via `git archive` only.
- No gate/ZB floor/validate_exact tolerance/leave relaxed; verify/ and opencode.json
  untouched by me (opencode.json diff is pre-existing harness config: baseURL +
  reasoningEffort, not mine).
- Engine imports unchanged; engine never imports zmap/verify (test imports them, allowed).
- All commands FOREGROUND; nothing committed.

## (7) Test log (chronological, exit codes)
1. 06:0x env/lane check varying_width: PASS exit 0 (VibeCAD python + slot OK)
2. 06:25-06:41 lane queued behind another session's job (PID 21607, live) - waited, exit 0
   after run; scene Q base: blind (over=0.0) exit 0
3. 06:53 Q full window dump base: 288 cutting-feed windows, max a 0.135 -> blind exit 0
4. 06:57 scene R base+fixed: both ZERO a>0.3 windows at cutting feed -> blind exit 0
5. 07:00 batch fixed (prior loop engine): 8 PASS / new FAIL(4.3) FIXED_EXIT=1;
   base fail-check: FAIL-BY-ASSERTION BASE_EXIT=1
6. vectorized a1 (timing fix, +0 lines): 07:02 batch fixed: 8 PASS / new FAIL(4.3)
   FIXED_EXIT=1 (no regression from vectorization)
7. 07:03 timing scene V: base 0.221s vs fixed 0.224-0.227s (+1..3% <= 5%) exit 0
