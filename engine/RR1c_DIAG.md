# RR1c diagnosis (supervisor, from 885ee43; no engine edits)

Method: read engine/rest_rough.py at 885ee43 and ran only the two failing tests under a scratch wrapper that captures
`rest_rough()`'s (moves, stats) and drop-cutter-checks every emitted segment at 0.1 mm against the exact part CL
(engine.finish batch_drop, ball 9.525).

## 1. test_rr1c_thin_band_inpass_ramp - "no moves emitted"
stats: zones 0; no_entry 1 (bbox x 18.5-21.5, y 8.3-31.7, r_max_cl 0.200); levels_unreachable [t 29.847, r_max_cl 0.2,
live depth 0.549]. The band's CL-legal region at its only level is a strip ~0.4 mm wide (1-2 cells of the 0.2 grid).
Three independent causes, each enough to emit nothing:
- **Step 2 is never tried at the zone's first entry.** The entry point p0 comes from the first `march_level` contour at
  c = ae/2 = 0.95 (rest_rough.py:506-511). The strip's max distance is 0.2 < 0.95, so there is no contour; p0 falls back to
  the single argmax cell (:512-515), `ux = uy = 0` (:516), and the in-pass ramp is gated on `abs(ux)+abs(uy) > 0.5`
  (:524). Step 1 then refuses (live depth 0.549 > shallow 0.25, :325). The ramp direction must come from the region's
  own long axis when p0 has no direction.
- **Step 3 (zig-zag) can never produce a run in a strip narrower than ae.** `zigzag_runs` (:142-183) places runs at
  lo + ae/2 ... hi - ae/2 across the short axis; for a 0.4 mm strip that range is empty, it appends hi - ae/2 (:155-156),
  which lies OUTSIDE the strip, so `sel` is empty and no run survives. Separately, for vertical runs (`horiz` False) it
  builds the run from `xs[g[0]] / xs[g[-1]]` (:173) although g indexes ROWS - it must be `ys`. Every vertical run is
  mis-placed (this bug is independent of width).
- **Even if entered, the level has nothing to cut.** Passes are contours of the distance transform at c = ae/2, ae/2+ae,
  ... (:597-607); with max distance 0.2 < ae/2 the ring list is empty. A strip narrower than ae needs a centre-line pass
  (the strip's medial line / the zig-zag run at the strip centre), not offset rings.

## 2. test_rr1c_narrow_pocket_side_entry - "gouge: 2 pts (worst 0.811)"
The only entry is step 4 ("SE2 side-entry d=5.0", live depth 0.126). The drop-cutter scan of the emitted moves finds
three segments below the exact CL, all from that entry:
- move 1: G1 descent at (13.2525, 12.1) from Z 32.0 to 27.05 - the exact CL there is 27.661 (0.611 deep);
- moves 2-3: the horizontal feed-in at Z 27.05 to (13.2525, 12.5) - 0.611, 0.235 deep.
Cause, file:line (step4, :376-410):
- the descent column at (sx, sy) is checked only for LIVE STOCK depth (:385-387) - never against the part. step1 and
  step2 call `cl_ok` (exact drop-cutter, :307-313) on their descent columns; step4 does not.
- along the feed-in, any point whose live stock is already cleared skips the part check altogether (`continue`, :394-395);
  only points standing in stock are tested, and then only with `legal` (:396), which reads the 0.2 mm grid CL `Zraw` at the
  nearest cell (:302-304) and misses walls between cell centres (the cl_ok docstring says so itself). "Cleared stock" is
  not "part-legal": the mouth here is next to the south frame wall, which the ball cannot get that low against.
Rule for the fix: every emitted move - descents, ramps, side entries, feed links - must pass the same exact CL check as
the passes (cl_ok / validate_exact-equivalent at <= 0.2 mm spacing), independent of the stock state.

## 3. Is the ladder structure sound?
Mostly yes: step1/step2/step4/helix are separate closures with a recorded step per entry, tried in the briefed order, and
a refused level is recorded and the next one up tried. Problems to fix or cut:
- The ladder is invoked in TWO places with different orders: zone entry (:522-549: 1, 2, 3, 4, 5) and per-pass links
  (:639-643: 1, 2, 4 only). Make it ONE function `enter(x, y, t, axis)` used by both.
- `legal()` (grid nearest-cell) is used for ramp interiors (step2 :361-363), helix points (:430) and floor circles (:581-582)
  while `cl_ok` is used only for vertical columns. Replace the per-point `legal` checks on EMITTED geometry by the exact
  check (batched drop-cutter per path, as validate_exact does); keep `legal` only for region building.
- Dead/redundant: `step2`'s two-direction wrapper is fine; nothing large is unused. The `mode`/`runs0` zig-zag hand-off
  (:528-546, and the li == 0 hand-off before the pass loop) only works when step 3 enters - it must also cover the thin-strip centre-line pass of finding 1.

## Order for the re-brief (RR1c-2)
1. thin band: direction for step 2 from the region's long axis when p0 has none; fix `zigzag_runs` (centre run for a
   strip narrower than ae; `ys` for vertical runs); centre-line pass when the region's max distance < ae/2 - the band must
   actually be cut and the test pass unchanged.
2. side entry: exact CL check on the step-4 descent column and on every feed-in point (no stock-based skip) - 0 gouge pts.
3. the 7 Core Front rapid collisions (out/rr1b/zmap_rest.json at RR1b).
Then stop for the supervisor's CF chain judge.
