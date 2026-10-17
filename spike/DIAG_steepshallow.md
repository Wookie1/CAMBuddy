# Diagnosis: SteepShallow finish gouging on the outer rim (round 3, out/core_front_finish.ngc)

Round-3 sim: 2411 gouge cells @0.5 mm grid, max depth 10.69 mm at (-114.615, 56.900),
gouge bbox X[-126.1,125.9] Y[-68.1,65.9] — a ring following the whole outer rim wall.

## 1a. Point table (spike/probe_diag_steepshallow.py, freecadcmd)

20 deepest gouge cells. `oclCL` = correct 6 mm ball tip Z from ocl.BatchDropCutter,
BallCutter(6.0 full-diameter arg, 50) on an STL of core_front_setup.step tessellated at
0.01 mm (55702 facets, bbox Z[-0.000, 46.844]). `pathZ` = lowest Z of any
core_front_finish.ngc move passing within 0.25 mm XY (line = that move). `hf01` = 0.1 mm
part heightfield Z at the cell.

| X | Y | oclCL tip Z | pathZ @0.25mm | hf01 part Z | ngc line |
|---|---|---|---|---|---|
| -114.615 | 56.900 | 41.425 | 41.311 | 38.719 | 369215 |
| 105.885 | 41.400 | 41.428 | 41.444 | 38.740 | 28577 |
| 116.385 | 47.900 | 41.417 | 41.368 | 38.546 | 353727 |
| -72.615 | 34.400 | 46.650 | 46.568 | 38.012 | 330575 |
| -68.615 | 34.400 | 46.643 | 46.562 | 37.992 | 330584 |
| -69.115 | 34.400 | 46.654 | 46.578 | 38.028 | 330583 |
| -104.615 | 59.900 | 41.438 | 41.290 | 38.852 | 374425 |
| -112.615 | 42.900 | 41.425 | 41.437 | 38.701 | 345028 |
| -106.115 | 41.400 | 41.451 | 41.444 | 38.939 | 27796 |
| -72.115 | 34.400 | 46.658 | 46.581 | 38.035 | 330576 |
| -108.615 | 41.400 | 41.442 | 41.444 | 38.869 | 27791 |
| -110.615 | 41.900 | 41.438 | 41.293 | 38.850 | 342959 |
| -110.115 | 59.900 | 41.416 | 41.269 | 38.558 | 374414 |
| -99.615 | 56.400 | 41.418 | 41.219 | 38.563 | 368208 |
| -98.115 | 48.400 | 41.427 | 41.215 | 38.757 | 354336 |
| -69.615 | 34.400 | 46.661 | 46.582 | 38.040 | 330582 |
| 104.885 | 59.900 | 41.496 | 41.358 | 39.135 | 374844 |
| -4.615 | -44.600 | 41.452 | 41.389 | 38.917 | 193833 |
| 103.385 | 59.400 | 41.466 | 41.424 | 39.020 | 373803 |
| 109.885 | 59.900 | 41.466 | 41.325 | 39.021 | 374854 |

Within 0.25 mm of the gouge cells themselves the path is ON the correct CL
(|oclCL - pathZ| <= 0.16 mm). The deep cutting that gouges these cells arrives from
**adjacent constant-Z steep contours within ball radius (<= 3 mm)**:

- Worst cell (-114.615, 56.900): part solid Z[0, 39.87] (column boolean), hf01 = 38.72.
  Steep contour at **Z = 25.244** passes through (-116.878, 58.860), 3.0 mm away
  (ngc lines 130978-130990, all G1 at constant Z 25.244) -> ball grazes the cell to
  stock 28.025 = depth 10.69 mm.  [spike/probe_engine_grid.py]
- At that contour point the correct drop-cutter CL is **35.545** (BallCutter(6, h) for
  h = 3/6/20/50 all agree — spike/probe_cutter_len.py). The engine drove the tip
  **10.3 mm below the gouge-free CL.**

## Engine-grid reconstruction (why the contour is there)

Reconstructed SteepShallow's own sampling grid (SampleInterval 0.5 mm, model bbox
+3 mm margin, n_x=519/n_y=293, STL @0.05 mm, BallCutter(6,·)) around the contour:
CL node values jump from **24.765 (floor reachable)** to **35.5-37.4 (ball caught on the
rim top edge)** between nodes only 0.5 mm apart — the floor beside the rim is a slot
narrower than the 6 mm ball, so the true CL surface has a ~11 mm step discontinuity
along the slot mouth (locus of points at distance = R from the rim edge).
Marching-squares places the iso-crossing for level 25.244 at
t = (25.244-24.765)/(35.5-24.765) ≈ 0.04 from the low node — i.e. ~20 um INSIDE the
catch shadow where the true CL is already 35.5+. The contour then walks the rim at that
too-low constant Z, intruding at many edges -> the full-perimeter gouge ring.

## 1b. Input checks

- Tool controller tc2: `Ballend` bit, Diameter 6.0 mm, shape Ballend — matches zmap
  `--tool ball --dia 6` used in out/zmap_setup_finish.json. No shape/diameter mismatch.
- Stock-to-leave: SteepShallow op has NO StockToLeave/ZStockToLeave property at all
  (property dump of out/core_front_job.FCStd); nothing negative. (Adaptive ops had
  StockToLeave +0.3, positive.)
- BoundaryOverlap = 1.0 mm (default 0.5; only dilates the shallow mask into steep —
  cannot produce points below the CL surface). **BoundaryAdjustment: property does not
  exist** in this SteepShallow implementation. Boundary shape: generator uses the raw
  job-model bbox + tool radius margin; no custom boundary.
- StartDepth = 61.96 (stock top 60.96 + 1): the generator IGNORES StartDepth — steep
  levels start at max(hf) ≈ 47.14, not StartDepth (steep_shallow.py: `level = z_max -
  stepdown`). It contributes nothing but rapids in air; not the gouge cause.
- SlopeThreshold = 45 deg: standard; classification only.
- Steep vs shallow: the gouging moves are constant-Z staircase polylines (e.g. lines
  130978+ at Z 25.244, emitted before the surface-following rows) = **steep passes**.
  The shallow passes (lines ~368k+, Z varying along X rows) track the CL within 0.15 mm.

## 1c. Conclusion — ENGINE BUG (stop; no tuning)

The steep (waterline) branch of Path.Base.Generator.steep_shallow interpolates
iso-crossings linearly between heightfield nodes. Where the CL surface is discontinuous
— unavoidable at slot mouths narrower than the cutter, here the ~3 mm gap between the
outer rim wall and the plateau above the Z 24.76 floor — linear interpolation places
contour points inside the overhang shadow, up to ~half a sample interval in XY and up
to ~10.3 mm in Z below the true gouge-free CL, all around the rim. The generator's
"gouge-free by construction" claim holds only for CL surfaces without step
discontinuities. No setup property causes it: StartDepth is unused, BoundaryOverlap only
affects mask dilation, there is no stock-to-leave, tool definition matches the sim, and
lowering FinalDepth would not remove it (any level between floor+0.3 and rim top
produces the same mis-placed crossings at the shadow). Fix requires the engine to
re-project steep-pass points against the drop-cutter surface (or exclude crossings whose
verified CL exceeds the level) — out of scope per task ("if it is the engine, STOP").
