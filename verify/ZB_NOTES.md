# Task ZB notes (do not commit)

## Status
- `pytest verify -q`: 93 passed (supervisor run; holder CLI test now uses a pre-cleared slot via --stock-in).
- `pytest connector -q`: 86 passed, 9 failed - the same 9 real-engine e2e tests as ZA2 (rough plunges until RT2; finish/rest plunges until FE).

## Change summary
- verify/zmap.py: BALL_AXIAL_FLOOR = 0.5 mm - FIXED constant (James's
  0.381 mm finish leave + measurement noise), NOT tied to any per-program
  leave parameter, documented at the constant, never raised. A ball axial
  plunge uses the same rule as flat/bull (descending feed steeper than
  MAX_RAMP_DEG=15, angle from arc length for helical arcs) and removes
  stock deeper than BALL_AXIAL_FLOOR under the ball: deepest removed column
  stock - (z_end + dz(d)) over the ball's contact disk = the tool's full
  radius R around the end XY, judged against the spherical surface.
  Ball plunges now FAIL (CLI exit 1) exactly like flat/bull ones; the
  report carries floor_mm per tool type (flat/bull: 0.2, ball: 0.5).
- connector/runner.py _check_zmap_gates: axial plunges > 0 now fail EVERY
  tool type (finish/rest ball programs included); check_program uses the
  same gate, so it fails ball plunges the same way. Nothing else changed;
  the flat/bull gate (MAX_RAMP_DEG=15, AXIAL_FLOOR=0.2) is untouched.
- verify/test_zmap.py: ball plunge now must-fail (1.0 mm straight plunge
  into a block; deep plunge CLI exit 1); must-pass: ball descent onto
  0.381 mm of leave (0.381 < 0.5), ramped (~14.7 deg <= 15) ball entry
  into the block; real interim finish chained after interim rough fails
  with the exact >2 mm entry count asserted. Ball fixtures that plunged
  only to set up another check now enter honestly (ZA2 pattern: descend to
  stock top, ramp <= 15 deg or helix <= 15 deg); every assertion kept.

## Fixtures kept as plunges (plunge IS the checked scenario; simulate-only,
## never runs the CLI/gate; weakening them would delete assertions)
- test_shank_over_flute_wall: asserts on the plunge move itself
  (over_flute first_line == 3 "the plunge move", count == 2 = plunge +
  traverse); an honest ramp/helix entry would change those counts.
- test_vertical_wall_ball_gouge intruding case (b): gouges > 0 is the
  assertion; entries are honest helices now.
- HOLDER_GCODE (S5 holder tests): 20 mm descent inside a narrow slot; a
  <= 15 deg helix there needs ~24 turns - the descent positions the tool
  for the holder-clearance scenario itself. Simulate-only, gate never runs.

## Connector e2e tests that run the REAL finish/rest (expected failures
## until task FE gives the engine's finish honest entries)
PENDING - recorded from `pytest connector -q` below.
