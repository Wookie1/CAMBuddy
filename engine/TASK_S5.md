# Round S5 (safety): real tool data + holder clearance. Do not commit; probes in engine/probe_*.py.
HARD RULES: no git stash/reset/clean/restore/checkout of files. No bypass flags, no exempted cells, no relaxed tests.
Data: tools/x7_tools.json now holds James's real tools (source "James's STEVE tool library (My shop rev 24)"):
T31 6 mm ball D 5.958 flute 12 shank 5.958 stick-out 18 holder BT30-ER20-60; T20 3/8 in D 9.525 flute 22.225 shank 9.525
stick-out 46.2 holder BT30-ER20-60; T33 1/8 in D 3.142 flute 6.35 shank 3.142 stick-out 20.8 holder BT30-ER20-80;
"necked": false (when true, shank_diameter_mm is the neck diameter). "holders" gives each holder as frustum segments
[z_lo, z_hi, r_lo, r_hi] above the holder NOSE, which sits at tool tip + stick-out.
James's rule (keep it, it is what S4 does): no vertical wall deeper than flute length unless the shank is reduced.
1. engine/finish.py: read stick-out + holder from the table by diameter (CLI overrides --stickout/--holder). Shank
   check = the existing S4 rule, unchanged (incl. tangent-touch), now applied to the shank from tip + flute up to tip +
   stick-out. HOLDER check: the holder solid (frustum stack starting at tip + stick-out) must stay >= 1.0 mm from the
   part (and the --stock-from stock): drop the point, never lower it; split + verified relink like the other nets.
   Implement with batched OCL drop-cutter (e.g. one CylCutter/ConeCutter per segment offset in Z, or a conservative
   cylinder of each segment's max radius + 1 mm) - document which; conservative is fine. Report dropped points split
   by shank vs holder in stats.
2. verify/zmap.py: independent holder-hit count (numpy only, never import engine code): read tools/x7_tools.json
   (--tool-number N or --holder NAME --stickout S), and for every cutting sample check the holder frustum stack against
   max(stock, part) with the 1.0 mm clearance; report holder_hits {count, max_intrusion, worst_xy, first_line}.
3. connector/runner.py: pass the tool number to zmap and FAIL the run when holder_hits > 0 (alongside gouges, rapid
   collisions, shank/over-flute, clcheck). Mock-STEVE test with a deliberate holder hit -> failed, no .nc.
4. Tests: holder hit (synthetic tall boss beside a deep pocket so the holder, not the shank, touches) dropped in
   finish and counted by zmap; real-flute case: T31 (flute 12) next to a vertical wall 13 mm deep -> those points dropped.
Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q and the VibeCAD-python engine
suites (engine/test_engine.py, engine/test_finish.py). Do NOT run Core Front; the supervisor does.

## Supervisor note (relaunch)
A previous S5 session already changed 7 files (+735 lines: connector/runner.py, connector/test_connector.py,
engine/cli.py, engine/finish.py, engine/test_finish.py, verify/test_zmap.py, verify/zmap.py) and exited; its log was lost.
Check git diff first, keep that work, run all the test suites listed above, and finish whatever is missing or failing.
