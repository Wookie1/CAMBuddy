# FE5d results — the line-52593 entry WAS ramped; the violation is the vertical link plunge onto the ramp top

Diagnosed from files only (no engine/zmap runs; scripts in out/fe5d_diag*.py).

## What the NC actually contains (out/fe5_finish.nc)
- 52591 retract Z46.72 at prev-pass end (-28.73,17.89,41.444); 52592 G0 to (-8.677,17.193);
  52593 **vertical G1 plunge** dz=4.575 to Z42.145 (90 deg — this is the move ZB flags, depth 2.826);
  52594–52607 a **correct 2.0-deg backward ramp** (dz/dxy = 0.173/5.0 per step, 5mm chords)
  descending from (-8.677,17.193,42.145) to the pass start P0 = (-28.57,17.89,41.444);
  52608+ the pass runs forward at z=41.444, 61.7 mm, to (32.47,17.19).
- So: ramp emitted, on the right run, at exactly 2 deg (never steeper than MAX_RAMP_DEG=15,
  engine/entry_depth.py:24). The violation is the **vertical plunge onto the ramp's top point rv[0]**.

## Why (file:line)
- finish.py sizes the ramp from live depth at the pass's P0 only: d = live.disk_depth(P[0])
  (engine/finish.py:2192), L = d/tan (finish.py:2201), ramp z = max(CL, z0 + s*tan)
  (engine/finish.py:1792–1812). It never checks stock height at the ramp TOP / along the chord.
- At P0=(-28.57,17.89,41.444) the live stock depth is only d=0.701–0.719 mm (replayed from
  out/fe5_stock_01.npy) -> L = 20.1–20.6 mm. finish.py DID ramp this pass:
  out/fe5_finish_stats.json fe5_deep_ramped contains [-28.575, 17.887, 41.444, 0.701, 56.58]
  (full ramp: total 56.58 >= L; that is why fe5_deep_unramped = []).
- But rv[0] lands 20.1 mm along the pass at (-8.677,17.193), z = 41.444+20.1*tan(2) = 42.145,
  where the live stock is ~45.03 (ball-engaged ridge cell 45.72 at (-8.69,19.71), 2.5 mm +Y):
  disk_depth there = 2.888 mm (matches ZB's 2.826 and out/fe5_est_finish_ramped_entries.json
  line 52593 depth_mm 2.8879). The ramp top is ~2.9 mm BELOW the local stock surface.
- The rapid link then plunges vertically at path[0] = rv[0] straight down to 42.145
  (engine/finish.py:2419–2422 emit(1, path[0][0], path[0][1], path[0][2], ramp_feed)) —
  a 90-deg entry engaging the ridge by ~2.9 mm. The stock under the plunge axis is 40.29
  (tip clears); the engagement is the ball SIDE against the bay wall along y ~19.7–22.
- Why the ridge stands there: the previous serpentine pass was cut short at x=-28.73 (shank net,
  stats n_shank_removed=9886), so nothing before this Z-level cleared the wall foot near x=-8.7.

## Estimator / measurement questions
- Did the estimator flag it? YES: out/fe5_est_finish_ramped_entries.json line 52593, depth 2.888
  (> 0.25), already printed in out/t_est5.log ("deep: {line 52593 ...}"). Its "deep" field is
  inf-only fail-closed (engine/entry_depth.py:350), so deep=False there is not a pass verdict.
  The unramped-program file out/fe5_est_finish_entries.json (built on fe2_finish.nc by
  out/fe5_proof.py:61–69) has no matching XY — different program, not comparable.
- Run measured differently? YES: supervisor's 81.6 mm contiguous run = XY length of the merged
  segment lines 52593–52648 (20 mm ramp-back + 61.7 mm forward). finish.py's total = stored-pass
  XY length 56.58 mm (stats) and its L = d(P0)/tan = 20.1 mm — sized by the depth at P0
  (0.70), not the plunge-XY depth ZB measures (2.83 -> needed height 3.59 mm -> L >= ~103 mm
  > any run available). The entry could not be fixed by a longer ramp on this pass: rv[0]'s
  required top is above the stock at the plunge XY, which z0 + s*tan anchored at P0 cannot reach
  while staying CL-safe (the pass CL there is already at 41.444).

## Verdict
Not "skipped", not "too steep": emitted on the right run, but the ramp height is anchored at
P0's depth (0.70 mm) while ZB scores the vertical link plunge at rv[0], 20 mm earlier, where
stock stands ~2.9 mm above the ramp top. The unguarded vertical plunge at finish.py:2422 onto
a buried rv[0] is the defect. (Diagnosis only — no fix made, per task.)
