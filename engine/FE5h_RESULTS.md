# FE5h results — entry-depth estimate never under-reads the true live stock (ZB)

Started 15:08 MST (2 h cap => 17:08). Branch fe5-trial @ ea84f92 (FE5g a49c8d3 + brief).

## CAUSE (working, refined by local diagnosis below)
The FE5e/f entry decisions read engine/entry_depth.py LiveStock: the COARSE
engine post-rough stock (0.5 mm, stock_after_rough_engine.npy), resampled to
0.1 and stamped with the generated passes. The zmap judge reads the TRUE
0.1 mm full-simulation stock (its own rough sim + the posted finish.nc).
The engine estimate under-reads the judge's live stock wherever the two
stock models diverge near-vertical walls/ledges; FE5g measured a 1.130 mm
divergence at the TB wall corner (-34.763, 34.744) where the engine read
<= 0.25 and allowed a straight G1 drop-in (finish.nc line 27680).
Candidate divergence sources (FE5g diagnosis: footprint-boundary cells,
4.7640 vs R 4.7625, counted by one model and not the other):
  (i) coarse 0.5 mm engine rough kernel clears cells the judge's 0.1 mm sim
      never cuts (RT2 gotcha: engine clears ~c/√2 + c beyond the judge's
      footprint edge at the coarse cell lattice);
  (ii) LiveStock stamps its OWN cell centres (exact envelope, pre-post-grid
      path) while zmap stamps the posted program on ITS grid — cells near a
      footprint edge are stamped by one model and not the other.
Choice: name after local diagnosis (in progress).

## Test log
(pending)

## RED (a) on UNCHANGED code (before)
(16:0x) connector/test_connector.py::TestZg1connStockBottomE2E::test_tb_rest_chain_checks_stock_bottom
  -> pytest FAILED (exit code 1; "1 failed in 493.30s"), ZB blocks check.json
  (artifacts kept: scratch/bt_a_before/stevecam-home0/runs/1950/).

## CAUSE (confirmed by local diagnosis on the red-(a) artifacts)
The plunge (finish.nc line 28185: G00 X-34.763 Y34.744, G01 Z23.) lands where
zmap's 0.1 mm live stock has a thin HIGH-STOCK RIM: its worst cell
(-34.293, 30.007) sits at distance d = 4.7603 from the entry axis, i.e.
0.0022 mm INSIDE the ball radius R = 4.7625, with live stock 28.7467 ->
ZB depth 1.1303. The engine estimator reads its LiveStock at FINE cell
centres derived from the COARSE (0.5 mm) stock lattice: the nearest coarse
centre maps to d = 4.9624 (OUTSIDE the d <= R mask), so the resampled grid
has NO cell inside the mask where the judge's 0.1 mm grid keeps a tall rim
column - the coarse->fine resample loses sub-cell rim slivers and the
estimate reads 0.1443 (measured by replaying entry_depth over the emitted
program) while zmap measures 1.1303.
CHOSEN FIX: max-pooled (dilated) coarse->fine resampling in
engine/entry_depth.py - each fine initial-stock cell takes the max of the
coarse cells within a wall-adjacency margin (default = 2 coarse cells =
1.0 mm, covering the coarse lattice phase 0.707 mm + the coarse kernel's
optimistic clearing at footprint edges, the RT2 gotcha). Stamps and the
read stay exact; only the INITIAL resample becomes conservative, and only
when the source grid is coarser than the fine grid. Opt-in parameter so
rest_rough / build_rough_stock behaviour (fine source grid) is unchanged.

## Red test (b) BEFORE (engine UNCHANGED, fe5-trial @ ea84f92)

New test `engine/test_finish.py::test_fe5h_entry_estimate_not_below_true_depth`
(pocket floor 28.2 / stock 28.4, coarse post-roughing ridge remnant 29.55 at
the pocket corner raw zone; truth = test-built 0.1 judge grid: 2-cell
Chebyshev dilation of the coarse array + overlap resample, prefix-stamped
with `zmap.simulate`, exact ball read). Run 2026-10-27 via slot_m4:

    fe5h: 1 entries; deep ['(-8.000,-12.000) z=28.201 est=0.1985 truth=0.6085'];
          under-read ['(-8.000,-12.000) z=28.201 est=0.1985 truth=0.6085']
    AssertionError: FE5h: vertical entries below the 0.5 floor: [...]
    EXIT=1  (FAILED BY ASSERTION on the unchanged engine, as required)

Same mechanism as the TB chain's 1.1303 mm plunge: the coarse 0.5 lattice
(and the plain 0.5->0.1 overlap resample) hide the rim sliver (est 0.1985 ->
straight plunge) while the true 0.1 mm live stock stands 0.6085 mm above the
ball at the entry.

## The change (file:line, engine lines)

- engine/entry_depth.py: `resample_fine(..., margin=0.0)` (+18/-4 with
  LiveStock): opt-in data-preserving Chebyshev box-max dilation of the
  SOURCE grid (k = ceil(margin/cell) rounds of 3x3 max-pool) before the
  existing overlap resample; no-data cells stay no-data; default margin 0
  = byte-identical old behavior (rest_rough / rr tests untouched).
  `LiveStock.__init__(..., margin=0.0)` passes it through.
