# Task A: independent toolpath checker (verify/zmap.py)

Plain Python 3 + numpy, NO FreeCAD import in zmap.py. Keep it solid and small. Work only in this folder.
Run with /opt/homebrew/bin/python3 (has numpy 2.4 + pytest; no matplotlib). VibeCAD's bundled python
(/Applications/VibeCAD.app/Contents/Resources/bin/python) has numpy + matplotlib if you want the PNG.

## Files
- verify/heightfield.py — run under /Applications/VibeCAD.app/Contents/Resources/bin/freecadcmd.
  Loads a STEP (Part.read), tessellates at 0.05 mm (shape.tessellate(0.05)), rasterizes triangles top-down
  into a max-Z grid, cell 0.5 mm (configurable). Cells with no part = part bottom Z. Writes .npy plus a small
  .json sidecar with origin x0,y0, cell size, shape. Args via sys.argv or env vars (STEP_IN, HF_OUT, CELL).
- verify/zmap.py — CLI: gcode file, tool (--tool flat|ball|bull --dia D --corner R), stock box
  (--stock xmin xmax ymin ymax zmin zmax), part heightfield .npy (+ sidecar), --out-json, --png (optional).
- verify/test_zmap.py — pytest, synthetic only, no FreeCAD.

## G-code parsing
G0/G1/G2/G3 (I/J arcs, XY plane, G17), G20/G21 units (convert to mm), G90 absolute, modal motion and coords.
Ignore comments ( ... ) and ; ..., N numbers, and other words (F S T M H D G43 G54 etc). Track line numbers.

## Simulation
Stock heightfield starts at stock top (same grid as the part). For each cutting move (G1/G2/G3), sample along
the move at <= cell/4 spacing; at each sample lower the stock cells under the tool footprint using the tool's
lower-surface profile: flat = disk at tip Z; ball radius R: z(r) = tip + R - sqrt(R^2 - r^2); bull: flat center
out to (D/2 - r), then a torus of radius r. The tip Z is the lowest point of the tool. Vectorize with numpy
(precompute the tool kernel offset grid once). G0 moves that would cut stock are rapid collisions
(count + first line number), but still apply them.

## Report (JSON)
- gouges: cells where final stock < part height - 0.02 mm: count, max depth, XY of worst.
- leftover: final stock - part, max/mean/p95, over cells where the part top surface is reachable from above
  (cells inside the part footprint; exclude cells outside the stock box).
- rapid_collisions: count, first line number.
- air_fraction: fraction of cutting length where the tool removes no material.
- Optional PNG heatmap of leftover stock (skip cleanly if matplotlib missing).

## Tests (verify/test_zmap.py), must pass with `/opt/homebrew/bin/python3 -m pytest verify -q`
1. Straight flat-mill line cuts a groove of exactly its width and depth (within one cell).
2. Ball-mill line leaves the right cross-section profile (compare to the analytical circle; and two parallel
   passes at stepover s leave cusp height h = R - sqrt(R^2 - (s/2)^2)).
3. A G2/G3 arc groove matches its analytical radius.
4. A deliberate gouge (path below a synthetic part) is detected; a clean path reports zero gouges.
5. A G0 through stock is counted as a rapid collision with the right line number. G20 input scales to mm.

Workflow: write the code first, run the tests, fix from failures. Then run heightfield.py on
samples/core_front.step to out/core_front_hf.npy and print its shape, min, max as a smoke test.
