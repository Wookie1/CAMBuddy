# SP-P1C — exact spatial culling for the island-clearance check — RESULTS

Session started on clean tree at 94c99f7 (main 562bf68 + task doc). Only
`opencode.json` was already modified (pre-existing, not touched).

## Plan
1. `island_clear_fn`: bucket grid (cell 1.0 mm, seg bbox expanded req+1e-6) +
   y-strips (1.0 mm, edge [min-1e-9, max+1e-9]) built once per call; f groups
   points by bucket/strip; same predicates/formulae => identical booleans.
2. `band._march`: batch 32 candidate points per isl_ok3 call; same d.
3. New tests `engine/test_sp_p1c.py` (verbatim *_ref copies + property test +
   march test + mutation self-checks (a)/(b)).
4. Targeted tests only; TB rough vs main byte-identical; CF T13 rough vs
   baseline MANIFEST + wall time vs 2,113.0 s.

## Side-effect audit (required before (2))
- `_march` is called ONLY from `band._centreline` (band.py:134/135), which is
  called ONLY from `band.channel_regions` (band.py:456) with the `isl_ok3` it
  receives.
- The only production caller is rough.py:2246 `channel_regions(rings, stock,
  isl_ok3, ...)`, where `isl_ok3 = island_clear_fn(islands, 0.03)`
  (rough.py:1949) — a pure numpy closure: no counters, no stats, no I/O.
- `isl_ok` (req 0.01) is never passed to `_march`.
- test_engine.py spies wrap `channel_regions` itself and pass `isl_ok3`
  through unchanged; none wraps it with a counter before `_march`.
=> Batching is safe. Proceeding.

## Runs log
(append after every test run)

### Run 0 — fixtures + TB rough BASELINE (pre-change, tree = 94c99f7)
- Fixtures copied from /Users/James/ai-sandbox/stevecam/out (manifest-pinned);
  `scripts/check_fixtures.py` -> "fixtures: 14 ok, 0 bad", **exit 0**.
- TB rough baseline (main code, slot_m4 lane, VibeCAD python):
  `engine.cli rough --step samples/test_block.step --stock -50 50 -40 40 0 38
  --tool flat:12.686 --floor 20 --leave 0.381 --final-zmin 20.381 --stepdown
  19.05 --optimal-load-mm 2.032 --hf out/test_block_hf_0.5.npy --out
  out/spp1c_tb_base.ngc` -> 40,862 moves in 110.1 s, **exit 0**.
26	4	opencode.json

### Implementation (rough.py island_clear_fn; band.py _march)
- island_clear_fn: bucket grid (cell 1.0 mm, seg bbox x [req+1e-6]) +
  y-strips (1.0 mm, edge [min-1e-9, max+1e-9]) built once per call; f groups
  points by bucket/strip, same _pt_seg_dist_np / crossing / xint expressions.
- band._march: batches of 32 candidate points per isl_ok3 call; d
  accumulates exactly as the old loop.
- New engine/test_sp_p1c.py with verbatim *_ref copies + in-memory-only
  mutations (working tree never patched).

### Run 1 — engine/test_sp_p1c.py (slot_m4 lane, VibeCAD python)
PASS list semantics + empty islands
PASS property: 30 sets, 662,866 pts total, req 0.0/0.01/0.03, 0 mismatches
PASS march: 2000 rays, identical floats
PASS mutation (a) bucket margin req+1e-6 -> req-0.5: mismatch COUNT = 42211
PASS mutation (b) strip margin dropped + half-open strips: COUNT = 54617
SP-P1C ALL PASS, **exit 0**.
16	6	engine/band.py
78	8	engine/rough.py
26	4	opencode.json

### Run 2 — at-risk existing tests (slot_m4 lane, one test per process)
- test_engine.py::test_island_clear_fn **exit 0**
- test_engine.py::test_allowance_violation **exit 0**
- test_engine.py::test_allowance_violation_containment **exit 0**
- test_engine.py::test_islands_grid_edge_parity **exit 0**
- test_engine.py::test_bs1a_straight_channel **exit 0**
- test_engine.py::test_bs1a_lshaped_channel **exit 0**
- test_engine.py::test_bs1a3_no_band_after_a2d **exit 0**
(First run of the four small ones was mistakenly NOT via the lane — also
exit 0; all were then re-run through slot_m4.sh as required, exit 0.)

### Run 3 — TB rough AFTER change (slot_m4 lane)
- Same command as Run 0, --out out/spp1c_tb_new.ngc -> **exit 0**.
- `cmp out/spp1c_tb_base.ngc out/spp1c_tb_new.ngc` -> **BYTE-IDENTICAL**.
- sha256 both: a35f7cc8d505489bde35895c6ba7ebf9db77dc1e740b8f5c929c6cd4a9ce6e93
- git diff --numstat: band.py 16/6, rough.py 78/8 (opencode.json pre-existing).

### Run 4 — remaining band tests (slot_m4 lane, one per process)
- test_engine.py::test_bs1a4c2_band_chord_cl_checked **exit 0**
- test_engine.py::test_bs1d_overload_band_on_standing_strip **exit 0**

### Run 5 — CF T13 rough AFTER change (slot_m4 lane, ENGINE_WORKERS<=4)
- `engine.cli rough --step samples/core_front_setup.step --stock -128.651
  128.651 -82.55 82.55 0.0 60.96 --tool flat:12.686:0.0 --floor 24.765
  --leave 0.381 --stepdown 19.05 --optimal-load-mm 2.032 --stepup 1.905 --hf
  out/core_front_setup_hf.npy --min-rest 0.5 --out out/spp1c_cf.ngc`
  -> **exit 0**, wall **1544.84 s** (user 2086.36 / sys 105.01).
- vs baseline 2,113.0 s: **-568.2 s = 1.37x faster (-26.9 %)**.
- `shasum -a 256 -c` vs MANIFEST rough_w4.ngc
  (72333caa408630bfd290c910052cfeb0f32ff4b7f0a63132065e0a6a1643ef0e):
  **OK - byte-identical**, check exit 0.

## Final summary
- Proof: TB rough .nc byte-identical to main (Run 0 vs Run 3, sha256
  a35f7cc8... both). CF T13 rough .nc byte-identical to baseline
  (72333caa..., Run 5). CF wall 1,544.84 s vs 2,113.0 s baseline (1.37x).
- Tests: engine/test_sp_p1c.py ALL PASS exit 0 (property: 30 sets /
  662,866 pts / req 0.0, 0.01, 0.03 / 0 mismatches; march: 2,000 rays equal
  floats; mutation (a) count 42,211, mutation (b) count 54,617 - both > 0,
  patches applied IN MEMORY only, tree never mutated). At-risk existing
  tests (island/allowance/grid-parity + 5 band tests) all exit 0.
- Side-effect audit of isl_ok3 into _march: pure island_clear_fn closure
  only (see top) - batching approved and done.
- Changes: engine/rough.py +78/-8 (island_clear_fn only), engine/band.py
  +16/-6 (_march only), new engine/test_sp_p1c.py, this results file.
  No existing test or caller, req, step or margin touched. opencode.json
  modification pre-existing. Nothing committed (per instructions).
16	6	engine/band.py
78	8	engine/rough.py
26	4	opencode.json
