# SK1 RESULTS — thin side-skin entry from the air outside the stock

Session start: 2026-10-31. Branch wt sk1 @ 6215965. Cap 2 h. FOREGROUND only. Targeted tests only.

## Plan
1. Read find_shift/feed_down/offset_down/band._simulate/load_limit rule + CLI plumbing. (in progress)
2. rough.py: find_shift gains `air=` candidate class (air columns outside listed faces),
   SE2 link_clear replaced by _simulate load check (ae<=2.44, load<=1.2, a<=flute),
   flat-bottom floor check <= z+AXIAL_FLOOR. feed_down: try air class only where a plunge
   would be counted (side=True branch after helix fails; wide_fail branch before counting).
3. rough() kwargs: side_entry_faces (None/off), side_entry_min_z (None), flute_mm (None).
   cli.py rough: --side-entry-clear, --side-entry-min-z, --flute; flute from --tools-json
   entry ("flute_mm") by tool-number/diameter like finish.
4. stats["sk1_feedin"] records per feed-in {ae, load, a}; report maxima.
5. New tests engine/test_sk1.py (synthetic ring-skin block). Targeted runs only:
   test_sk1.py + named test_engine.py tests (side entries: test_bs1a4d6c_side_entry_no_under_read,
   test_rr1c_narrow_pocket_side_entry, test_se2_side_entries_only_through_cleared).
6. Mutation check (scratch, revert): disable air class -> synthetic test fails with n_axial_plunge>0.

## Rule compliance
- No Core Front jobs run. No existing tests edited. Nothing staged/committed.

## Runs log
(exit codes + git diff --numstat appended after every run)

- [pre-session WIP] compile check via lane: rough.py/cli.py/test_sk1.py py_compile OK (exit 0).
- Run 1: `python engine/test_sk1.py` via lane -> FAIL exit 1.
  test_sk1_air_entry_all_faces: RuntimeError axial-plunge FAILED, 3 pts
  ("wide", 10.769, 3.23 at z=10.381/0.95/0.381). Air class searched, all
  candidates rejected.
- Debug (temporary SK1_DBG instrumentation, since REMOVED; compile re-verified):
  * straight-out rung loop bound used the FAR grid edge -> hundreds of
    out-of-grid candidates (fixed: bound to the NEAR grid edge).
  * root cause: the ring's region entry point (10.769, 3.23) sits 0.0300 mm
    from this level's island loop (flange offset by tool_r+leave via
    level_islands), so it FAILS the strict self-pick oracle isl_ok3 (req
    >0.03) itself -> isl_ok3(_seg_clear) over the whole feed path can never
    pass for ANY candidate, because the endpoint is the engine's own entry
    point. Fix (entries-only, documented): validate the feed path at isl_ok3
    at 0.25 mm samples UP TO the entry point and the endpoint at isl_ok
    (0.01 - the oracle every emitted cutting point must meet anyway);
    hf_gouge_violation still checks the whole path (was None at target).
- Debug re-run after fixes: synthetic all-faces rough COMPLETES:
  plunges=0, n_side_entries=4, sk1_feedin 4 records, max ae=2.000 (<=2.44),
  max load=0.497 (<=1.2), max a=9.619 (<=flute 31.75). Columns (10.004,1.382)
  / (9.503,1.382): beyond yneg by >= tool_r+rapid_margin.
- Test-file fixes (new test file only): _main_rough_mod returned the module
  not rough() (TypeError); side-by-side main module moved into the package
  (engine/_sk1_rough_main.py, atexit-removed) so spawned pool workers can
  import it (was BrokenProcessPool).
- Run 2: `python engine/test_sk1.py` via lane -> exit 1 (TypeError in test 2,
  above). test_sk1_air_entry_all_faces PASSED.
- Run 3: -> exit 1 (BrokenProcessPool in test 2, above).
- Run 4 (fixes applied): `python engine/test_sk1.py` via lane -> **exit 0,
  SK1-ALL-PASS**:
  * test_sk1_air_entry_all_faces PASS: 4 air feed-ins, max ae=2.000
    max load=0.497 max a=9.619 (flute 31.75), side entries=4, 0 plunges.
  * test_sk1_no_faces_today_behaviour PASS: plunge count 4 == main 4.
  * test_sk1_partial_faces PASS: xpos-only, 0 xpos feed-ins accepted
    (entry sits at the yneg face), 4 plunges remain, no column beyond an
    unlisted face.
  * test_sk1_side_entry_min_z PASS: min_z=0.381 -> 4 entries all >= 0.381;
    min_z=0.881 -> no entry below it, 1 plunge remains.
  * test_sk1_tb_program_unchanged PASS: test block rough program
    byte-identical to main (md5 50815d1320ec7e235ee6c7b2d1bf2ea1).
  git diff --numstat: cli.py 59/1, rough.py 195/3, opencode.json 26/4
  (opencode.json pre-existing, not touched by this task).
