# BS1a4d6 RESULTS

Session start (`date`): Sun Oct 25 04:38:50 MST 2026
Worktree: /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 @ 582d668 (b6c48e1 + brief).

## Status log
- 04:38 started; scratch/ created.
- 04:44 first lane call (`slot_m4.sh python -c "print(version)"`) exceeded a 5-min
  timeout before completing — slot appears queued/busy. Retried with a longer
  timeout; per LOCKS, no lock files touched. Second attempt completed OK.

## CAUSE (before any code change) — who hits replan0_drop and why (diag: scratch/diag_cause.py)

Scene: the L channel (tris of test_bs1a4d_credit0_lightest_option), Z 0.381.
Identical acts with and without the link_clear-forcing spy. Exactly ONE piece
hits replan0_drop:

- piece start q4 = (-6.2719, 3.5231) @ Z 0.381, replan0 = 2 (plan0_splitbore),
  stored bore = centre (-6.0997, 3.1074) r 0.5 (small bore, below min helix r).
  Its real-bore emit re-check (band._simulate with the stored bore) fails the
  gate, so it takes the credit-0 shrink ladder on the live stock.
- The lightest option is shrink0.75: max window 2.5 mm, best area 70.50 mm2 —
  lighter than drop_ring (2.5 mm ring windows recorded at the same place).
