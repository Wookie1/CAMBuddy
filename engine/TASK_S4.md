# Round S4 (finishing): flute/shank-aware passes and James's tools. Do not commit; probes in engine/probe_*.py.
James's tools (tools/x7_tools.json, source "James 2026-10-18"): ball 6.0, 9.525 (3/8), 19.05, 12.7, 3.175 (1/8),
1.5875, 0.79375 mm; flute = 2.5 x D; shank dia = D (assumed, not necked). Core Front walls are ~22 mm deep.
1. finish reads flute/shank from the tool table by diameter (CLI --flute/--shank override). Shank safety per CL
   point: drop-cutter a CylCutter(shank_dia) at that XY; if its CL (the cylinder bottom) > tip_z + flute - 0.01 the
   shank would touch the part -> drop the point (split + verified relink, same nets). With --stock-from, also
   require the stock top within shank radius <= tip_z + flute. Count and report removed points per level and the
   removed wall area; never move points down.
2. Rest pass tool: --rest-tool ball:3.175 (1/8 in, from the table); the placeholder marker stays only for tools
   not in the table. Rest mask from the previous finish tool's CL vs the rest tool's CL (> 0.5 mm), and the same
   shank rule (7.9 mm flute) - report which rest cells are reachable cleanly and which are blocked by the shank.
3. Tests: deep wall (22 mm) + D=6 F=15: points deeper than the flute next to the wall are dropped, probe_clcheck 0;
   same wall with D=9.525 F=23.8: kept. Keep all existing finish tests green.
Do NOT run the full part (the supervisor does). Short outputs.