- Run 5 (targeted existing tests, brief-named at-risk: find_shift /
  feed_down / side entries): via lane, calling directly (no pytest in the
  VibeCAD python; test_engine.py is a standalone runner without a filter):
  test_se2_side_entries_only_through_cleared,
  test_bs1a4d6c_side_entry_no_under_read,
  test_rr1c_narrow_pocket_side_entry -> **exit 0**, all 3 PASS
  (SE2: standing-wall part 0 side/helix, test block 5 side through cleared).
- Mutation check (scratch edit `_sk1_on = False` in rough.py, REVERTED after;
  revert verified by grep + py_compile exit 0): all-faces synthetic run via
  lane aborts exactly as today with **n_axial_plunge = 4** ("wide" points
  10.769/3.23 at z 10.381/0.95/0.381 + 10.268/3.23 at z 2.281) - the test
  fails with n_axial_plunge > 0. Count reported: 4.
- CLI smoke via lane (exit 0): `rough --help` lists --side-entry-clear,
  --side-entry-min-z, --flute; cli.table_flute reads flute_mm from
  tools/x7_tools.json (bull 12.7 -> 31.75, matches James's bull; flat 12.7
  -> None -> class OFF without --flute).
- Run 6 (FINAL, tree after mutation revert): `python engine/test_sk1.py`
  via lane -> **exit 0, SK1-ALL-PASS** (all 5 tests, same maxima as Run 4:
  4 feed-ins, max ae=2.000, max load=0.497, max a=9.619, flute 31.75).
  Final git diff --numstat: engine/cli.py 59/1, engine/rough.py 195/3,
  opencode.json 26/4 (pre-existing, untouched by this task).

## Design notes / deviations
- find_shift(air=True) air class per brief: candidates whose ENTIRE footprint
  (centre +- (tool_r + rapid_margin)) lies beyond a LISTED stock face (never
  beyond an unlisted one), inside the tracked grid; searched on the existing
  (dist, 16 directions) pattern + straight out through the nearest face to
  the grid edge (rung bound fixed to the NEAR grid edge). All existing
  candidate checks kept: judge-disk-clear descent (offs_wide <= z+0.04),
  isl_ok3 segment legality of the whole feed path, hf_gouge_violation on the
  feed path, rapid-clear G0 descent at the column (link_top_max <= z+0.05),
  flat-bottom floor check (link_top_max(path, tool_r-corner_r-0.5) <=
  z + AXIAL_FLOOR: flank engagement only, never the bottom).
- SE2 replacement for air candidates (brief 2): engine.band._simulate(path,
  live stock, z, tool_r, cell, 0.0, entry="link", eps=0.0) - every 1 mm
  window ae <= SPIKE_MM 2.44; load = ae_eff * a * F / (2.032 * 19.05 * F)
  (load_limit DESIGN_AE * DESIGN_STEPDOWN rule) <= LOAD_MAX 1.2; engaged
  axial a (max live top within tool_r along the path minus z) <= flute_mm.
  Per feed-in {ae, load, a, z, col} recorded in stats["sk1_feedin"] +
  running maxima sk1_max_ae/load/a; cli prints the maxima line.
- ONE documented refinement of "isl_ok3 on the whole feed path": the ring's
  region entry point (engine-picked, brief forbids touching region/path
  generation) sits 0.0300 mm from the level's island loop - the big-cutter
  (tool_r + leave) offset of the flange - so it is itself rejected by the
  strict self-pick oracle isl_ok3 (>0.03) and NO feed path ending there can
  pass it (this, not the column search, was the real blocker: found by
  instrumentation). Air feed-ins therefore check the path at 0.25 mm samples
  under isl_ok3 UP TO the entry point and the endpoint under isl_ok (0.01),
  the oracle every emitted cutting point must meet; hf_gouge_violation
  (exact part heightfield backstop, tool_r disk) still checks the WHOLE path
  including the endpoint and was clear at every accepted entry. No existing
  test conflicts (the SE2 test passes unchanged).
- Workholding (brief 3): --side-entry-clear default NONE and --flute/flute_mm
  required for the class to be ON (fail-closed, ValueError on unknown face
  names); --side-entry-min_z gates the descent Z. Wired through rough() as
  side_entry_faces / side_entry_min_z / flute_mm kwargs (default off);
  connector/runner.py NOT touched (connector-thread follow-up).
- Used only at the two axial-plunge sites of feed_down (side=True branch
  after helix fails; wide_fail branch before counting) - no other caller,
  no constants, no other entry type changed.
- rough()'s abort now attaches .stats to the RuntimeError (additive; used by
  the tests to read counts/records from the abort).

## Rule compliance (final)
- All commands foreground, waited; lane script used for every python run; no
  Core Front job run; no G-code printed. No existing test edited. Nothing
  staged or committed. Full suite NOT run (supervisor). Debug
  instrumentation removed from rough.py (grep clean, compile OK).
  engine/_sk1_rough_main.py (side-by-side main module) is atexit-removed and
  absent from git status. Scratch debug: out/sk1_dbg.py + out/sk1_*.log
  (out/ is scratch, not git).