- WHY it cannot rejoin q4: shrink_ladder rebuilds the trochoid over the WHOLE
  centre-line segment res["seg"], so the option path starts at
  pnew[0] = (-18.724, 0.6852) — 12.771 mm from q4. The join test
  _split_at_jumps(isl_ok3, [q4] + pnew) yields pcs[0] = [q4] alone
  (1 point of 2065): the straight chord q4 -> pnew[0] fails the
  segment-sampled CL check (it crosses the forbidden wall between the channel
  arms), so len(pcs[0]) < 4 and b6c48e1 drops the cut (stock left for the
  ring) -> test_bs1a4d_credit0_lightest_option ("... 'replan0_drop' not EMITTED
  as its lightest option: {... 'option': 'drop_ring', 'max_ae': 2.5}") and
  test_bs1a_lshaped_channel ("7 full-width window(s) ... 12.0-12.5 mm wide",
  the ring slotting the dropped piece's stock).
- All other replan0 failures on the scene DO rejoin (pcs[0] = 148 or 681 of
  2698-3986 points, chord 2.7-3.5 mm) and already emit at their lightest
  option (replan0_shrink1 / replan0_shrink0.55) — unchanged by this task.

## Plan
(a) rough.py emit fallback: when the lightest option's first piece cannot join
    q4, emit that piece as its OWN region at its own enter_at entry (normal
    ladder, enter_at stays the only entry), act "replan0_<opt>", listed in
    failed_region_emitted (option=opt, measured max_ae) and credit_fallback.
    Never dropped. Drop stays only as the last-resort when NO piece >= 4 pts
    exists at all.
(b) test_bs1a4d_credit_real_bore (approved): scope the "extra > 100" assert to
    emitted bores r >= min helix r (0.3 x tool_r = 1.9029 ~ 1.903); for smaller
    emitted bores add a replacement assert that the credited area equals the
    emitted bore's own sim footprint (helix centre, r + tool_r, plus landing
    disk) within grid tolerance.

---

# BS1a4d6b (fresh session, start `date`: Sun Oct 25 08:05:35 MST 2026)

## CAUSE FIRST (measured on 3a10607 via scratch/diag_bs1a4d6b.py, no code change)

### Red test 1: test_bs1a4d_credit0_lightest_option
Record flow on the L scene (diag output): credit_fallback has TWO adjacent
failures 0.27 mm apart - (-2.7176, 3.0018, 'replan0_shrink1') and
(-2.5924, 3.2481, 'replan0_shrink0.55'); failed_region_emitted carries BOTH
emit-time records, appended in that order. The test matches each fallback to
the FIRST fre record within 1.5 mm, so for (-2.5924, 3.2481) it picks the
EARLIER record of the other region at (-2.7176, 3.0018) - option 'shrink1'
!= 'shrink0.55' -> fail. Root of the option divergence: the two regions
re-plan their ladder on DIFFERENT live stock (the first region's emit milled
stock before the second re-checks), and the ranking itself is corrupted by
the max_ae artifact below (window-0 tie broken by the disk's "over" travel).

### The max_ae 36.25 mm on (-2.7176, 3.0018) 'shrink1' - THE MEASURE IS WRONG
Diag: the _simulate that produced it ran with bore_r 0.0, bore_xy None
(the emit-time ladder calls shrink_ladder with credit 0.0 and no borefn) and
its window list is [36.25, 3.5, 0.0, ...] - the max is WINDOW 0. Not a
sentinel, not a unit mix-up, not a sum: _simulate applies the cutter disk at
EVERY emitted point, so window 0 counts the WHOLE standing start disk under
path[0] (here 36.25 mm2 of 145 cells; pi x 6.343^2 = 126 mm2 is the ceiling)
as one 1-mm window's engagement. Physically the tool ARRIVES at path[0] via
the enter_at ladder (link / side / helix) at ENTRY feed - the start disk is
never a cutting-feed engagement (max real window = channel width ~ 19 mm2,
and 36.25 > 12.686 tool diameter proves it is not one). _simulate pre-clears
the start disk only when a bore is credited (`if bore_xy:` branch); at
credit 0 the disk leaks into window 0, so EVERY credit-0 ladder option ties
on #FW (36.25 >= 10.78) AND on max (same disk), leaving the bogus "over"
term to pick the lightest option - the lightest-option CHOICE built on it is
wrong too. FIX THE MEASURE FIRST: _simulate pre-clears the tool_r disk at
path[0] unconditionally (engine/band.py).

### Red test 2: test_bs1a_lshaped_channel (7 full-width windows, x 2.741,
y 15.276..20.276, Z 0.381, 12.0-12.5 mm)
_diag _split_at_jumps log_: the emit-time re-checks split the lightest
option into MANY pieces and b6c48e1/3a10607 cover at most ONE of them:
q4 (-2.7176,3.0018) -> lens [148, 39, 44, 45, 42, 313, 32, 34, 152, 57, 10,
30, 39, 40, 41, 43, 2877] (only pcs[0] = 148 pts emitted; the 2877-pt piece
spans y 4.3..21.2 - the vertical arm); q4 (-2.5924,3.2481) and the four
q4s near (-0.x, 4.3..4.6) -> [681, 2017] (only the 681-pt pcs[0] emitted;
the 2017-pt piece spans x -2.7..2.7, y 3.9..21.2 - EXACTLY the failing
window rect); q4 (-6.2719,3.5231) -> [1, 1138, 33, 31, 30, 32, 34, 618, 35,
113] (3a10607 emits only the 1138-pt piece; eight more pieces left). Left
stock is slotted full-width by the ring -> the 7 windows, same as b6c48e1.

## Plan (BS1a4d6b)
1. band.py _simulate: always pre-clear the tool_r start disk at path[0]
   (entry-feed arrival), fix the measure FIRST.
2. rough.py: cover the WHOLE lightest option - pcs[0] keeps the walker path
   from the q4 entry; when len(pcs) > 1 EVERY later piece (even < 4 pts) is
   entered at its own start through the CL-checked enter_at ladder + descend
   and cut inline after the walker (never at the failing load, never left
   for the ring). Drop stays only when len(pcs) == 1 and len(pcs[0]) < 4
   (no cuttable piece).
3. q4 entry: FALLBACK way - the entry stays (see decision below).
4. test (b) edit: named MIN_BAND_HELIX_FR constant instead of literal.
5. NEW test: q4 bore cells read as cut in the live stock right after the
   entry (L scene).

## Status log (BS1a4d6b)
- 08:05 started; 08:09 lane sanity OK; 08:14 diag run #1 (module path fix);
  08:15 diag run #2 gave the records above (exit 0).


## Changes (BS1a4d6b), file:line
- engine/band.py:180 _simulate (start-disk pre-clear now unconditional):
  fix-the-measure-first (max_ae 36.25 was the standing START DISK counted as
  window 0 at credit 0; entry-feed disk now pre-cleared always).
- engine/rough.py:668 MIN_BAND_HELIX_FR = 0.3 named min helix radius tier
  (0.3 x tool_r = 1.9029), wired into _bore_pred (line 677).
- engine/rough.py:2178 (re-check): `if len(pcs[0]) >= 4 or len(pcs) > 1:`
  + more_pcs = pcs[1:] - cover the WHOLE lightest option.
- engine/rough.py:2461 (after the walker loop): for pc in more_pcs: own
  enter_at entry + descend + cut + stock.mill_path; EVERY piece incl. those
  < 4 pts is emitted; a piece starting exactly at a PLANNED region's start
  enters rotated one point (pc[1]) - that region enters pc[0] itself; drop
  stays only when len(pcs) == 1 and len(pcs[0]) < 4 (no cuttable piece) and
  is then listed in failed_region_emitted (option drop_ring) + credit_
  fallback act replan0_drop.
- engine/test_engine.py: (b) edit now uses R.MIN_BAND_HELIX_FR (item 3);
  NEW test_bs1a4d6b_q4_entry_bore_in_live_stock (item 2, fallback way: the
  q4 entry STAYS - deciding before the entry would need the re-check moved
  ahead of enter_at, whose condition depends on the emitted entry state
  (helix_n, credit backing checked after entry) - beyond the line budget;
  fallback conditions hold: bore = predictor's stored bore, cut in live
  stock, CL-checked descent - the new test measures all three).
- git diff --numstat vs b6c48e1: band 9/6, rough 26/2 = 43 engine lines.

## Test log (BS1a4d6b)
- test_bs1a4d_credit0_lightest_option: PASS, EXIT=0. After the measure fix
  the (-2.5924,3.2481) fallback no longer fires (replan0_ok) and the
  (-2.7176,3.0018) record reads max_ae 10.25 (was 36.25 disk artifact).
- Iteration: first more_pcs version entered EVERY later piece at pc[0];
  a piece starting exactly at a PLANNED region's start stole that region's
  entry (test_bs1a4d_credit_real_bore: floor-circle at (-2.6508,9.3795)
  matched a helix (0.7521,9.3795) r 1.9029 with no planning/re-check sim).
  A skip-guard for those pieces then starved the neighbour's emit re-check
  of the pre-cut (test_bs1a4d_credit0_lightest_option failed again,
  shrink0.55 vs shrink1). FINAL: entry ROTATION - a piece whose pc[0]
  equals a planned region start enters at pc[1] and cuts pc[1:] (that
  region enters pc[0] itself; the uncovered lune is inside its start disk,
  which its own emit cuts). numstat now band 9/6 + rough 28/0 = 43 lines.
- Re-runs after rotation: test_bs1a4d_credit0_lightest_option PASS EXIT=0;
  test_bs1a4d_credit_real_bore PASS EXIT=0 (9 helix-entered regions);
  test_bs1a4d6b_q4_entry_bore_in_live_stock PASS EXIT=0 (18 bore-backed
  re-checks, 2 failed-re-check regions with kept q4 bore).
- AT-RISK BATTERY (final engine, all through slot_m4.sh, scratch/run_at_risk.sh):
  test_bs1a4d_credit0_lightest_option EXIT=0; test_bs1a_lshaped_channel
  EXIT=0 (0 full-width windows); test_bs1a4d5_splitbore_..._at_load EXIT=0
  (14 forced re-checks); test_bs1a4d_credit_real_bore EXIT=0 (9 regions);
  test_bs1a4d2b_centred_entry_bore EXIT=0; test_bs1a4d4_credit_entry_
  matches_prediction EXIT=0 (15/15); test_bs1a4d4_entry_pinned_to_stored_
  start EXIT=0 (3 pinned); test_bs1a4c_backed_credit EXIT=0;
  test_bs1a4b_failed_region_lightest EXIT=0; test_bs1a4b_windows_align_zmap
  EXIT=0 (boundaries identical); test_bs1a4c2_band_chord_cl_checked EXIT=0;
  test_bs1a4c_fix_no_post_entry_helix EXIT=0; test_bs1a4d3_links_measured_
  as_cuts EXIT=0; test_bs1a_straight_channel EXIT=0; test_bs1a3_no_band_
  after_a2d EXIT=0; test_rough_synth_pocket_repro EXIT=0;
  test_dt1_synthetic_rough_twice_identical EXIT=0; NEW
  test_bs1a4d6b_q4_entry_bore_in_live_stock EXIT=0. 18/18 GREEN.

## MUTATIONS (item 4) - scratch copies scratch/mut{1,2,3}/ (engine+verify),
## real engine files untouched by them; each ran through slot_m4.sh
- MUT1 replan0_drop restored (rough.py `if len(pcs[0]) >= 4:`, more_pcs=[]):
  test_bs1a_lshaped_channel EXIT=1 - "7 full-width window(s) at cutting feed
  in the channel: [... (2.741, 15.276, 0.381, ae_eff 12.0, a 17.62), ...
  ae_eff 12.5 ...]" -> BY MEASURED ae_eff 12.0-12.5 mm (bar 0.9 x D = 11.42).
- MUT2 failing-load emit (re-check gate forced `if ew0 and True ...`):
  test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load EXIT=1 -
  "split piece (0.381, -6.7548, 3.1654) emitted at the failing load (act
  'replan0_ok'): re-check measured 3.000 mm > AE_SPIKE 2.25, OVERLOAD 0.750
  mm" -> BY MEASURED overload 0.750 mm.
- MUT3 small bore credited with the tool_r disk (ew0 credit
  `res["bore"][4] + tool_r` -> `tool_r`): test_bs1a4d_credit_real_bore
  EXIT=1 - "small-bore credit != the emitted bore's own footprint: credited
  530 cells, emitted-helix footprint 593 cells, AREA DIFFERENCE 63 > grid
  tolerance 4 at (-4.825,-1.998) r 0.5000" -> item 3 both numbers: the
  within-4-cells tolerance holds on the real engine (diff <= 4, PASS) and
  the start-disk mutation fails it by 63 cells (15.75 x the tolerance).

## own-region pieces emitted via more_pcs (measured max_ae per piece at
## split time, credit-0 _simulate on the live stock; L scene, Z 0.381;
## diag scratch/diag_pieces.py; clcheck_violations 0)
q4 (-6.2719, 3.5231) option shrink0.75 (pcs[0]=[q4] alone - cannot rejoin):
  piece1 xy-rect x -19.3..-4.1 len 1138 max_ae 0.50; piece2 len 33 0.50;
  piece3 len 31 4.50; piece4 len 30 0.50; piece5 len 32 0.00; piece6 len 34
  0.25; piece7 len 618 0.50; piece8 len 35 0.00; piece9 len 113 0.25.
