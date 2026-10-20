# Task RT2a: helixes and ramps honor the ramp angle (default 2 deg). Do not commit. SMALL: under ~60 lines.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do not edit
verify/; no post-pass. Judge = verify/zmap.py exit code + JSON only (command in engine/TASK_RT2.md).
Supervisor measured RT2's output (arc length for helical arcs): Core Front - 0 descents at <= 2.05 deg, 18,774 segments
at 5-15 deg (15.9 min), 6 > 15 deg; test block - 0 at <= 2.05, 2,039 at 5-15. RT2's pitch cap (~14 deg) is the judge's
limit, not the ramp angle. The ramp angle is the parameter the generator must honor.
1. --ramp-angle-deg (default 2.0; clamp [0.5, 15]; <= 0 rejected; reported in stats) sets the helix pitch: integer-turn
   rounding must round the number of turns UP so pitch per turn = 2*pi*r*tan(angle) or less at every radius; straight
   ramps use the same angle. No descending feed into stock steeper than the ramp angle (+0.05 deg rounding).
2. Re-measure on Core Front T13 and the test block with zmap: exit code (0), axial plunges (0), gouges/rapids (0), entry
   count, entry time, total cycle time, rapids, horizontal p99. Also the entry time at 5, 10 and 15 deg (just run with the
   parameter - do not change the default) so the choice can be made by James. Write engine/RT2a_RESULTS.md.
Engine suites + pytest verify connector engine/test_post.py green. FOREGROUND only. Short outputs.
