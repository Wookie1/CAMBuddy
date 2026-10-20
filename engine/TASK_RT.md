# Task RT: roughing travel - no feed plunges through air, minimal retracts, no axial plunging into stock. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do not edit
verify/ gate logic (a new REPORT-only count in verify/zmap.py is allowed, see 3); keep programmed engagement = optimal
load (no derate). zmap stays the judge.
Supervisor's diagnosis (Core Front, T13 flat 12.686, connector adaptive_rough, real blank X+-128.651 Y+-82.55 Z0..60.96,
floor 24.765, stepdown 19.05, optimal 2.032): 77 min vs round 7's 27.8 min. Straight plunges at ramp feed 2,966 /
43.8 m / 34.5 min (median 15.7 mm, mostly through air: zmap air fraction 48%, only 852 touch stock); rapids 113.6 m /
22.7 min (vs 38.2 m); 1,107 retracts / 1,511 not-clear links; 290 regions / 78,475 clip breaks (round 7: 14 / 3,626).
Helix entries are only 0.7 min - not the cause.
0. FIRST, before changing anything: classify the straight feed-down moves of the current Core Front rough (run it with
   the command above via engine.cli rough; reuse its output): for each, does it remove material UNDER the tool
   footprint (axial plunge: stock above the move's end Z within the flat bottom disk) or only brush walls at the bottom?
   Write the counts (axial / wall-only / air) to engine/RT_BEFORE.md.
1. After a retract, descend with G0 to a verified-clear height = max(part, remaining stock) within tool radius + 1 mm
   along the descent (use the existing R5 rapid-clear check), then feed only the remaining stretch.
2. Retract only to the minimum verified-clear height over the link (like engine/finish.py link_plan), never to full
   clearance unless needed.
3. Axial plunging into stock is forbidden: a straight feed-down may only enter material already cleared under the
   footprint; anything that would cut stock axially must be a helix/ramp entry. Enforce in the engine (stats
   n_axial_plunge must be 0) AND add a report-only zmap count "axial_plunges" (feed-down moves removing stock under
   the flat bottom disk) - report-only, no new gate.
4. stats: regions and clip breaks per level.
Acceptance (supervisor re-runs): Core Front as above and the test block (TASK_R6 command): plunge time < 5 min on Core
Front, rapids <= 1.5 x round 7 (<= 57 m), all zmap gates 0, axial_plunges 0 (engine and zmap), engine suites
(VibeCAD python engine/test_engine.py, engine/test_finish.py) and /opt/homebrew/bin/python3 -m pytest verify connector
engine/test_post.py -q green. Before/after table in engine/RT_RESULTS.md. Run heavy jobs in the FOREGROUND.