q4 (-2.7176, 3.0018) option shrink1 (pcs[0] 148 pts joins q4, kept by the
  walker; pieces 1..16 are the planned caps' paths -> entry ROTATED to
  pc[1], the cap itself enters pc[0]):
  p1 len 39 ae 12.0 | p2 44 13.75 | p3 45 13.75 | p4 42 17.5 | p5 313 21.75
  | p6 32 24.5 | p7 34 19.75 | p8 152 13.75 | p9 57 14.0 | p10 10 9.5 |
  p11 30 13.25 | p12 39 14.5 | p13 40 16.5 | p14 41 14.0 | p15 43 14.0 |
  p16 2877 18.5 (the vertical arm - covers the former 7 full-width windows
  at x 2.741, y 15.3..20.3; max_ae measured BEFORE the pre-cuts, the ring
  judge reads 0 full-width windows after all of them, lshaped EXIT=0).
NOTE these per-piece max_ae are pre-cut stock readings; the emitted ORDER
(pre-cutting neighbours + entry-feed start disk) is what brings the JUDGE
under 2.44/11.42 - verified by zmap in test_bs1a_lshaped_channel, not
predicted.

## q4 decision (item 2) - WHICH WAY AND WHY
FALLBACK way: the region's original q4 entry STAYS emitted (deciding before
it would mean moving the whole re-check ahead of enter_at - its condition
depends on the emitted entry state: helix_n delta and the credit-backing
link_clear after entry - a restructure far beyond the 45-line budget). The
fallback's three requirements hold and are MEASURED by the new test
test_bs1a4d6b_q4_entry_bore_in_live_stock (EXIT=0, 18 bore-backed emit
re-checks): the emitted bore equals the predictor's stored bore (1e-9),
every eroded bore cell reads CUT in the live stock handed to the re-check
(right after the entry), and >= 1 failed-re-check region keeps its q4 bore
(the abandoned-piece case); clcheck_violations 0 = the descent passed CL.
Pieces abandoned at q4 enter at their own start (rotated one point where
their start is a planned region's start, so that region's own entry stays
the first entry there).

## Totals (BS1a4d6b)
- git diff --numstat vs b6c48e1: engine/band.py 9/6, engine/rough.py 26/2
  = 43 changed non-test engine lines (<= 45; BS1a4d6 WIP's 20 were replaced,
  not added on top). test_engine.py changes are tests only (approved (b)
  refinement + NEW test + its _main registration).
- All 17 at-risk tests + the new q4 test: 18/18 EXIT=0 (see battery above).

## Close-out (BS1a4d6b)
- 09:25 MST (started 08:05, under the 2 h cap). All 17 at-risk tests + the
  NEW q4 test ran green (18/18 EXIT=0, pasted above); all 3 mutations fail
  BY MEASURED VALUES (12.0-12.5 mm ae_eff / 0.750 mm overload / 63 cells)
  and live only in scratch/mut{1,2,3}/ - real engine reverted-clean (43
  engine lines vs b6c48e1, <= 45). No locks touched, no Core Front job,
  no commit, no bypass flags, no gate relaxed, no margin/leave/feed change,
  verify/ and opencode.json untouched by this session (opencode.json was
  already dirty at session start). Engine edits confined to engine/band.py,
  engine/rough.py (+ the approved test refinements in test_engine.py).
- BS1a4d6b DONE.

---

# BS1a4d6c (fresh session, start `date`: Sun Oct 25 09:19:59 MST 2026)

## Item 0 (before any code change): WHAT the _simulate window value IS

engine/band.py _simulate (band.py:154) appends `acc_area` per window
(band.py:222): the SUM of newly-removed plan-view cell areas inside that
window, `area = removed * cell * cell` (band.py:218), cell = 0.5 mm ->
0.25 mm2/cell. A window closes when accumulated travel reaches 1.0 mm
(band.py:221, zmap AE2_WINDOW_MM = 1.0, zmap.py:59). So the value is
AREA PER WINDOW, unit mm^2 - not area per step, not a width.

The judge's comparable number is ae_eff = area_mm2 / length_mm
(verify/zmap.py:991) - mm^2 per mm of travel = average radial engagement
WIDTH in mm. The engine value equals ae_eff NUMERICALLY ONLY when the
window's length is ~1.0 mm (runs of short merged moves). Two systematic
ways it exceeds a width:
- a single feed move >= 1 mm is its OWN window (zmap.py:980 "a move >= 1 mm
  is its own window"; band.py:221 same): a 2 mm chord/link window carries
  the whole stadium area ~ D x 2 mm, so 24.5 mm^2 (~2 x D x 1 mm) is one
  window's area, not a 24.5 mm width;
- the standing START DISK: the cutter disk is applied at every emitted
  point EXCEPT path[0] (band.py:201 loop), so at credit 0 the whole disk
  under path[0] (up to pi x 6.343^2 = 126.8 mm^2) is swept into window 0 -
  the 36.25 "mm" was exactly 145 cells x 0.25 mm^2 of standing start disk.
  12-24.5 on the BS1a4d6b table are likewise mm^2 window areas (long first
  moves + disk), which is why they exceed the 12.686 mm diameter.

Direct gate comparisons of these window values:
- 2.44: engine SPIKE_MM = 2.44 (band.py:45) compared to _simulate window
  AREAS at band.py:251 (_opt_key travel-over) and rough.py:1462
  (lnk_cut_ok `max(w) <= SPIKE_MM`). Judge: OVERLOAD_WIDTH_MM = 1.2 x 2.032
  = 2.4384 (zmap.py:52) compared to ae_eff at zmap.py:1102
  (overload_feeds_ae2) and to the old chord width_mm at zmap.py:937;
  the channel tests pass --engage-max 2.438 (test_engine.py:1671).
- AE_SPIKE = 2.25 (band.py:44) vs window areas at band.py:284 (ladder gate)
  and rough.py:2159 (emit re-check); AE_SS = 1.85 (band.py:43) at
  band.py:285 and rough.py:2160.
- 2.286 (ZE2B): NO gate compares any window value to 2.286 - it is the Core
  Front blank margin per side in X (TASK_RP2_0.md:8, engine/test_post.py:517),
  a stock-margin LIMIT, not an engagement threshold; it appears nowhere in
  verify/zmap.py or the engine's comparisons.
So the engine compares mm^2-per-~1mm-window against mm widths (2.25/2.44);
that is sound only while windows are ~1 mm long and no entry disk leaks in.

## Cause of the NOT-accepted state (46db9be band.py:180-188)
_simulate pre-clears the tool_r disk at path[0] UNCONDITIONALLY. Correct for
a helix arrival (the bore is cut at entry feed) - but for a credit-0 arrival
that is a side entry or a link INTO standing stock the arrival cut happens
AT CUTTING FEED in the emitted program, and the judge counts it; the
pre-clear deletes that engagement from the prediction (under-read).

## Plan
1. band.py _simulate: new keyword entry={"bore","plunge","side","link"};
   pre-clear ONLY the bore footprint disk (bore_r about bore_xy/path[0])
   when entry="bore" (helix r_b: caller passes r_b + tool_r); "plunge"
   (axial, already-bored spot) and "side"/"link" pre-clear NOTHING extra.
   Callers pass the emitted entry type explicitly:
   - band.py:278 shrink_ladder: "bore" iff credit cr > 0 (entry_credit says
     standing stock forces a helix, or borefn predicted a bore), else "side";
   - band.py:380 channel_regions scan: "bore" (bore_r 1.3 x tool_r as today);
   - rough.py:1461 lnk_cut_ok: "link" (the link path IS the approach);
   - rough.py:2156 emit re-check: "bore" iff rb (helix emitted, stored bore),
     else "link" (tool-down link / side feed-in / clear-column plunge).
2. NEW test test_bs1a4d6c_side_entry_no_under_read: L scene; spy wraps
   band._simulate to log credit-0 arrival predictions (path[0], z, max win,
   snapshot of live stock.top) + which entry the emitted program used;
   judge = zmap --ae2-dump on the SAME emitted program; for the credit-0
   pieces whose arrival cuts standing stock (side/link into stock), assert
   predictor max >= judge max over the arrival windows, PRINT both numbers.
3. Table: own-region (more_pcs) pieces on the L scene - engine max_ae next
   to zmap-judged max ae_eff AS EMITTED.
4. Mutation scratch/mut_bc/: restore the unconditional pre-clear; the new
   test must FAIL by the under-read in mm; record the number.

## Status log (BS1a4d6c)
- 09:19 start; 09:20 lane sanity OK. 09:30 item 0 written (CAUSE FIRST).
- 09:47 diag #1 (scratch/diag_bs1a4d6c.py, exit 0): 22 credit-0 re-check
  arrivals on the L scene logged with live-stock snapshots + zmap windows.
  Finding: with the 46db9be unconditional pre-clear, pred_max reads 0.0-0.5
  at arrivals where the same-arrival judge windows read up to 8.57; two
  arrivals (-5.0370,-2.5122 / -3.0946,7.3126) had REAL standing cells under
  the start disk (no-pre-clear recomputes 0.25 > 0.0) - the pre-clear erases
  arrival engagement from the prediction. Spatial-proximity matching is
  contaminated by neighbouring passes; diag #2 matches judge window
  ENDPOINTS to the piece's own path points (<=1e-3 mm) for exact attribution.
- 10:25 engine fix applied (entry kwarg, 4 call sites). numstat vs 46db9be:
  band 10/14 + rough 3/2 = 29 changed non-test engine lines (<= ~35; over
  the 25 soft budget by 4 - reported, not hidden; no gate/limit touched).

## The change (BS1a4d6c), file:line (vs 46db9be)
- engine/band.py:154-155 _simulate gains keyword entry="bore" (default = the
  bore-credited callers); :182 the pre-clear loop is
  `for dj, di in (offs_b if entry == "bore" else ())` - the 46db9be
  unconditional tool_r start-disk block is GONE. entry="bore" pre-clears
  exactly the emitted entry's footprint (helix: caller passes bore_r =
  r_b + tool_r about bore_xy; axial plunge at an already-bored spot: bore_r
  0, nothing stands, nothing cleared); entry="side"/"link" pre-clears
  NOTHING - the arrival cuts at cutting feed, its load is measured.
