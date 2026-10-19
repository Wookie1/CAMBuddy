# SteveCAM connector — plain words for James

The connector runs SteveCAM on this Mac for STEVE. You send in a STEP
model; you get back a checked LNC program for the X7, plus a report and a
leftover preview picture.

**Nothing is ever sent to the machine.** Every program still needs your
graphics check and a dry run above the part on the X7 before it cuts
anything.

## The two actions

- **adaptive_rough** — constant-engagement roughing with a flat or bull end
  mill. It cuts level by level, keeps the side load about the same on every
  pass (the "optimal load"), and leaves a skin of stock (the "leave") for
  finishing. When big levels leave material in corners, rest passes step back
  up in small cuts (about the "stepup" distance) to clean out any leftover
  deeper than half a millimetre.

- **slope_split_finish** — ball-end finishing split by how steep the surface
  is (default split: 40 degrees). Steep walls get contour-style passes
  (waterline, one level per "stepdown"); flatter areas get raster-style
  back-and-forth passes ("stepover" between rows). The steep pass reaches a
  few degrees down into the flat zone so the two meet overlapped, not gapped.
  It runs adaptive roughing first — a finishing ball must never meet raw
  stock — and gives you both programs: rough.nc and finish.nc. Run finish.nc
  only after roughing.

## The gates — a run fails if any of these catch something

- **Gouges** — the simulated tool cuts into the part where the model says it
  shouldn't. What to do: look at the flagged spots in check.json and
  preview.png; usually the orientation, a tool too big for the features, or
  a stepdown that is too deep. Fix and rerun.

- **Rapid collisions** — a G0 (rapid) move hits stock or the finished part.
  What to do: check floor Z and the stock sizes, and look at the first
  offending line in check.json. Fix and rerun.

- **Shank / over-flute** — a wall is deeper than the tool's flutes, so the
  non-cutting shank rubs the wall. Vertical walls deeper than the flute
  length are refused unless the tool has a reduced neck in the tool table.
  What to do: use a longer-flute or reduced-neck tool from
  tools/x7_tools.json, or split the depth differently.

- **Holder hits / holder unknown** — the collet nut or holder would come
  within 1.0 mm of material, or the tool has no known holder outline and
  stick-out in tools/x7_tools.json. A tool with no known holder is never
  run — the clearance cannot be judged, so the run fails. What to do: add
  the holder and stick-out to the tool table, use more stick-out, or pick a
  shorter holder.

- **clcheck** (finishing runs) — an exact drop-cutter check of the posted
  finish program: no point may cut below the tool path by more than
  0.005 mm. This is the final gouge judge for finish.nc; if it reports any
  hits the run fails. What to do: check the ball diameter and tool number
  against the X7 table and rerun.

## Warnings — reported, never a fail

- **Engagement** — cutting moves where the side bite is more than 1.2x the
  optimal load (roughing, e.g. 2.438 mm for an optimal load of 2.032) or
  1.5x the stepover (finishing). Review them; they can chatter or load the
  tool heavily.

- **Plunge** — descending feed moves straight into stock that are not a
  shallow helix/ramp (3 degrees or less). Steep entries are hard on the
  tool; check them before running.

## What a run gives you

rough.nc (and finish.nc for the slope-split job), check.json with the gate
numbers, and preview.png showing leftover material. Read the report, open the
program in the X7 graphics, and dry-run it above the part before cutting.
