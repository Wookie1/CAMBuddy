# Task RT2: finish the roughing-travel work against the REAL gate. Do not commit. Under ~200 more lines.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ (zmap is the judge); keep programmed engagement = optimal load 2.032; NO post-pass that edits Adaptive2d moves.
This branch = the stopped RT work + ZA (the zmap axial-plunge gate) + R6c-n (ONE helix diameter helix_dia = 0.8*D used
by Adaptive2d and _helix_moves; feed_down now passes helix_dia/2).
PASS/FAIL IS DECIDED ONLY BY THIS INDEPENDENT ZMAP COMMAND (exit code 0 and its JSON), never by the engine's own counters
(n_axial_plunge etc. do not decide anything - the last round reported axial 0 while zmap found 343):
  /opt/homebrew/bin/python3 verify/zmap.py <rough.ngc> --part out/cf_hf01_z5b.npy --tool flat --dia 12.686
    --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438 --jobs 6 --out-json <report.json>
  Test block: --part out/test_block_hf_0.1.npy --stock -50 50 -40 40 0 38 (same tool / engage-max).
ZA gate: any descending feed move steeper than 15 deg (angle from arc length for helical G2/G3) that removes > 0.2 mm
of stock under the flat bottom = axial plunge = FAIL.
Supervisor's judgement of the last RT Core Front output (out/core_front_roughRT_after.ngc): gouges/rapids/outside 0,
axial_plunges 343 (worst 5.905 mm at XY 2.732,-20.134, first line 67753); rapids 89.8 m (target <= 57 m); plunges
2.5 min (ok, keep < 5); entries 109,118 helix/ramp moves / 14.6 m / 11.3 min; cut 25.4 min; total 57.1 min;
horizontal engagement p50 2.080 p95 2.392 p99 12.686 (baseline before RT: 6.7).
0. FIRST (report in engine/RT2_RESULTS.md before changing code): where do the full-width (12.686) horizontal moves in
   out/core_front_roughRT_after.ngc come from? Classify the top ones (straight ramps through solid stock, new links at
   depth not classed as entries, helix depth circles, ...) with counts. Also: why 109k entry moves - over-fine segments?
1. Every descent into stock: a helix (helix_dia, starting at the verified-clear height just above the remaining stock)
   or a ramp at <= 2 deg; never steeper than 15 deg into stock. Fix all 343.
2. Rapids <= 57 m on Core Front; plunge time stays < 5 min; entry segments no finer than needed.
3. Horizontal p99 must not exceed 6.7 (the pre-RT baseline).
4. Report before/after on Core Front T13 and the test block: zmap gates incl. axial_plunges, rapid length, entry count,
   entry time, plunge time, total cycle time, horizontal p50/p95/p99.
STOP and report if a target can't be met without workarounds. Engine suites + pytest verify connector
engine/test_post.py green (connector e2e tests now pass only if the rough has 0 axial plunges). FOREGROUND jobs only.
