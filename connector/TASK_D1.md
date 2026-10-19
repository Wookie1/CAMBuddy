# Task D1: plain-language connector README and panel text. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase. TEXT ONLY: no logic, gate, parameter-name, default or
test changes. You may edit only connector/README.md (create it), the visible text in connector/panel/index.html and
connector/panel/panel.js (labels, help strings, messages - not ids, keys or logic), and "description" string values in
connector/catalog.py. Never write the words "Fusion" or "Steep & Shallow" / "Steep and Shallow" anywhere.
Read connector/catalog.py, connector/runner.py (_check_zmap_gates and the run steps) and the panel files first, so
every statement is true of the code. Then write, for James (a machinist, not a programmer):
1. README.md: what the connector is (runs SteveCAM on this Mac for STEVE; STEP in, checked LNC program out).
   The two actions in plain words:
   - adaptive_rough: constant-engagement roughing with a flat/bull end mill, level by level, leaving stock allowance.
   - slope_split_finish: ball-end finishing split by surface slope: contour-style passes on steep walls, raster-style on
     flatter areas, overlapping where they meet; plus what rest passes are if the code has them.
   Each gate a run must pass, what it means and what to do when it fails: gouges (tool cuts into the part), rapid
   collisions (a G0 move hits stock or part), shank / over-flute (non-cutting shank or a wall deeper than the flutes
   rubs; vertical walls deeper than flute length are refused unless the tool has a reduced neck), holder hits / holder
   unknown (collet nut or holder hits; a tool with no known holder outline is never run), clcheck (exact drop-cutter
   check of the posted program, the final gouge judge), engagement and plunge warnings (report-only: moves over 1.2x
   the optimal load, steep entries).
   State plainly: nothing is sent to the machine; every program needs James's graphics check / dry run above the part
   on the X7 before cutting.
2. Panel: the same descriptions, short (one line per action and per gate) where the panel shows actions/results.
Keep it short and accurate; no marketing words. Run /opt/homebrew/bin/python3 -m pytest connector -q (must still pass).