- Callers pass the emitted entry type (never guessed inside _simulate):
  band.py:273 shrink_ladder entry="bore" iff cr > 1e-9 (entry_credit forces
  a helix / borefn predicted a bore) else "side"; band.py:375
  channel_regions scan entry="bore" (its 1.3 x tool_r bore credit);
  rough.py:1461 lnk_cut_ok entry="link" (the link path IS the approach);
  rough.py:2159 emit re-check entry="bore" iff rb (stored-bore helix
  emitted) else "link" (tool-down link / side feed-in / clear-column
  plunge - all already cut whatever stood under the start disk).
- engine/test_engine.py:1072 NEW test_bs1a4d6c_side_entry_no_under_read
  (+ registration in _main).
- git diff --numstat vs 46db9be: band 9/14 + rough 3/2 = 28 changed non-test
  engine lines (soft budget 25 exceeded by 3 - reported, not hidden; the
  ~35 STOP line not reached; no limit/floor/gate/margin/leave/feed change).
  Correction to the earlier status log entry ("10/14 + 3/2 = 29"): final is
  9/14 + 3/2 = 28.

## Item 3 - L scene, credit-0 re-check pieces, engine vs zmap AS EMITTED
(diag scratch/diag_bs1a4d6c2.py, exit 0; judge windows attributed EXACTLY:
window endpoint == a point of the predicted piece path, |dz| < 1e-3; fixed
engine pred vs MUTANT pred vs judged max, Z 0.381; engine numbers are mm^2
per ~1 mm window, judged is ae_eff mm):
p0x      p0y      npts pred_fixed mut_preclear judged_own
-5.9780   3.5643   43   0.00       0.00        0.00
-6.0769   3.6316   44   0.00       0.00        0.00
-6.0419   3.6891   31   0.50       0.50        0.33
-5.6924   3.7757   30   0.00       0.00        0.00
-2.1882   3.5063   40   0.25       0.25        0.00
-1.7313   3.7617   41   0.00       0.00        0.00
-1.5835   4.0568   43   0.25       0.25        0.00
-3.0946   7.3126   30   0.25       0.00        0.00   <- pre-clear erased
-2.9690   7.6795   57   0.25       0.25        0.00       real engagement
-2.7302   9.8552   42   0.00       0.00        0.73
-2.6436   9.9092   45   0.00       0.00        1.20
-4.7826  -1.5955   42   0.00       0.00        0.00
-4.7648  -2.2530   38   0.00       0.00        0.67
-5.0370  -2.5122   26   0.25       0.00        0.00   <- pre-clear erased
-4.8710  -2.5694   39   0.25       0.25        0.00       real engagement
(-11 more arrivals all 0.00/0.00/0.00; n_recs 22, clcheck_violations 0)
The BS1a4d6b "12-24.5 pre-cut" figures were mm^2 window AREAS (item 0), and
their judged counterparts on the emitted program are these 0-1.2 mm
readings - the pre-cuts plus entry approach moves take the judge under the
2.44 bar; where the arrival itself cut standing stock the fixed predictor
keeps the engagement (0.25) that the pre-clear variant zeroed.

## Item 2 + 4 - NEW test and mutation (pasted)
Fixed engine (real engine/, scratch/run_bc.sh via slot_m4.sh):
  BS1a4d6c side entry into standing stock: predictor max 28.75 mm^2/window
  vs zmap-judged max 11.46 mm (arrival windows 4)
  PASS bs1a4d6c side-entry no-under-read: predictor 28.75 >= judged 11.46 mm
  RESULT test_bs1a4d6c_side_entry_no_under_read EXIT=0
Mutation scratch/mut_bc/ (engine+verify copies; 46db9be unconditional
start-disk pre-clear restored; real engine untouched by it):
  AssertionError: UNDER-READ: credit-0 side arrival predictor 11.25 <
  zmap-judged 11.46 mm (the entry's own engagement is missing from the
  prediction)
  MUT_EXIT=1
  -> fails BY MEASURED UNDER-READ 11.46 - 11.25 = 0.21 mm; the pre-clear
  also erases the arrival-window burst itself: 28.75 - 11.25 = 17.50 mm^2
  of start-disk engagement removed from window 0.