- engine/finish.py (+33/-3): the FE5 estimator LiveStock is built with
  `margin = 2*cell` when the stock grid is coarse (cell > FINE) - the 2-cell
  dilation dominates the fine-grid resample + ball-slope quantization, so
  the coarse read can no longer come in under the 0.1 mm judge read.
  Item 2 stats: a plain (margin 0) twin LiveStock stamped identically
  classifies each entry's decision BEFORE ("straight"/"ramp" at
  RAMP_TRIGGER) vs AFTER; changed decisions land in
  `stats["fe5h_changed_n"]` / `stats["fe5h_changed"]`
  ({"x","y","z","before","after"}, cap 400).
- Gates untouched: ZB_FLOOR_BALL 0.5, RAMP_TRIGGER 0.25, CLCHECK. No test
  deleted/renamed/relaxed; one NEW test added (red (b)).
- `git diff --numstat a49c8d3 -- engine/entry_depth.py engine/finish.py`:
  `18 4  engine/entry_depth.py` / `33 3  engine/finish.py` (58 changed
  lines, budget 60; STOP line 90 never reached).

## Red test (b) AFTER

    fe5h: 1 entries; deep []; under-read []
    EXIT=0  (entry now read 0.6085 == truth, ramped; no floor breach)

## AT-RISK battery (all ran, exit codes)

- engine/test_finish.py WHOLE suite via slot_m4: ALL FINISH TESTS PASSED,
  exit 0 (incl. fe5t 9 ramped/0 unresolved, fe5fc +2, fe5g nets).
- engine/test_entry_depth.py (frozen estimator tests) via slot_m4:
  ALL ENTRY_DEPTH TESTS PASSED, exit 0.
- verify/test_zmap.py -k "zg1 or ze2b": 18 passed, exit 0.
- connector/test_tlg1.py: 8 passed, exit 0.
- engine/test_engine.py rr1b/rr1c3/rra2/rra3/rr1c5c via slot_m4: all PASS,
  exit 0.

## DEVIATION: test_fe5f_skip_bore_entries skip count

Baseline (git archive of a49c8d3 engine, same scene): "skipped 16 passes in
1 cluster(s) at [0.0, -0.466] (max live depth 5.90 mm)".
After the fix: "skipped 21 passes in 1 cluster(s) at [0.0, 1.0] (max live
depth 5.90 mm)". The test's OWN assertions pass (exit 0: no bore entry
plunged > 0.5, cluster centred <= 1 mm on the bore axis), but the count and
cluster centre moved: the dilated read conservatively reads the bore-wall
entries deeper (plain-resample view <= trigger, dilated > trigger), so 5
more passes/fragments take the ramp->skip path. Direction is SAFE (more
skips, never a deeper plunge) and is the same sliver class the fix targets
- the frozen 16/[0.0,-0.466] printout is NOT preserved. Flagging for
supervisor judgement.

## Red test (a) AFTER - STILL FAILING (exit 1, 1 failed in 490.26s)

`test_tb_rest_chain_checks_stock_bottom` (scratch/bt_a_after): check.json
still absent; check_finish.json axial_plunges {count 2, max_depth_mm
1.1303, first_line 28010, worst_xy [-34.763, 34.744]}. Diagnosis: the
margin fix removes the RESAMPLE under-read (red (b) class), but the TB
worst plunge is a deep-level entry (G01 Z23. at line 28515) whose worst
cell (-34.293, 30.007) reads 21.381 in the coarse stock_after_rough_engine
grid while the judge's FINE rough sim leaves 28.7467 standing there (a
7.4 mm ROUGH-stage coarse-vs-fine stamp divergence, not a sub-cell resample
sliver). At plunge time the dilated rim values in the engine's live grid
have been cut below the ball surface by preceding finish chords, while the
judge's same cell was never swept (the engine's exact-chord LiveStock
envelope mills rim cells the judge's per-sample-point disks leave standing,
on top of the rough-side divergence) - est 0.1443 vs truth 1.1303 at every
margin 0/1/2. Closing red (a) needs the rough-side divergence addressed
(the RT2 coarse-kernel clear in rough.py / a rough-output-aware margin),
beyond FE5h's 60-line budget. Red (a) awaits supervisor.

## Status

Red (b): red on unchanged engine (est 0.1985 vs truth 0.6085), green with
the fix. All frozen estimator + finish + rr + zmap + tlg1 gates green; one
documented behavioral deviation (fe5f skip count 16->21, assertions still
green). Red (a) E2E still red - remaining cause is the rough-stage
coarse-vs-fine divergence at deep-level entries (above). NOT committed.

## Reviewed deviation (coordinator, 2026-10-27)
test_fe5f_skip_bore_entries reports 21 skipped bore-wall entries instead of 16 (cluster still centred on the bore axis).
ACCEPTED: James chose to skip the bores (drill them); the dilated entry stock reads more bore stock, so 5 more bore-wall
entries are skipped instead of plunged - conservative. The test asserts fe5_skipped_n >= 1 (it never pinned 16; 16 was the
brief's expectation), so no test value changes.
- Bore cluster AT BOUND, NO MARGIN (coordinator 2026-10-27): with FE5h the test_fe5f_skip_bore_entries cluster centre is
  [0.0, 1.0], exactly at the test's 1.0 mm bound (passes, no margin left). The test stays as is; the next change that touches
  the bores must be checked by hand here.
