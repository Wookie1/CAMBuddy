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
