# RR1c-3 diagnosis (supervisor; from e206c56, no engine edits)

Data: the supervisor's chain judge on the current Core Front part (scratchpad chain/: rest-rough rr.nc + stats, fe5 zmap
with raw axial lists) and a probe (scratchpad rr1c3/probe.py: rest-rough limited to the two X+-71 bays and the two flank
bands, with march_level / zigzag_runs call capture, cut moves per Z, and the FE5 LiveStock stamped with the probe's moves
to read the depth left at the finish's bay entries). The three through-bores (centre-south, corners) are OUT of scope
until James decides.

## (a) Flank bands (and small zones): an entry is recorded but 0 levels are cut
Zone stats: both flank bands (~2,284 mm2) `entry_steps [4]`, `levels 0`, `floor_tip_z 47.0`; same for most small zones.
On these sloped walls every level region is a strip 1-2 cells wide that follows the curved contour (max distance 0.2):
- rings: `march_level` at c = ae/2 = 0.9525 (rest_rough.py:614-627) finds 0 contours (max distance 0.2 < 0.95) - probe:
  (maxDz 0.2, c 0.9525, 0 contours) on every flank level;
- the centre-line fallback `zigzag_runs(reg, xs, ys, ae, 2 * CELL)` (:638) lays AXIS-ALIGNED rows across the band's bbox;
  each row crosses the curved strip in 1-2 cells, groups of < 2 cells are dropped and 2-cell groups (0.2 mm) are below
  min_run 0.4 - probe: (28 cells -> 0 runs), (27 cells -> 0 runs). No path, so `cut_here` stays 0 and the level counts 0.
- the synthetic thin-band test passes because its band is straight and axis-aligned.
- T33's two remaining ZB (both 0.528, at (-62.27, -16.45) and (79.24, -16.45)) sit inside the flank bands: same cause.
Fix: cut a thin level strip ALONG ITS OWN CENTRE LINE - e.g. the contour of the distance field at c = max(maxDz/2,
CELL/2) when maxDz < ae/2 (march_level already returns ordered polylines for a curved strip), every point CL-checked like
the passes. Zig-zag stays as briefed (each run >= D); it is not the tool for curved strips.

## (b) Bays: 0.83-1.52 mm left at the finish's entry XYs although the leave is 0.2
Probe, bay zones (r_max_cl 2.433): levels at t 36.365 (the floor-hugging level), 36.965, 38.965 (2.0 step).
- `levels_unreachable`: t 36.365 (r_max 0.2, live depth 3.924) and t 36.965 (r_max 0.4, live depth 3.323) for BOTH bays -
  the deepest levels are a narrow groove, steps 1-5 all refuse at ~3.3-3.9 mm of live depth.
- the zone is then entered at t 38.965 (helix r 1.946, step 5), and the pass loop runs `levels[li0:]` (rest_rough.py:614)
  - i.e. only the entered level AND THE ONES ABOVE IT. The two deeper levels are never revisited after 38.965 is cleared.
  Cut moves per Z in the probe: only Z 38.965 (132 G1 at cut feed).
- result at the finish entries (LiveStock after the probe, ball disk): (-71.21, -1.21, Z 38.145) 0.825; (70.30, -1.21)
  0.828; (+-71, -0.91, Z 37.85) 1.17; (+-71, -0.61, Z 37.55) 1.52 - live top 38.97-39.07 = the 38.965 level. Not reach,
  not leave: one cut level, the deeper ones skipped. (zmap on the full chain read 0.825/0.827/0.51/0.51 at the finish's
  own entries, the finish's earlier passes having cut part of it.)
Fix: cut levels TOP-DOWN after the zone is entered - enter at the highest level that the ladder can enter, then step
down level by level; each deeper level is re-tried through the ladder from the level just cleared (its live depth is then
~ one stepdown, <= 2.0, instead of 3.3-3.9) and, being thin (r_max 0.2-0.4), cut with the centre-line pass of (a).
Target: every finish-entry footprint in the bays <= 0.5 live depth; the clean target is the 0.2 leave.

## (c) T33 rest ZB 2 (max 0.528)
line 53335 (-62.265, -16.450) 0.528 and line 53344 (79.235, -16.450) 0.528 - both inside the flank bands (bbox
x -104.5..-37.3 / 36.3..103.3, y -33.4..33.6). Root cause (a): the T20 rest-rough cut nothing there, the finish leaves
its scallop, and the T33 rest enters it.
