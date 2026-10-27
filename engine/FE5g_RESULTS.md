# FE5g RESULTS

Session start: Tue Oct 27 13:52 MST 2026 (2 h hard cap => stop by ~15:52).
Baseline: d24ec80 (brief) on fe5-trial; line budget measured vs 74582f3.
Final line count: `git diff --numstat 74582f3 -- engine/finish.py engine/entry_depth.py`
=> `80	11	engine/finish.py` (91 changed lines; entry_depth.py untouched; ~90 STOP
line reached, no further code growth).

## OUTCOME (summary)
- RED test 1 (engine/test_finish.py::test_fe5g_no_lifted_vertex_in_constant_z_pass):
  **GREEN** - "fe5g lifted vertices in constant-Z passes: 0 (max lift 0.000)".
- RED test 2 (connector/test_connector.py::TestZg1connStockBottomE2E::
  test_tb_rest_chain_checks_stock_bottom): **still RED**, but the ORIGINAL
  violation is fixed (0.815 mm plunge at (-5.763, 20.745) is gone; gouges 0,
  below_stock_bottom 0, rapid_collisions 0). A different axial gate violation
  (1.130 mm entry-link plunge at (-34.763, 34.744)) appeared, caused by the
  engine's live-stock ENTRY estimator being optimistic vs the zmap fine-grid
  simulation at near-vertical entries hugging walls - diagnosis below, NOT
  fixed within the cap.
- No regressions: full engine/test_finish.py, engine/test_entry_depth.py,
  5 at-risk test_engine.py tests, verify/test_zmap.py -k "zg1 or ze2b",
  connector/test_tlg1.py all EXIT=0 (pasted below).

## CAUSE
engine/finish.py, `grid_snap()` - TWO lift sites emit vertices at ceil(CL)
instead of the pass line when a constant-Z pass runs along a wall-top edge:
1. snap step (~line 1292): a snapped vertex kept at an output-grid CORNER whose
   CL is far above the pass Z (own_ok accepted the corner anyway) is emitted at
   Z = ceil(max(corner CL, z)). This alone created ALL 98 lifted vertices of
   red test 1's synthetic scene (boss ball-catch corners: corner CL 0.7-4.6 mm
   above the level, own CL fine) - diag scratch/diag_fe5g.py: "final lifted:
   98 (max 4.607) / lifted not from grid_snap: 0".
2. densify/repair branch (~line 1388): when a snapped chord's one-sided dip
   exceeds max(NET_TOL, pre-snap dip) the chord is DENSIFIED - interior samples
   INSERTED at Z = ceil(drop-cutter CL) at their own XY. Where the pass crosses
   a wall-top edge that CL is far above pass Z (e.g. 28.268 in a Z26 pass at
   X-5.796 on the TB block).
Either way the pass climbs to the inserted/kept vertex and drops back over
~0.03-0.1 mm XY - an in-pass descent ~90 deg deep, which FE5e/FE5f
(entry-only logic) never examines. No other stage inserts a vertex at sampled
CL: segment_net/simplify_rounds/vertex_net/shank_net/holder_net/grid_snap-drop
all SPLIT or DROP, and simplify_rounds only re-inserts ORIGINAL vertices.

## Change (engine/finish.py only; entry_depth.py untouched)
1. ROOT, `grid_snap()` snap step: a snapped vertex whose corner CL exceeds its
   pass Z by more than ZB_FLOOR_BALL (0.5, the ball floor) is DROPPED (run
   splits there; pieces rejoin via the verified link_plan/clcheck link)
   instead of lifted - condition `d > GRID_SPIKE and (not own_ok or
   c > z + ZB_FLOOR_BALL)` (~line 1292). Violations <= 0.5 keep the old
   behaviour (they cannot drive the ball past the floor).
