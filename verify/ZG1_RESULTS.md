# ZG1 results — gouge rule blind spot at the global part minimum

Session start: Sun Oct 25 00:34 MST 2026 (`date`), branch `zg1` at c3cd812.

## Item 0 — fixtures / archived judge inputs WITHOUT a part mask (.hit.npy)

Lane note: `slot_m4.sh` was BUSY 00:38-~01:20 (owner PID 23022, another
session's job, plus a queued connector pytest ahead of me). Locks untouched
per LOCKS rule. The lane batch below ran 01:22-01:31 and is COMPLETE.

Empirical item-0 judge runs (new code, `/private/tmp/zg1_item0.py`, via the
lane; "fallback_extra_gouge_cells" = cells the OLD footprint rule was blind
to that the strict-everywhere fallback now judges — 0 means the fallback
cannot change the verdict):

- `out/core_front_setup_hf.npy` + `out/core_front_roughG.ngc`:
  `rc=1 part_mask=missing gouges={'count': 0, 'max_depth': 0.0,
  'worst_xy': None} fallback_extra_gouge_cells:0
  below_stock_bottom={'count': 0, ...} axial={count:80, max_depth_mm:17.145,
  first_line:67572}` (rc=1 is the PRE-EXISTING ZA axial gate, unchanged).
- `out/cf_hf01_z5b.npy` + `out/core_front_roughRT_before.ngc`:
  `rc=1 part_mask=missing gouges={'count': 0, ...}
  fallback_extra_gouge_cells:0 below_stock_bottom={'count': 0, ...}
  axial={count:489, max_depth_mm:25.654, first_line:63675}` — axial numbers
  byte-identical to the test's pinned expectations.

=> NO currently-green fixture/test turns red from the fallback; no STOP.

Manifest entries (fixtures/manifest.json) and archived judge inputs, and what
the strict-everywhere fallback (gouge mask = valid, no footprint exclusion)
does to each verdict:

1. `out/core_front_setup_hf.npy` (+ .json) — part heightfield, NO .hit.npy.
   Judge input for engine/test_post.py::test_zmap_matches_neutral (with
   out/core_front_roughG.ngc). Fallback: only ADDS gouge candidates at cells
   where part == global min AND finite stock < part - 0.02. The test asserts
   neutral-vs-inch EQUALITY (both sides get the same fallback), not a fixed
   count -> equality preserved either way. Verdict: stays green, CONFIRMED
   empirically (0 extra gouge cells, lane run above).
2. `out/cf_hf01_z5b.npy` (+ .json) — part heightfield, NO .hit.npy. Judge
   input for verify/test_zmap.py::test_axial_real_core_front_rough_fails
   (with out/core_front_roughRT_before.ngc). Test asserts rc==1 and the
   axial_plunges count/max/first_line only; gouges are not asserted and the
   axial gate already forces rc==1. Verdict: stays green, CONFIRMED
   empirically (lane run: 1 passed, gouges 0, axial 489 unchanged).
3. `out/test_block_hf_0.5.npy` (+ .json) — used by engine/test_engine.py as
   an ENGINE drop-cutter grid (engine.rough part_hf), never fed to
   zmap.analyze -> fallback irrelevant. Verdict: unchanged.
4. `out/test_block_hf_0.1.npy` (+ .json) — manifest entry only; no test reads
   it. Verdict: unchanged.
5. Non-heightfield entries (`core_front_roughG.ngc`, `core_front_rough_X7.nc`,
   `core_front_roughRT_before.ngc`, `test_block.stl`) — G-code/STL, not part
   judge grids; the fallback touches only the part-mask side. Unaffected
   except via the programs in 1-2 above.
6. All synthetic parts in verify/test_zmap.py (created with np.array, no
   .hit.npy) — fallback applies: gouge mask becomes every finite-stock cell.
   The at-risk synthetic tests passed 62/62 at BASELINE and are re-run after
   the change (exit codes below).

## The change (45 changed non-test lines in verify/, `git diff --numstat`)

`verify/zmap.py` (34 added, 1 removed):
- `PartField` (zmap.py:2279): `np.ndarray` subclass carrying `.hit`;
  `load_part` (zmap.py:2294-2296) views the part as `PartField` and loads
  `<stem>.hit.npy` onto it when present.
- `analyze` (zmap.py:2217, 2224-2225, 2248): gouge mask = `valid & hit`
  when the mask exists, else EVERY valid cell (fail closed); JSON gains
  `"part_mask": "present"|"missing"`. Leftover stats keep the old mask.
- `below_stock_bottom` (zmap.py:1468, 1501-1504, 1925-1926, 2207-2211):
  every cutting move whose lowest tip Z < stock-box zmin is recorded
  (line, xy, depth mm); `_bsb_report` = {count, max_depth, worst_xy,
  first_line}; merged exactly under `--jobs` (zmap.py:2152-2153).
- HARD GATE (zmap.py:2581-2586): non-zero exit naming count, max depth mm,
  worst xy, first line; report keys at zmap.py:2521-2522.

`verify/heightfield.py` (8 added, 2 removed):
- `rasterize(..., hit_out=None)` (heightfield.py:85) accumulates
  `hit[jlo:jhi+1, ilo:ihi+1] |= inside` per triangle (heightfield.py:103,
  128) and writes the bool mask to `hit_out` (heightfield.py:138-140);
  `main` passes `<stem>.hit.npy` next to the .npy (heightfield.py:150).
- Existing fixtures keep NO mask (regeneration is the supervisor's job),
  so every current fixture run exercises the fail-closed fallback and says
  `"part_mask": "missing"`.

`verify/test_zmap.py` (138 added, new tests only, nothing renamed/edited):
- `test_zg1_plate_minimum_face_gouge_with_hit_mask` — plate top face AT the
  global part minimum, 0.1 mm cut, `.hit.npy` present: gouge max_depth
  0.100 mm (fails under the old footprint rule).
- `test_zg1_plate_minimum_face_gouge_without_mask` — same without mask:
  fail-closed strict, `part_mask == "missing"`.
- `test_zg1_hit_mask_excludes_part_free_cells` — 0.1 mm cut into masked
  geometry + 0.15 mm cut into part-free zmin fill: measured max_depth must
  be 0.1, not 0.15.
- `test_zg1_below_stock_bottom_hard_gate` — tip 0.1 mm below stock bottom:
  rc==1, max_depth 0.100 mm, worst_xy [-20, 0], first_line 3.
- `test_zg1_at_stock_bottom_not_flagged` — cutting exactly TO the bottom:
  count 0, rc 0.
- `test_zg1_heightfield_writes_hit_mask` — rasterize hit_out: bool mask,
  True under geometry (also a top face AT zmin), False in the grown ring.

## Mutation outputs (scratch copies under /private/tmp/zg1_mut, never committed)

Control (unmutated copy): 6 passed, PYTEST_EXIT=0.
- (a) drop the hit-mask use (`gouge_mask = valid & ...` always):
  `test_zg1_hit_mask_excludes_part_free_cells` FAILED by MEASURED DEPTH:
  `max_depth 0.15000000000000036` vs required 0.1 (part-free cells judged
  as gouged). PYTEST_EXIT=1.
- (b) drop the fail-closed fallback (`else mask` = old footprint rule):
  `test_zg1_plate_minimum_face_gouge_without_mask` FAILED by MEASURED
  DEPTH: `{'count': 0, 'max_depth': 0.0}` vs required 0.1. PYTEST_EXIT=1.
- (c) drop the below_stock_bottom gate (`if False:`):
  `test_zg1_below_stock_bottom_hard_gate` FAILED: exit code 0 instead of 1
  (its depth assertion `max_depth == 0.1 mm` runs first and still pins the
  measured depth). PYTEST_EXIT=1.

## Test log

- 00:37 BASELINE (before any change), synthetic at-risk subset
  (`-k "gouge or ze2 or axial or strict or leftover"`, real-part axial test
  deselected): **62 passed, 53 deselected**, PYTEST_EXIT=0.
- After the change, same subset + `zg1`: **67 passed, 1 failed**,
  PYTEST_EXIT=1.
- The single failure is `test_ze2b_flat_and_bull_json_byte_identical`
  (test_zmap.py:2765). ROOT CAUSE, verified empirically on the test's own
  input (old b1688b8 zmap vs new zmap, same argv):
  `keys only in new: ['below_stock_bottom', 'part_mask']`,
  `common keys with changed value: []`.
  The test pins the flat/bull `--out-json` BYTE-IDENTICAL to b1688b8, while
  TASK_ZG1 items 1-2 MANDATE `"part_mask"` and the `below_stock_bottom`
  report IN that JSON — the requirements cannot coexist. Per the TESTS lock
  I did not touch the test; re-pinning byte-identity (e.g. comparing the
  common-key subset, or re-pinning to a post-ZG1 commit) is a supervisor
  decision. Every other value in the JSON is byte-equal.

## Test log (final)

- New tests `-k zg1`: 6 passed, PYTEST_EXIT=0.
- At-risk + new (synthetic): 67 passed, 1 failed (byte-identity conflict,
  above), PYTEST_EXIT=1.
- Lane (small-test slot, real parts):
  - `verify/test_zmap.py::test_axial_real_core_front_rough_fails`:
    1 passed in 184.31s, **AXIAL_EXIT=0**.
  - `engine/test_post.py::test_zmap_matches_neutral`:
    1 passed in 21.18s, **NEUTRAL_EXIT=0**.
  - item-0 judge script: **ITEM0_EXIT=0** (numbers above).
- Final `git diff --numstat -- verify/`:
  `8 2 verify/heightfield.py`, `138 0 verify/test_zmap.py`,
  `34 1 verify/zmap.py` -> 45 changed non-test lines.
- Not committed (per brief). `opencode.json` was already modified in the
  worktree before this session; untouched by me.
- Open item for the supervisor: `test_ze2b_flat_and_bull_json_byte_identical`
  cannot stay byte-identical to b1688b8 while the brief's `"part_mask"` and
  `below_stock_bottom` JSON keys exist (analysis + proof above).




---

# ZG1b — true stock bottom through --stock-in chains

- Session start: Sun Oct 25 04:10:43 MST 2026 (`date`), branch zg1 @ cbb60bd.
- Lane note: first two `slot_m4.sh` invocations (04:10, 04:12) timed out at
  120 s / 600 s because the small-test lane is held by another live session's
  job (`m4small.lock/pid` = 86492, alive since 04:11:33). Locks untouched.
  Waiting; meanwhile making the edits.

## Plan
1. `main()`: read `<stock-in stem>.json` sidecar key `stock_box`; explicit
   `--stock` wins, >1e-6 mm disagreement -> exit 1 naming both boxes.
2. Derived `stock_box` zmin (no `--stock`) = sidecar `stock_box[4]` if present,
   else -inf (gate can never fire); never `nanmin(stock_init)`.
3. No box at all -> report `below_stock_bottom` says the check was not done,
   why, and next_step "pass --stock or regenerate the stock file with this
   version"; exit code unaffected.
4. `--stock-out` merges `stock_box` (the ORIGINAL box: --stock, else the box
   read from the --stock-in sidecar; never the remaining stock) into
   `<stock-out stem>.json`, keeping existing keys.
5. New tests (test_zmap.py): chain-below-true-bottom fails with measured
   depth; old stock file w/o sidecar box -> unknown, exit 0; --stock vs
   sidecar disagreement error; --stock-out merges into existing sidecar.
6. Mutation in scratch/: restore nanmin(stock_init) bottom; test 4 must fail
   by a measured value.

## Test log
- Run 1 (lane, VibeCAD python): PYTEST_EXIT=1 — `No module named pytest`
  in /Applications/VibeCAD.app/Contents/Resources/bin/python (no tests ran).
- Probe (lane): /opt/homebrew/bin/python3 has pytest 9.1.1, numpy 2.4.3.
- Run 2 (lane, homebrew python):
  `pytest verify/test_zmap.py -q -k 'stock or chain or gouge or axial or
  strict or zg1 or ze2b_flat_and_bull_json_byte_identical'`
  -> **PYTEST_EXIT=1**, 3 failed, 59 passed, 63 deselected in 160.35s.
  ALL at-risk tests PASSED (incl. test_stock_chain_cli, every test_zg1_*,
  test_ze2b_flat_and_bull_json_byte_identical). The 3 failures are my NEW
  zg1b tests: test-side TypeError `PosixPath + ".json"` in the shared
  helper (fixed; zmap.py untouched by the fix).
- git diff --numstat at this point: 28 2 verify/zmap.py (30 changed lines,
  budget <=30), 114 0 verify/test_zmap.py.
- Run 3 (lane): `pytest verify/test_zmap.py -q -k zg1b` (my 4 new tests)
  -> **PYTEST_EXIT=0**, 4 passed.

## Change (verify/zmap.py, 28 added + 2 removed = 30 changed non-test lines)
- `main()` ~2477-2482: read the `--stock-in` sidecar `<stem>.json` key
  `stock_box` into `side_box` (never `nanmin(stock_init)`).
- ~2484-2487: explicit `--stock` wins; if it disagrees with the sidecar box
  by > 1e-6 mm in any coordinate, exit 1 with an error naming BOTH boxes.
- ~2497: derived `stock_box` zmin (no `--stock`) = `side_box[4]` if present,
  else `-inf` — the below_stock_bottom gate (zmap.py:1506) can never fire on
  a guess. XY derivation for the grid check unchanged; zmax unchanged.
- ~2500: `orig_box` = `--stock` box, else the sidecar box (the ORIGINAL
  starting stock, never the remaining stock).
- ~2553-2557: with no box at all the report's `below_stock_bottom` is
  `{"status": "unknown", ..., "reason": "stock bottom check NOT done: ...",
  "next_step": "pass --stock or regenerate the stock file with this
  version"}`; exit code unaffected (gate sees count 0).
- ~2602-2610: `--stock-out` merges `stock_box` (= `orig_box`) into
  `<stock-out stem>.json`, keeping any existing sidecar keys; no box known ->
  no `stock_box` key written.
- Report top-level keys unchanged (item 7): proven by
  `test_ze2b_flat_and_bull_json_byte_identical` passing.

## New tests (verify/test_zmap.py, +114 lines, appended only)
- `test_zg1b_chain_below_true_bottom_fails_by_value` — chain prog1
  `--stock-out` / prog2 `--stock-in` no `--stock`, tip to Z -0.25 (true
  bottom 0.0): exit 1 with measured `max_depth` 0.25 mm ±1e-6; prog2's own
  sidecar re-records the ORIGINAL box (bottom travels on).
- `test_zg1b_stock_without_sidecar_box_is_unknown` — sidecar removed (old
  stock file), cut to Z 4.5 (below remaining 6.0): `status == "unknown"`,
  count 0, reason + exact next_step, rc == 0.
- `test_zg1b_stock_vs_sidecar_box_disagreement_fails` — sidecar zmin 0.5 vs
  `--stock` zmin 0.0: exit 1, stderr names both values.
- `test_zg1b_stock_out_merges_existing_sidecar` — pre-existing
  x0/y0/cell keys survive; `stock_box` added.

## Exit codes (all via the small-test lane slot_m4.sh)
- Run 2 above: PYTEST_EXIT=1 (3 new tests, test-side Path+str bug; fixed).
- Run 3, new tests: `pytest verify/test_zmap.py -q -k zg1b`
  -> **PYTEST_EXIT=0**, 4 passed, 121 deselected in 0.23s.
- Final at-risk + new: `pytest verify/test_zmap.py -q -k 'stock or chain or
  gouge or axial or strict or zg1 or ze2b_flat_and_bull_json_byte_identical'`
  -> **FINAL_EXIT=0**, 62 passed, 63 deselected in 157.79s. Includes
  `test_stock_chain_cli` PASSING UNCHANGED, every `test_zg1_*`,
  `test_ze2b_flat_and_bull_json_byte_identical`, and
  `test_axial_real_core_front_rough_fails`.

## Mutation (scratch/mut/, never committed; scratch/zg1b_mutation.out)
Mutant = copy of zmap.py with zmin put back to `float(np.nanmin(stock_init))`
(scratch/mut/zmap.py:2497); tests = copy of test_zmap.py.
`pytest test_zmap.py -q -k 'test_zg1b_chain_below_true_bottom or
test_stock_chain_cli'` -> **MUTATION_EXIT=1**, 2 failed:
- `test_zg1b_chain_below_true_bottom_fails_by_value` fails BY MEASURED VALUE:
  "measured depth below the TRUE bottom must be 0.25 mm: {'count': 2,
  'max_depth': 6.26043481422465, ...}" — the nanmin bottom measures
  **6.26043481422465 mm** instead of 0.25 mm.
- `test_stock_chain_cli` also fails (`AssertionError: assert 1 == 0` at
  test_zmap.py:284 — the original "below the stock bottom Z 6.000" bug).

## Notes
- Lane was held 04:10-04:35 by another live session (m4small.lock/pid 86492,
  alive); locks untouched per LOCKS; queued waits eventually ran.
- `/Applications/VibeCAD.app/Contents/Resources/bin/python` has no pytest;
  lane test runs used `/opt/homebrew/bin/python3` (pytest 9.1.1), the same
  interpreter the other lane user runs.
- Not committed (per brief). `opencode.json` was already modified in this
  worktree before this session; untouched. `scratch/` left untracked.
- Session end: Sun Oct 25 05:02 MST 2026 (start 04:10, ~52 min < 2 h cap).
