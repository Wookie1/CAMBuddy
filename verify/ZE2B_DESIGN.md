# ZE2B - ball-tool engagement in verify/zmap.py (design note, report-only)

Why: ZE2 (`_ae2_windows`, flat 2.5D semantics) divides the PLAN area of every removed cell by HORIZONTAL travel. On a
ball program that counts the whole spherical footprint and breaks on every Z change, so the T20 finish read ae_eff p50
17-93 mm, max 400+ (impossible for D 9.525). ZE2B replaces it for `--tool ball` only. Flat/bull output (ZE2 keys, JSON
bytes) must stay byte-identical; verify/ stays independent of engine/ (no engine imports).

## Per cutting-feed move (any direction), sampled every <= 0.25 mm of 3D travel
Against the zmap stock grid as it stands BEFORE the move is stamped (the same live stock zmap already keeps):
- ball surface over the footprint: z_b(d) = tip + R - sqrt(R^2 - d^2), d = horizontal distance to the axis, d <= R.
- removed depth per cell: r = stock_top - z_b, kept where r > 0.01 (engaged cells, each cell counted once per window).
- a = max removed height above the tip in the window = max(stock_top - tip), clipped to [0, R]; contact angle
  theta = acos(1 - a/R) (0 = tip only, 90 deg = equator).
- two engagement widths, both perpendicular to the HORIZONTAL travel direction u:
  * w_plan = extent of engaged cells projected on u-perp (radial contact width) - compared with the ball's chord at depth
    a: c(a) = 2*sqrt(a*(D - a)) for a <= R, else D;
  * ae_eq = removed volume per mm of 3D travel / a (the equivalent radial engagement: for a flat end mill it equals ae;
    for a ball side pass at stepover s it is ~s) - compared with James's load (T20: 1.905 steady, 2.286 spike).
- windows: consecutive cutting-feed moves (no rapid between, direction change <= AE2_DIR_MAX_DEG on u, ANY Z change
  allowed) merged to >= 1 mm of 3D travel, as ZE2's minimal-window rule. 3D travel is the divisor, so helices and
  ramps cannot blow up; windows whose horizontal travel is < 10% of the 3D travel are tagged `descent` (u undefined:
  w_plan = engaged-extent diameter) and excluded from the full-width flag - axial plunges stay ZB's job.
- flags: full_width = w_plan >= 0.9 * c(a) and a >= 0.05 (not descent); overload = ae_eq > --engage-max.

## Output (only when --tool ball and engagement tracking is on)
`engagement.ze2b`: {n_windows, full_width {count, length_mm, worst[10]}, overload {count, length_mm, worst[10]},
ae_eq {p50, p95, max}, w_plan_over_chord {p50, p95, max}, a {p50, max}, descent {count, length_mm}}, with the same
cutting-feed / entry-feed split ZE2F uses; `--ae2b-dump <json>` writes the windows (line, x, y, z, a, theta, w_plan,
c_a, ae_eq, length_3d, feed, descent). ZE2 keys stay as they are for every tool (flat byte-identical); for ball the ZE2
block is marked `"semantics": "flat-only, see ze2b"`.

## Tests (verify/test_zmap.py; analytic, D 9.525, cell 0.05 synthetic grids)
1. straight pass at a = 2.0 beside a cleared pass at stepover 1.905 -> ae_eq ~ 1.905 (+-5%), not full width
   (w_plan/c(a) ~ 0.62: contact from the scallop crest at -s/2 to the far chord edge);
2. full-width slot at a = 2.0 into flat stock -> w_plan ~ c(2.0) = 7.76, full_width flagged; ae_eq = segment area/a ~ 5.44;
3. 0.2 mm normal-thickness skim on a 45 deg slope -> not full width, not overload at 2.286;
4. 2 deg helix descent (r 3, 5 mm deep) -> finite ae_eq/w_plan, no window above D, descent windows tagged as such;
5. a flat-tool program: ZE2 JSON byte-identical to main's zmap (cmp of --out-json with/without the change);
6. mutation proof: with c(a) replaced by D (a broken chord formula), test 2/1 must fail by assertion (wrapper, no edit).

## Then
Report-only on the chain (rest-rough T20, finish T20, rest T33) by zone; the coordinator sets the rest-rough bar after.
Budget for the implementation: <= 150 non-test lines in verify/zmap.py.