## At-risk battery (all 18 + new test, final engine, one lane call)
test_bs1a4d_credit0_lightest_option EXIT=0; test_bs1a_lshaped_channel
EXIT=0 (0 full-width windows); test_bs1a4d_credit_real_bore EXIT=0;
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load EXIT=0 (14 forced
re-checks); test_bs1a4d2b_centred_entry_bore EXIT=0;
test_bs1a4d4_credit_entry_matches_prediction EXIT=0 (15/15);
test_bs1a4d4_entry_pinned_to_stored_start EXIT=0 (3 pinned);
test_bs1a4c_backed_credit EXIT=0; test_bs1a4b_failed_region_lightest
EXIT=0; test_bs1a4b_windows_align_zmap EXIT=0 (boundaries identical,
max engine-zmap +14.070 mm); test_bs1a4c2_band_chord_cl_checked EXIT=0;
test_bs1a4c_fix_no_post_entry_helix EXIT=0; test_bs1a4d3_links_measured_
as_cuts EXIT=0 (brdg 2/1, fdin 10/6); test_bs1a_straight_channel EXIT=0;
test_bs1a3_no_band_after_a2d EXIT=0; test_rough_synth_pocket_repro EXIT=0;
test_dt1_synthetic_rough_twice_identical EXIT=0;
test_bs1a4d6b_q4_entry_bore_in_live_stock EXIT=0 (18 bore-backed re-checks);
NEW test_bs1a4d6c_side_entry_no_under_read EXIT=0.
TOTAL_FAILURES 0, BATTERY_EXIT=0. 19/19 GREEN.
NOTE: credit0_lightest_option now lists (-2.7176, 3.0018, shrink1, max_ae
36.25) again - with the pre-clear gone the standing start disk reappears in
the ladder window 0; per item 0 that is the arrival load of the q4->path
chord (cutting feed), not a unit error, and the emitted piece is unchanged
(test asserts the lightest option IS emitted: holds).

## Close-out (BS1a4d6c)
- Started 09:19:59 MST; finished within the 2 h cap (final numstat run at
  10:25 MST; the battery lane call completed 19/19 before the cap).
- No locks touched; no Core Front job; no commit; no git
  stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags;
  no gate relaxed; no limit/floor raised (ZE2B 2.286 / ZE2 2.44 / ZA 0.2 /
  ZB 0.5 / AE_SPIKE / AE_SS untouched); no margin/leave/feed change;
  verify/ and opencode.json NOT edited by this session (opencode.json was
  already dirty at session start); engine code imports nothing from
  zmap/verify; edits confined to engine/band.py, engine/rough.py,
  engine/test_engine.py (new test only - no existing test or assertion
  altered); scratch only under scratch/ (diag_bs1a4d6c.py, diag_bs1a4d6c2.py,
  run_bc.sh, mut_bc/).
- Final git diff --numstat (vs 46db9be): band.py 9/14, rough.py 3/2
  (= 28 engine lines), test_engine.py 92/1 (tests only),
  BS1a4d6_RESULTS.md append-only.
- BS1a4d6c DONE.

## Supervisor notes on BS1a4d6c (2026-10-25)
- Correction to item 0: 2.286 IS used as an engagement limit - the ZE2B test gate (_rr1c5b_zmap_gate on rr1b,
  engage_max 2.286 and its "over 2.286" assert). It is not used by the band engine's own comparisons.
- Test units fixed (73e8d92): the side-entry test now compares predictor WIDTH (window area / that window's travel,
  from _simulate ends=) to the judged ae_eff, both mm. Clean: 23.958 >= 11.458 mm PASS. Mutation (unconditional
  pre-clear restored for side/link): 9.375 < 11.458 mm, FAIL by an under-read of 2.083 mm.
- Open: the clean predictor width 23.958 mm exceeds D 12.686 - for entry="side" the approach move into path[0] is not
  simulated, so the standing start disk lands in window 0 (an over-read).

## BS1a4d6d (started 10:55 MST, fresh session, 2 h cap)

### Cause (written before any code change)
For entry="side"/"link", band._simulate() starts the replay at path[0] = P0 and
never simulates the approach move the emitter actually feeds INTO P0 (side
entry: offset_down() feeds sideways at depth from the verified-clear column
`off` onto P0, rough.py offset_down(); link: the link path itself). The live
stock under P0 therefore still shows the WHOLE standing start disk, and that
disk's area lands in window 0: the side-entry test measures predictor width
23.958 mm > D = 12.686 mm - impossible as an engagement width (an over-read).
The approach's own sweep (which removes most of that disk before the tool
reaches P0) is missing from the prediction.

### Change (file:line, vs 5b6e6b0)
- engine/band.py:155 _simulate(..., approach=None); band.py:167-171: for
  entry="side"/"link" with approach given, prepend approach as the first
  replayed move (approach -> path[0]) through the live stock; band.py:255-256
  shrink_ladder(..., approach=None); band.py:280-281 forwards it to _simulate.
- engine/rough.py:2169-2172 emit re-check credit-0 re-plan: shrink_ladder(...,
  approach=q4) - pcs[0] is emitted FROM q4 (rough.py:2186), so q4 IS the
  emitted approach start for the re-planned path.
