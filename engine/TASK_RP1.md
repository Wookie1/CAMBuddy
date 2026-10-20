# Task RP step 1: fewer regions and links in roughing. Do not commit. Under ~250 lines. Two parts, MEASURE AFTER EACH.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/; keep programmed engagement = optimal load 2.032; ramp angle default 2 deg unchanged; NO post-pass that edits
Adaptive2d moves. Report ONLY numbers you produced this session from files that exist under /Users/James/ai-sandbox.
RUN HEAVY ENGINE JOBS ONE AT A TIME (this Mac also runs another model; memory is tight).
JUDGE = verify/zmap.py exit code + JSON only (never the engine's own counters):
  /opt/homebrew/bin/python3 verify/zmap.py <rough.ngc> --part out/cf_hf01_z5b.npy --tool flat --dia 12.686
    --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438 --jobs 6 --out-json <report.json>
Core Front T13 rough command (baseline = this branch's main code at 2 deg): engine.cli rough --step
  samples/core_front_setup.step --stock -128.651 128.651 -82.55 82.55 0.0 60.96 --tool flat:12.686:0.0 --floor 24.765
  --leave 0.381 --stepdown 19.05 --optimal-load-mm 2.032 --stepup 1.905 --hf out/core_front_setup_hf.npy --min-rest 0.5
Per-level breaks/regions: the RT_RP=1 instrumentation already here (RT_RP_OUT=<json>); RP0 baseline in
engine/RP0_RESULTS.md / out/rp0_cf.json: 213 regions, 2,342 breaks, 2,213 of them Adaptive2d tool-up link splits (0 mm
clipped), 3,218 a2d internal links; worst z 35.306 (565 breaks) and 42.354 (550).
(a) keep-tool-down: sweep a2d.keepToolDownDistRatio (report each value tried); AND treat Adaptive2d's own link segments
    that stay over cleared stock as at-depth links - only where the existing verified link check passes against the
    live stock AND part at that depth; anything failing retracts exactly as now. MEASURE: regions/breaks per level
    (esp. z 35.306, 42.354), rapids (m), entry time at 2 deg, total cycle time, horizontal p99, axial 0, all gates 0.
    If (a) alone meets the targets, STOP and report.
(b) Feed the SAFE region (part offset + CL-grid islands + stock box) as the Adaptive2d input boundary per level; the
    clip becomes an ASSERTION that fails the run if it would remove more than a trace (> 0.5 mm of path per level).
    Report the "under" area per level explicitly (safe area the old input boundary missed; see RP0's under_mm2 column)
    and whether (b) now roughs those areas AT THAT LEVEL - if any under-area is instead left for lower levels or the
    finish, measure it (area and depth left) as a coverage gap. MEASURE as in (a).
Targets: rapids <= 57 m; entry time < 5 min at 2 deg; horizontal p99 <= 6.7 (slot-p99 when the ZE report lands);
axial plunges 0; gouges/rapid collisions/outside-grid 0. STOP and report (engine/RP1_RESULTS.md) if a target can't be
met without workarounds. Engine suites + pytest verify connector engine/test_post.py green (fixtures: run
/opt/homebrew/bin/python3 scripts/check_fixtures.py first). FOREGROUND only.
