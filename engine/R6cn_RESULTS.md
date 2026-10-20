# R6c-n results — STOP (diameter matching alone does not reach the target)

Change: ONE helix entry diameter `helix_dia = 0.8 * 2 * tool_r = 10.1488 mm`
(reported in stats as `helix_dia_mm`) now feeds `a2d.helixRampTargetDiameter`
AND `a2d.helixRampMinDiameter` AND `_helix_moves` (fixed radius = helix_dia/2
about Adaptive2d's HelixCenterPoint, one full circle at depth; straight feed at
depth onto the region start point only when the live stock model says the bore
is cleared, else retract + straight plunge as before). Engine diff: 45(+)/11(-)
lines in engine/rough.py. No post-pass; nothing after Adaptive2d was edited,
converted or replayed beyond the entry generation itself.

Measurement note: out/test_block_hf_0.1.npy was regenerated with
verify/heightfield.py STOCK_BOX mode (grid now covers stock + tool_r + 5 mm,
pad ~11.35 mm) because the committed tight grid flagged every wall pass as
outside_grid (RS lets centres cross stock faces by tool_r) and zmap refused to
judge. Same padded grid used before AND after.

## zmap (--engage-max 2.438, flat D12.686, stock -50 50 -40 40 0 38)

| metric            | before          | after           |
|-------------------|-----------------|-----------------|
| horizontal p50    | 2.1116          | 2.1060          |
| horizontal p95    | 3.0045          | 2.9211          |
| horizontal p99    | **8.4459**      | **8.5000**      |
| horizontal max    | 12.686          | 12.686          |
| entry n           | 430             | 226             |
| entry p50/p95/p99/max | 12.686 all | 12.686 all    |
| engage count >thr | 2400            | 2032            |
| gouges            | 0               | 0               |
| rapid collisions  | 0               | 0               |
| outside_grid      | 0               | 0               |

Target horizontal p99 <= 2.438 NOT met (8.50).

## Why the bore match is not enough (diagnosis of the measurement)

1821 horizontal spikes; 1673 at Z=20.381 (final level, first level 35.381:
43; 27.381: 85; 30.381: 20). The worst horizontal moves are the one-full-circle
at depth and the first loops right after it: with z_top = min(clearance, z+stepdown)
the helix pitch is fixed by the FULL 19.05 mm drop (turns ~3.4, pitch ~5.6 mm),
but most of that drop is in air — the stock surface at those XYs is only ~7 mm
above the level. So the cutting part of the descent is ~1.2 turns and leaves
uncut steps up to ~5.6 mm high ahead of the depth circle; zmap then sees
full-width radial engagement (12.686) on the depth circle and on every loop
that crosses those steps, even though the bore centre/diameter now match what
Adaptive2d assumed. Entry (descending) engagement is likewise full width: the
ramp cuts into solid stock at that pitch.

Per the task rule ("If matching the diameter alone does NOT get there, STOP and
report the numbers - do not add workarounds") no further changes were made.
Coverage is unchanged by the fix: zmap leftover max/mean/p95 and within-0.5mm
fraction are identical before/after (leftover max 15.381 pre-existing); a2d
returns one fewer tiny region at Z=33.716 (Min=target now forces the full
10.15 mm ramp circle) with no leftover difference. Not committed. Engine suites
green: test_engine.py 0 failures, test_finish.py ALL PASSED.