2. ROOT, `grid_snap()` densify branch: inserted samples keep the PASS LINE
   (Z = max(chord Z, ceil CL), never below CL); a sample whose CL is > pass Z +
   ZB_FLOOR_BALL SPLITs the pass there (~line 1390, `if pz > lzz +
   ZB_FLOOR_BALL:`). The 0.5 threshold (not GRID_SPIKE=0.01) was chosen after
   regression: at 0.01 the FE5f bore scene split at violations of 0.011-0.101
   mm, the wall fragments became FE5f skips (23 vs baseline 16) and the skip
   cluster drifted off the bore axis (test_fe5f_skip_bore_entries failed). At
   0.5 the baseline numbers reproduce exactly (16 skips, cluster [0.0,-0.466]).
3. SAFETY NET, `_fe5g_inpass()` (~line 1871) called per pass inside the FE5
   loop before stamping (finish AND rest passes): in-pass G1 descents steeper
   than FE5G_MAX_DESCENT_DEG (15.0, mirror of zmap MAX_RAMP_DEG) whose live
   disk_depth exceeds ZB_FLOOR_BALL are ramped along the pass's OWN following
   vertices (XY fixed, Z only rises); a descent into the LAST vertex trims the
   tail (never the whole pass) and reports it. Non-finite disk_depth treated
   as safe (FE5fc convention). Stats: fe5g_ramped_n, fe5g_trimmed_n,
   fe5g_trimmed ([{"x","y","z","depth"}]).
4. Constant FE5G_MAX_DESCENT_DEG = 15.0 (~line 111).
No gate touched; no existing test edited; no existing pass point moved; no
whole pass skipped by the net.
NEW tests added to engine/test_finish.py (both pass):
test_fe5g_scene_vertices_never_below_cl (39516 G1 scene vertices, 0 below CL
by >0.004) and test_fe5g_net_ramps_and_trims_inpass_drop (unit test of the
net: mid-pass drop ramped to <=2 deg slopes, tail drop trimmed + reported).

## Test log (chronological, all via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh)
- (13:53) RED test 1 on baseline: FAIL as expected - "98 lifted vertices, max
  4.607" (exit code lost to `| tail`; reruns below use no pipe).
- (13:56) scratch/diag_fe5g.py: exit 0; all lifted vertices are grid_snap.
- (14:20) RED test 1 after fix: PASS - "0 lifted (max 0.000)", EXIT=0.
- (14:26) E2E run 1 (GRID_SPIKE threshold + net): EXIT=1 (scratch/e2e_tb.log,
  1 failed in 476.36s). Original 0.815@(-5.763,20.745) plunge GONE; failure is
  now axial_plunges: 2, max 1.1303 mm at (-34.763, 34.744) first line 27680
  (+ (-21.255, 21.237)); gouges 0, below_stock_bottom 0, rapid_collisions 0.
- (14:3x) full engine/test_finish.py run 1: EXIT=1 - test_fe5f_skip_bore_entries
  failed ("no skip cluster centred on the bore axis", cluster drifted to
  [-0.989,-5.476]); everything else passed. Mutation copies
  (scratch/mut_net / mut_densify / mut_snap) showed the densify split firing at
  radius ~12 for violations of 0.011-0.101 mm -> FIX: 0.5 threshold (above).
- (14:4x) RED test 1 + test_fe5f_skip_bore_entries: EXIT=0, both PASS:
  "0 lifted (max 0.000)"; "skipped 16 passes in 1 cluster(s) at [0.0, -0.466]
  (max live depth 5.90 mm)" = identical to baseline.
- (14:18/14:4x) full engine/test_finish.py (ZB threshold + net): EXIT=0,
  "ALL FINISH TESTS PASSED" (5m36s, scratch/test_finish_full2.log).
- (14:47) engine/test_entry_depth.py: EXIT=0 (scratch/entry_depth2.log).
- (14:47) test_engine.py x5 (test_rr1b_rest_rough_synth_pocket,
  test_rr1c3_bay_deep_groove_top_down, test_rra2_deep_top_scope,
  test_rra3_straight_descent_scope, test_rr1c5c_closed_pocket_bore_entry_no_deep_axial):
  EXIT=0 (scratch/test_engine5.log).
