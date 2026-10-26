# RR1c-3b results (rr1b worktree, base 6913c3f; not committed)

## (1) Line count
`git diff --numstat 6913c3f -- engine/rest_rough.py`: **24 adds / 7 dels = 31 changed lines**
(budget <= 60, stop ~80). No other file touched; nothing committed; slot locks / busy flag untouched.

## (2) Cause found, fix, tests

### Cause (both tests, one root cause)
`engine/rest_rough.py:648-663 (at 6913c3f)`: the thin-strip centre-line fallback
`march_level(Dz, xs, ys, c_mid = max(maxDz/2, CELL/2), comp=reg)` **returns zero paths** on a
1-2-cell-wide level strip. Two reasons, both structural in `march_level` (finish.py:616):
- every node inside the strip sits on the quantised distance-field plateau (`Dz >= c_mid`
  everywhere inside, since min inside Dz = CELL), so every all-corners-inside valid cell has
  case 15 and is excluded (`0 < case < 15` required);
- every mixed-case cell straddles the strip boundary, where a corner is outside `comp` ->
  the cell is invalid (`valid` = all four corners in comp).
Probe (small-test lane): test A's level region: 272 cells, Dz.max 0.4, c_mid 0.2 ->
`march_level(c_mid) n paths: 0`. So the thin level produced no paths at all: test A's zone was
entered (step 4) but 0 mm cut; test B's descent groove level (t = 26.208, r_max_cl 0.2)
produced no paths -> `levels` stayed 1 ("only the entered level cut"). `passes_skipped` was 0
in both cases (never reached - `paths` was empty), which is why the old code failed silently.

### Fix
`engine/rest_rough.py:649-680`: trace the same iso `c = max(maxDz/2, CELL/2)` over a 1-cell
**dilated** comp (`dil = binary_dilation(reg)`, rest_rough.py:662) so boundary cells become
valid and the ordered contour is the loop bounding the whole strip; keep it only if every point
of every loop stays leave-legal against the exact CL (batched drop-cutter vs `t - rest_leave
+ 0.005`, rest_rough.py:671-677); if the loop is rejected (concave floor: strip edges rise
above CL + leave) or absent, fall back to the axis zig-zag (rest_rough.py:678-679), whose
centre run still hits a straight thin strip exactly on its centre line. Every emitted point of
these paths goes through the existing exact CL check (`clneed = True`, rest_rough.py:680,
consumed at :749-763) - fail closed, as briefed. No test, threshold, verify/, cli or
entry_depth file changed; no bypass flags.

### Tests (small-test lane slot_m4.sh only, ENGINE_WORKERS <= 4)
Log: `/private/var/folders/zb/.../T/opencode/rr1c3b_all.log` (+ rr1c3b_A/B.log, rr1c3b_nums.log):
- `test_rr1c3_curved_thin_band_centre_line`: **PASS, exit 0** ("A ok").
- `test_rr1c3_bay_deep_groove_top_down`: **FAIL, exit 1** - now only the last assertion:
  "groove floor leaves 1.675 mm (want <= 0.5)" at sample (17, 60). Everything else passes:
  both levels cut (`levels = 2`, entry_steps [2, 2]), `validate_exact` 0, all entries <= 0.5 mm,
  groove-floor depth at (17, py) = 0.01 mm for py = 12/24/36/48 (was ~2.0 on e206c56).
  This residual is provably unavoidable - see (3b) below; per HARD RULES the test may not be
  relaxed, so B is reported, not passed.
- full `engine/test_engine.py`: summary line **"1 failure(s)"** - only the B floor assertion
  above; every other test (incl. A) passes.
- `engine/test_finish.py`: **"ALL FINISH TESTS PASSED"**.
(The suite exit codes were echoed after `| tail` in the runner, so the suites' own summary
lines are quoted; A/B exit codes above are python's real exit statuses.)

## (3) Item 3 - test A's ">= 80 % of the centre line"
Measured (rr1c3b_nums.log): cut-feed length inside the test's +-0.7 mm window around r = 30:
**60.9 mm of the 47.1 mm centre line = 129 %**; `validate_exact` 0.

What is actually machined, honestly:
- the excess mask splits into components [0.4, 0.4, 0.6, 0.6, 0.8, 0.8, 2.2, 2.2, 10.9] mm2;
  `find_zones` keeps only >= 5 mm2, so the zone is the middle arc of the quarter ring:
  21.7 deg .. 68.3 deg = **24.4 mm of the 47.1 mm centre line (52 %)**. The rest are the two
  end caps (~11.4 mm each, **22.7 mm total**, 0.4-2.2 mm2 fragments under the 5 mm2 filter -
  they cannot be kept: test A asserts `len(zones) == 1`).
- within the zone, the emitted path is the loop bounding the 0.4 mm-wide strip, so it traverses
  both edges (~2 x 24.4 mm + caps = the 60.9 mm counted); every point of the zone arc is
  machined (the 9.525 mm ball spans the 0.4 mm band ~12x over, so one edge already removes all
  rest across the band - coverage of the material is complete, the length is double-counted).
So: more than end caps is "missing" from the *centre line* in the literal sense - only 52 % of
the 47.1 mm arc is inside any zone at all (end caps dropped by the area filter, plus the
0.5 mm stock-grid quantisation that leaves no cell centres in the annulus near the axes); the
>= 80 % assertion is met by both-edge coverage of that zone (129 %), not by 80 % single-pass
centre-line coverage.

### (3b) Why test B's py = 60 sample cannot pass (proof, numbers)
Sample (17, 60) at tip Z 26.2 is 4.25 mm from the north end block `box(10,24,64,68,20,30)`
whose top face z = 30 IS the part surface; stock there is also 30, so no legal move may lower
it (that would be a gouge the same test forbids via `validate_exact`). A ball of R = 4.7625
with tip at 26.2 reaches d <= R, and any cell at distance d with stock 30 contributes
`30 - lift(d) - 26.2` to `disk_depth`: at d = 4.25 that is **1.187 mm > 0.5** (measured
worst 1.675 incl. the d ~ 4.0 corner). Equivalently the exact part CL at (17, 60) is
**>= 27.822 mm** (ball vs the block's top edge y = 64, z = 30) - a tip of 26.2 cannot
physically exist at that column, let alone machine it to leave. Combining the two assertions:
stamping cell (17, 64.25) below 30 requires a move with `tip < 30 - lift(d)` at path distance
d, while legality (even with just the 0.195 leave margin of validate_exact) requires
`tip >= 30 + sqrt(R^2 - delta^2) - R` with `delta = d - 0.25 < d` - a contradiction. The
engine's actual residual at that point (1.675) is therefore the geometric floor, not a
plannable miss; py = 12..48 (all points where tip 26.2 is CL-reachable) come out at 0.01 mm.
Fixing this would require editing the test's sample points or its threshold - both forbidden.

## (4) Not done / status
- Do-item 2 partially: test B's final floor assertion is unsatisfiable as written (proof in
  3b); everything else in Do-items 1-2 passes (centre-line paths now emit and are CL-checked;
  top-down descent cuts the groove level to 0.01 mm on all reachable samples; full
  test_engine = only B's floor line; test_finish all green).
- No commit (as instructed); no lock ever touched; slot never bypassed.
- Suggested supervisor options (not taken): move B's sample py = 60 to <= 59 or compare
  against CL + leave instead of fixed tip 26.2 - both are test edits, forbidden here.
