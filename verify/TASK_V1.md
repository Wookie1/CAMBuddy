# Task V1: engagement-spike and plunge reports (verify/ + connector check.json). REPORT-ONLY. Do not commit.
Rules: no MCP, no questions, never contact the internet, probes in verify/probe_*.py. verify/ must stay numpy-only
and independent of engine/ (never import engine or ocl). No bypass switches, never weaken existing tests.
1. In verify/zmap.py (or a new verify/engagement.py used by zmap): for every cutting move, radial engagement against
   the LIVE simulated stock = width of material the tool footprint removes measured perpendicular to the direction
   of travel (or the engaged arc angle converted to an equivalent radial width; document which). Record per-move
   max engagement and where. Flag moves over a threshold (--engage-max mm; default 1.5 x --optimal-load if given,
   else off) with line numbers and XY; summary: count, max, top 10 spots (line, XY, mm).
2. Plunge flag: a feed move with a downward Z component that enters stock (removes material while descending) is
   flagged unless it is a helix/ramp at or under --ramp-angle (deg, default 3.0): report line numbers, XY, angle,
   depth into stock. Rapids that end inside stock are already rapid collisions - just cross-reference them.
3. Tests (synthetic): straight full-width slot -> engagement = D, flagged; 90-degree inside corner of a constant
   radial-engagement path -> spike flagged at the corner; helix entry at 2 deg -> not flagged; straight vertical
   plunge into stock -> flagged. Keep all existing verify tests passing: /opt/homebrew/bin/python3 -m pytest verify -q.
4. Connector: add both reports to check.json under "warnings" (never fail a run on them). Keep connector tests
   passing: /opt/homebrew/bin/python3 -m pytest connector -q.
Do NOT run Core Front or the test block; the supervisor does. Short outputs.