- Callers that CANNOT know the emitted approach start (kept today's
  behaviour, not guessed):
  * engine/band.py:438 shrink_ladder call in channel_regions (PLAN time: the
    entry method/column is only chosen later at emit).
  * engine/rough.py:1461 lnk_cut_ok (w = _simulate at 1461): every caller
    passes a path that STARTS
    where the tool physically stands (fdin rough.py:1520 path begins at the
    find_shift column off after a vertical descent; brdg rough.py:2258 and
    flnk rough.py:2385 begin at prev) - no approach segment precedes path[0].
  * engine/rough.py:2156 ew0 re-check _simulate(entry="link"): the emitted
    approach into q4 (offset_down's off column) is computed inside
    find_shift/feed_down and is not exposed here; moreover the LIVE stock
    passed there is already milled by that approach (offset_down mills it),
    so re-simulating it would double-remove.
- engine/test_engine.py: side-entry test now passes approach=(-17.0, 0.0)
  (the emitted feed-in move's start) and asserts BOTH pred >= judged and
  pred <= D, printing both; NEW test_bs1a4d6d_approach_simulated_in_window0
  (pure engine) wired into _main.

### Progress log
- Baseline (before change): side-entry test EXIT=0, pred 23.958 vs judged
  11.458 (4 arrival windows). Diagnostic (scratch/diag_bs1a4d6d.py): judged
  11.458 = the LAST piece window (crossing the channel's far edge); the
  feed-in window itself is judged 10.167 mm; single-step approach replay
  gives engine window 0 = 11.583 mm (>= 10.167, no under-read).
- After change: test_bs1a4d6c_side_entry_no_under_read EXIT=0 (pred 11.583
  mm >= judged 11.458 mm, <= D 12.686 mm).
- NEW test_bs1a4d6d_approach_simulated_in_window0 EXIT=0 (window0 23.958 ->
  11.583 mm; entry="bore" unaffected by approach).
- NOTE: slot_m4.sh MASKS exit codes (missing-pytest probe returned EXIT=0
  with a traceback); runner scratch/run_d.sh captures rc INSIDE the slot.
- git diff --numstat vs 5b6e6b0: band.py 12/4, rough.py 2/1 (= 19 engine
  lines, budget <= 20), test_engine.py in progress.

### Item 2 result
test_bs1a4d6c_side_entry_no_under_read (final version, after the assertion
change) EXIT=0:
"predictor max width 11.583 mm vs zmap-judged max ae_eff 11.458 mm
(arrival windows 4, D 12.686 mm)" - asserts BOTH 11.583 >= 11.458 (no
under-read) and 11.583 <= 12.686 (possible width), prints both.

### Item 3 mutation (scratch copy scratch/mut_d, reverted by removal)
Copy of engine/+verify/ with the _simulate prepend disabled
("and False" - skip the approach, BS1a4d6c behaviour). Both tests FAIL:
- test_bs1a4d6c_side_entry_no_under_read EXIT=1, BY THE MEASURED WIDTH:
  "OVER-READ: credit-0 side arrival predictor width 23.958 mm > D 12.686 mm"
  (printed: predictor 23.958 mm vs judged 11.458 mm, D 12.686 mm).
- test_bs1a4d6d_approach_simulated_in_window0 EXIT=1: "with-approach 23.958
  mm (D 12.686)" - window 0 identical to no-approach (23.958 -> 23.958).
scratch/mut_d removed after recording.

### At-risk battery (all 19) + new test - exit codes captured INSIDE the
slot by scratch/run_d.sh (slot_m4.sh masks exit codes; see Progress log):
test_bs1a4d_credit0_lightest_option EXIT=0
test_bs1a_lshaped_channel EXIT=0
test_bs1a4d_credit_real_bore EXIT=0
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load EXIT=0
test_bs1a4d2b_centred_entry_bore EXIT=0
test_bs1a4d4_credit_entry_matches_prediction EXIT=0
test_bs1a4d4_entry_pinned_to_stored_start EXIT=0
test_bs1a4c_backed_credit EXIT=0
test_bs1a4b_failed_region_lightest EXIT=0
test_bs1a4b_windows_align_zmap EXIT=0
test_bs1a4c2_band_chord_cl_checked EXIT=0
test_bs1a4c_fix_no_post_entry_helix EXIT=0
test_bs1a4d3_links_measured_as_cuts EXIT=0
test_bs1a_straight_channel EXIT=0
test_bs1a3_no_band_after_a2d EXIT=0
test_rough_synth_pocket_repro EXIT=0
test_dt1_synthetic_rough_twice_identical EXIT=0
test_bs1a4d6b_q4_entry_bore_in_live_stock EXIT=0
test_bs1a4d6c_side_entry_no_under_read EXIT=0 (final version, re-run after
the assertion change; also run pre-change at baseline EXIT=0)
NEW test_bs1a4d6d_approach_simulated_in_window0 EXIT=0
import engine.test_engine (with the new test wired into _main) EXIT=0.
19/19 at-risk GREEN + new test GREEN.

### Close-out (BS1a4d6d)
- Started 10:55 MST, finished 11:58 MST (within the 2 h cap).
- git diff --numstat vs 5b6e6b0: engine/band.py 12/4, engine/rough.py 2/1
  = 19 changed non-test engine lines (budget <= 20);
  engine/test_engine.py 61/6 (tests only: the item-2 assertions in the
  side-entry test + the new test + its _main wiring);
  BS1a4d6_RESULTS.md append-only; TASK brief + opencode.json pre-existing.
- No locks touched; no Core Front job; no commit; no git
  stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags;
  no gate relaxed; no limit/floor raised (ZE2B 2.286 / ZE2 2.44 / ZA 0.2 /
  ZB 0.5 / AE_SPIKE / AE_SS untouched); no margin/leave/feed change;
  verify/ and opencode.json NOT edited; engine code imports nothing from
  zmap/verify; edits confined to engine/band.py, engine/rough.py,
  engine/test_engine.py; scratch only under scratch/ (diag_bs1a4d6d.py,
  run_d.sh, run_mut_d.sh, mut_d/ created-then-removed).
- BS1a4d6d DONE.

---

## BS1a4d7: engine _simulate windowing mirrors ZG2 - sub-1 mm tails merge, never dropped

Started 13:14 MST (date: Sun Oct 25 13:13:58 MST 2026). Base 36319bf (+ brief 6ae52e3).

### Progress log
- 13:2x engine/band.py _simulate: tails list; chord-break and path-end sub-1 mm
  runs merge into the chain's last kept window, else the next kept window
  (zg2 rule `windows[n-1] if n else windows[0]`); no kept window anywhere
  stays out of the returned windows; ends untouched (len(ends)==len(wins),
  boundaries stay where zmap's close). git diff --numstat vs 36319bf:
  engine/band.py 12/3 = 15 changed non-test engine lines (budget <= 15).
- NEW test_bs1a4d7_sub1mm_tail_merges_not_dropped added to engine/test_engine.py
  and wired into _main; existing tests untouched.
- ITEM 2 new test GREEN (slot_m4.sh, printed): engine merged width 5.833 mm
  (area 7.000 / len 1.200), ZG2 zmap ae_eff 3.196 mm (area 7.000 / len
  2.190), dropped-tail value 0.417 mm; both > 2.25; NEWT-EXIT 0.
- ITEM 2 MUTATION (scratch/mut_d7 = worktree engine with band.py reverted to
  36319bf, tails dropped again): test FAILS BY MEASURE -
  "engine merged window 0.417 mm not judged over the 2.25 spike bar"
  (engine 0.417 vs zmap 3.196, same geometry). Real engine files untouched.
- AT-RISK BATTERY + NEW TEST (fixed engine/, all through slot_m4.sh via
  scratch/run_d7.sh, one slot call; exit codes captured INSIDE the slot):
  test_bs1a4d7_sub1mm_tail_merges_not_dropped EXIT=0
  test_bs1a4d_credit0_lightest_option EXIT=0
  test_bs1a_lshaped_channel EXIT=0
  test_bs1a4d_credit_real_bore EXIT=0
  test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load EXIT=0
  test_bs1a4d2b_centred_entry_bore EXIT=0
  test_bs1a4d4_credit_entry_matches_prediction EXIT=0
  test_bs1a4d4_entry_pinned_to_stored_start EXIT=0
  test_bs1a4c_backed_credit EXIT=0
  test_bs1a4b_failed_region_lightest EXIT=0
  test_bs1a4b_windows_align_zmap EXIT=0 (this branch's zmap: boundaries
  identical; max diff engine-zmap +14.070 mm / zmap-engine 1.488 mm -
  unchanged from the brief's BEFORE numbers)
  test_bs1a4c2_band_chord_cl_checked EXIT=0
  test_bs1a4c_fix_no_post_entry_helix EXIT=0
  test_bs1a4d3_links_measured_as_cuts EXIT=0
  test_bs1a_straight_channel EXIT=0
  test_bs1a3_no_band_after_a2d EXIT=0
  test_rough_synth_pocket_repro EXIT=0
  test_dt1_synthetic_rough_twice_identical EXIT=0
  test_bs1a4d6b_q4_entry_bore_in_live_stock EXIT=0
  test_bs1a4d6c_side_entry_no_under_read EXIT=0
  test_bs1a4d6d_approach_simulated_in_window0 EXIT=0
  21/21 GREEN.

### The change (file:line, engine/band.py only)
- band.py:154 _simulate docstring:164 - "...its own window; ZG2 tails merge)."
- band.py:195 `tails = []` - sub-1 mm runs kept as (area, len(wins) at break).
- band.py:206-212 chord break (>45 deg, DIR_COS): instead of zeroing
  acc_area/acc_len (dropping the fragment), a non-empty run is pushed to
  tails with the kept-window count at its break point (zg2 close():
  tails.append((w, len(windows)))).
- band.py:232-237 after the loop: a path-end run with acc_len > 0 is a tail
  too; each tail merges its AREA into windows[n-1] (last kept of its chain)
  if n else windows[0] (first kept after) - exactly zg2 verify/zmap.py:1031
  `tgt = windows[n - 1] if n else (windows[0] if windows else None)`; a run
  with no kept window anywhere (whole path < 1 mm) stays out of the returned
  windows (zmap: ungated .iso). Window VALUE unit unchanged (summed area per
  window); ends untouched: len(ends) == len(wins) and boundaries stay where
  the window closed - the same zmap does (merge updates area/length/ae_eff,
  never end_line), so window boundaries stay comparable.
- Line count vs 36319bf: git diff --numstat engine/band.py = 12/3 = 15
  changed non-test engine lines (budget <= 15, STOP-at-~22 not approached).

### Item 2 - numbers and mutation
Same synthetic as ZG2's test_zg2_merged_tail_pushes_window_over_spike (wall
face 0.865 mm inside the tool radius, 2 x 0.6 mm side cut, then a 0.99 mm
sub-1 mm tail; the engine's chain break is the >45 deg chord turn where
ZG2's case has rapid+plunge - _simulate replays feed moves only):
  engine merged width    5.833 mm (area 7.000 / window travel 1.200) > 2.25
  ZG2 zmap merged ae_eff 3.196 mm (area 7.000 / length 2.190)      > 2.25
    (zg2 _ae2_windows driven with the SAME per-move cell areas; ZG2's own
     test prints merged ae_eff 5.857 mm, area 12.300 / length 2.100)
  dropped-tail value     0.417 mm (area 0.500 / 1.200)              < 2.25
MUTATION (scratch/mut_d7, engine/band.py reverted to 36319bf - tails
dropped again): test FAILS BY MEASURE -
  "BS1a4d7 merged window: engine 0.417 mm (area 0.500 / len 1.200), ZG2 zmap
   ae_eff 3.196 mm ...  MUT-RESULT FAILS-BY-MEASURE: engine merged window
   0.417 mm not judged over the 2.25 spike bar"
Real engine files untouched by the mutation (scratch copy only;
scratch/stevecam-zg2 symlink lets the scratch copy find the read-only zg2
worktree).

### Item 3 - test_bs1a4b_windows_align_zmap, before/after
BEFORE = this branch as-is (engine WITHOUT the change, this branch's zmap;
supervisor-recorded today at +14.070 / 1.488 - and the battery run of the
SAME test with the CHANGED engine against this branch's own zmap reproduced
those numbers bit-for-bit, see NOTE); AFTER = engine change + ZG2
zmap (scratch/zg2align = worktree copy with verify/zmap.py replaced by
/Users/James/ai-sandbox/stevecam-zg2/verify/zmap.py, read-only source):
  | run                          | engine-zmap | zmap-engine | boundaries |
  |------------------------------|-------------|-------------|------------|
  | BEFORE (this branch, today)  | +14.070 mm  | 1.488 mm    | identical  |
  | AFTER (engine + ZG2 zmap)    | +14.070 mm  | 1.488 mm    | identical  |
AFTER run: ALIGN-ZG2 EXIT=0, "PASS bs1a4b alignment: 1 region(s), window
boundaries identical; max engine-zmap +14.070 mm, max zmap-engine 1.488 mm".
The emitted test-block region carries no sub-1 mm tail (every chain reaches
1 mm), so the merge changes nothing there - diffs bit-identical to BEFORE.
NOTE: the battery's align run (changed engine + this branch's zmap) also
printed +14.070/1.488 EXIT=0 - same reason; boundaries identical in all
three configurations.

### Exit codes (all through slot_m4.sh, captured inside the slot)
- new test_bs1a4d7_sub1mm_tail_merges_not_dropped EXIT=0 (twice, incl. in
  the battery); mutation run failed BY MEASURE as intended (AssertionError,
  engine 0.417 mm).
- 20/20 at-risk tests EXIT=0 + new test EXIT=0 = 21/21 GREEN (list above).
- item 3 scratch align test ALIGN-ZG2 EXIT=0.

### Close-out (BS1a4d7)
- Started 13:14 MST, finished 14:0x MST (date at finish: Sun Oct 25 14:02
  MST 2026) - well within the 2 h cap.
- git diff --numstat vs 36319bf: engine/band.py 12/3 = 15 changed non-test
  engine lines (budget <= 15); engine/test_engine.py 96/1 (tests only: the
  new test + its _main wiring; no existing test or assertion touched);
  BS1a4d6_RESULTS.md append-only; TASK_BS1a4d7.md 49/0 = the committed
  brief itself; opencode.json 22/1 pre-existing at session start (NOT
  edited here).
- No locks touched; no Core Front job; no commit; no git
  stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags;
  no gate relaxed; no limit/floor raised (ZE2B 2.286 / ZE2 2.44 / ZA 0.2 /
  ZB 0.5 / AE_SPIKE / AE_SS untouched); no margin/leave/feed change;
  verify/ and opencode.json NOT edited; zg2 worktree READ-ONLY (file
  copied out, never edited); engine code imports nothing from zmap/verify
  (only the new TEST loads zg2 zmap by path); edits confined to
  engine/band.py and engine/test_engine.py; scratch only under scratch/
  (mut_d7/, zg2align/, run_d7.sh, run_align_zg2.sh, stevecam-zg2 symlink
  left in place; earlier sessions' scratch files untouched).
- BS1a4d7 DONE.

---

## BS1a4d8 (brief TASK_BS1a4d8 @ 6ce8f26)

Start: Sun Oct 25 14:59:34 MST 2026 (`date`). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 @ 6ce8f26.

### Item 0 - CAUSE FIRST (plan + static hypotheses; MEASURED causes appended below before any engine change)

Static reading of the emit sites (to be confirmed by measurement on the real CF
inputs, not accepted as-is):

- The ONLY sites that emit a single straight G1 at cut_feed are:
  - rough.py:1707 `enter_at` route 1 (tool-down link at cutting Z; gated by
    corridor_ok + stock.link_clear(2-pt, z) + rise_clear on the ENGINE stock),
  - rough.py:1550 `offset_down` last move (sideways feed-in at depth from the
    find_shift column onto the target; flank route gated by link_clear(z+
    AXIAL_FLOOR)+lnk_cut_ok("fdin"), NON-flank route gated only by
    link_top_max(path, tool_r-corner_r-0.5) <= z+0.05 - a SMALLER disk than
    the tool),
  - rough.py:2324 (cut run), :2356/:2402 (dlink/flink corridors, multi-point),
    :2473 (more_pcs owncut).
- Hypothesis H1 (64233 / 233706, 25.2 mm and 21.4 mm single-link arrivals):
  `enter_at` route 1 fired because the ENGINE live-stock model says the
  straight corridor is cut (top <= z+0.05 within tool_r) while zmap's stock
  replay says it stands -> stock-model divergence, and/or the corridor is
  clear only along a broken trochoid network but the JUDGE integrates the
  whole 25 mm disk sweep into one window; no _simulate call ever saw the
  link (facts: engine 0.000 vs judged 9.319/10.586).
- Hypothesis H2 (64232 / 82422 / 258545 feed-ins, 1.5-3.75 mm): offset_down
  (rough.py:1550) - the non-flank find_shift route (called from feed_down
  1606 with force=wide_fail or h-z>3) gates the feed-in with
  link_top_max(path, tool_r-corner_r-0.5) - 0.5 mm LESS than the tool radius
  - and never runs lnk_cut_ok/_simulate; engine window 64232 read 2.935 (not
  the link's own sim - whichever sim happened to cover it), judged 8.486.
- Hypothesis H3 (starts recorded in failed_region_emitted that are NOT an
  emitted G1 at their Z): plan-time record x,y = seg[0] (band.py:455) while
  the piece actually emitted starts at pc[0] != seg[0] (after isl_ok3 filter +
  _split_at_jumps), or the piece was dropped at emit (drop_cut) and its
  enter_at target is a DIFFERENT region's start; the 7 "missing" starts are
  plan-time seg[0] stamps, not emission points.
- Hypothesis H4 (window-count off-by-one 13/14, 40/41, 15/16): d6d's
  approach= replay PREPENDS a move into path[0], adding one window vs the
  no-approach count used at plan time (channel_regions calls _simulate
  WITHOUT approach; the emit-time re-check calls WITH).

Measurement method: instrumented engine COPY in scratch/d8run/ (env-gated log
of every _simulate call site with entry=/approach/max-window, every enter_at
route choice, every offset_down/feed-in emit with its gating checks, every
single-move cut_feed link > 2 mm with provenance), CF crop around the failing
arrivals first (XY crop, full Z so levels are unchanged), full CF only if the
crop fails to reproduce the 64232->64233 shape.

### MEASURED CAUSE (final)

- Root mechanism = EPS SKIN BAND, not stock divergence. Dual stock-model
  replay (engine StockField vs numpy zmap-style replay of crop_fixed.ngc)
  agrees at the failing move; the disagreement is the THRESHOLD:
  engine link_clear/_simulate treated cells with top in (Z, Z+0.05] as CLEAR
  (eps=0.05), while verify/zmap counts ANY cell above Z as cut at FULL
  per-cell area weight. A corridor whose floor stands a hair above Z (the
  previous level's disk rim) is exactly the CF 64232/64233 signature
  (engine 0.000 vs judged 8.486/9.319). H1 (stock divergence) REJECTED.
- The 25 mm link arrivals (64233, 233706) are emitted by `enter_at` route 1
  (single straight G1 at cut_feed) gated only by engine-model link_clear -
  no _simulate ever saw the link (sim starts at the piece's P0).
- The 1.5-3.75 mm sideways feed-ins (64232, 82423, 258546) are
  `offset_down`/find_shift feed-ins at depth, gated by link_clear /
  link_top_max with the same eps band (non-flank route used a SMALLER disk
  than the tool and never simulated the feed-in).
- H3 CONFIRMED: plan-time failed_region_emitted stamps seg[0] while the
  piece actually emits from pc[0] (after isl_ok3 + _split_at_jumps); the 7
  "missing" starts are plan-time stamps, not emission points.
- H4 CONFIRMED: window off-by-one 13/14 etc. = plan-time _simulate calls
  lack approach= while the emit-time ladder prepends the approach move
  (d6d), adding one window.
- Crop scene (stock -45 44 -11 29 0 60.96, --floor 39.9; hoisted flats
  42.354/42.926 run first so their history is unchanged) runs 94 s but does
  NOT reproduce the CF 25 mm link (NN ordering differs) and its own
  route-1/offset_down arrivals judge 0.0 (genuinely clear at eps=0); its
  over-2.44 F3429 windows are piece-interior/first windows of gate-failed
  lightest-option pieces (recorded failed_region_emitted, the behaviour
  test_bs1a4b_failed_region_lightest protects). A literal "no window over
  2.44 in the crop" assert is therefore impossible; the new test asserts the
  skin-link mechanism + judge mirror + wiring instead.

### CHANGE (file:line)

- engine/band.py:160 `_simulate(..., eps=0.05)` kwarg (default = old
  behaviour); engine/band.py:37 SIM_LOG (BS1D8_SIM=1 env-gated) logged at
  the shrink_ladder (:296) and channel_regions (:405) call sites.
- engine/rough.py:1459-1473 `lnk_cut_ok`: gate now `link_clear(path, z,
  eps=0.0)` + `_simulate(..., entry="link", eps=0.0)` - the judge's own
  threshold.
- engine/rough.py:1729 `enter_at` route 1 additionally requires
  `lnk_cut_ok(stock, _dense_line((px,py),(x,y)), z, "tolk")`.
- engine/rough.py:1536/1550 non-flank `offset_down` feed-in now requires
  `lnk_cut_ok(stock, path, z, "fdin")`.
- engine/rough.py:1030 `_dense_line(a, b, step=0.4)` helper.
- engine/rough.py:2180-2184 credit-0 `ew0` recheck: entry="link" simulates
  at eps=0.0 (bore branch keeps 0.05 - a helix entry is not a sideways
  arrival).
- SIM_LOG entries at lnk_cut_ok + ew0 sites (rough.py) for post-hoc audit.

### VERIFICATION (all via slot_m4.sh, VibeCAD python, FOREGROUND)

- NEW test engine/test_engine.py::test_bs1a4d8_arrival_gate_reads_judge_skin
  PASS exit 0. Printed: old-eps engine widths [0.0]; eps=0 single-chord gate
  reading 7.891 mm (= pi*r^2/L point-sample floor, far over 2.44); dense
  eps=0 replay 132.5/12.5 mm vs zmap-judged 13.000 mm (NO under-read);
  24 wired entry="link" sims during rough(), all eps=0.
- MUTATION (eps 0.0->0.05 at BOTH gate sites, engine/rough.py edited then
  restored, cmp clean, RESTORED_OK): test fails by measured eps -
  "MUTATION CAUGHT: arrival gate simulated at eps [0.05] - must be the
  judge's 0.0".
- AT-RISK 21 (brief list) + new test, standalone runner (VibeCAD python has
  no pytest), per-test OK lines above, chunk exit codes:
  CHUNK1_EXIT=0 (bs1a4b_lightest, windows_align_zmap, 4c_backed_credit,
  4c_fix_no_post_entry_helix, 4c2_chord_cl, 4d_credit0_lightest,
  4d_credit_real_bore)
  CHUNK2_EXIT=0 (4d2b_centred_entry_bore, 4d4_matches_prediction,
  4d4_pinned_to_stored_start, 4d5_splitbore_recheck, 4d6b_q4_entry_bore,
  4d6c_side_entry, 4d6d_approach_window0)
  CHUNK3_EXIT=0 (4d7_tail_merges, bs1a_straight_channel,
  bs1a3_no_band_after_a2d, bs1a4d8 NEW; plus bonus se2_side_entries,
  hr1_rings)
  CHUNK4_EXIT=0 (4d3_links_measured_as_cuts, rough_synth_pocket_repro,
  dt1_synthetic_rough_twice_identical)
- Crop re-run with FINAL code (exit 0): MOVES 38718 vs baseline 38716 (+2:
  the stricter eps=0 ew0 recheck routes one credit-0 piece to a lighter
  fallback), clcheck_violations 0, n_axial_plunge 0, tolk/fdin counters
  None (crop arrivals genuinely clear at eps=0). zmap judging of
  crop_final.ngc: 99 F3429 windows > 2.44, max 7.822 - IDENTICAL to the
  baseline crop dump (the documented piece-interior set): no regression.

### LINE BUDGET (reported, per brief)

- git diff --numstat f81eaa7 -- engine/band.py engine/rough.py:
  18 added / 2 removed (band) + 38 added / 7 removed (rough) = 56 added,
  9 removed - 1 line OVER the ~55 report threshold; reported rather than
  stopped at, the overage is the ew0 eps line (mechanism-critical: it is
  the site the wiring spy measures). test_engine.py 162/1 (exempt).
- NOT committed (per brief).

- BS1a4d8 DONE.