- (14:47) verify/test_zmap.py -k "zg1 or ze2b" (/opt/homebrew/bin/python3):
  18 passed, EXIT=0 (scratch/zmap_zg1.log).
- (14:47) connector/test_tlg1.py: 8 passed, EXIT=0 (scratch/tlg1.log).
- (14:58) E2E run 2 (ZB threshold + net): EXIT=1 (scratch/e2e_tb2.log,
  1 failed in 472.50s). check_finish.json: axial_plunges count 2,
  max_depth_mm 1.1303, first_line 27680, worst_xy [-34.763, 34.744], floor
  0.5; gouges 0, below_stock_bottom 0, rapid_collisions 0, plunge_over_flute
  0. finish_stats: fe5g_ramped_n 18, fe5g_trimmed_n 0, n_gridsnap_splits 363,
  n_gridsnap_dropped 28, fe5_skipped_n 17.
  NOTE: the test itself dies on `FileNotFoundError: .../runs/1950/check.json`
  - check.json is only written when every sub-check passes; the numbers above
  are from runs/1950/check_finish.json.
- (~15:00) temporary NET-OFF-DIAG edit (`if False and ...` around the
  _fe5g_inpass call) prepared for attribution but no time to spend an E2E run
  on it; edit REVERTED. Post-revert verification: py_compile OK +
  test_fe5g_net_ramps_and_trims_inpass_drop PASS, EXIT=0 (~15:10).

## Where I got stuck (red test 2)
The remaining 1.130 mm violation is NOT in-pass: finish.nc line 27680 is a
vertical G1 Z descent at the START of a constant-Z pass (G00 XY then G01 Z
down, then G1 along the pass) - an entry-link descent near the wall corner
(-34.76, 34.74), the same corner where the baseline had lifted vertices at
28.011-28.066 in the Z28 passes (red test 1's scene region).
- The engine FE5e/f entry logic sized this entry from the LiveStock estimator
  (engine/entry_depth.py: coarse 0.5 mm stock_after_rough_engine.npy, resampled
  to 0.1, stamped with generated passes only) and saw disk_depth <= 0.25 at the
  entry, so it allowed the straight G1 drop-in.
- The zmap judge uses the true 0.1 mm full-simulation stock_after_rough.npy and
  measures depth 1.130 there (stock top ~29.13 vs tool tip 28.0).
- Divergence traced to footprint-boundary cells: at the entry footprint a cell
  at distance 4.7640 from the path vs R = 4.7625 is EXCLUDED by zmap's
  `d <= R + 1e-9` while the coarse engine cell covers it - near-vertical ball
  surface means such cell flips move ~1 mm of apparent stock top.
- The plunges are NOT caused by the safety net (net ramps only in-pass descents;
  these are entry links) and NOT by the split threshold (finish.nc is
  byte-identical between the GRID_SPIKE-threshold and ZB-threshold runs; both
  E2E runs show the same violation). They appear because removing the lifted
  vertices changed this pass's entry geometry/stock history so the pre-existing
  estimator-vs-simulation optimism at wall-hugging entries now surfaces above
  the 0.5 floor (baseline: this corner was entered via a lifted vertex at
  higher Z, masking the same divergence).
A responsible fix means making the entry-depth check conservative vs the fine
grid (e.g. max-pooled coarse->fine resampling, or margin at wall-adjacent
entries) in engine/entry_depth.py - that changes every entry decision and
needs its own regression cycle (E2E alone is ~8 min/run; only ~35 min remained
and both suites must stay green), so I stopped here per the brief.

## Final diff
git diff --numstat 74582f3 -- engine/finish.py engine/entry_depth.py
80	11	engine/finish.py
(entry_depth.py: no changes)
git status: M engine/finish.py, M engine/test_finish.py (new FE5g tests),
?? engine/FE5g_RESULTS.md, ?? scratch/. NOT committed, per brief.
