# Task V1e: finish the engagement + plunge report (REPORT-ONLY). verify/ + connector/ only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase. Do not commit (the supervisor commits the merge).
No bypass flags, never relax or delete tests.
State: this worktree is MID-MERGE of main into verify-engagement (WIP 6f34ee1). Conflicts in verify/zmap.py,
verify/test_zmap.py, connector/runner.py. Resolve them KEEPING BOTH SIDES: main's S5 holder_hits / --tool-number /
shank work and holder gate, plus this branch's engagement + plunge reports. Remove all conflict markers.
Then:
1. Engagement must never be inf/NaN: handle zero-length moves (pure Z), full-slot moves, arcs and helixes; clamp to
   [0, tool diameter]; JSON must be strict (no Infinity/NaN). Engagement = radial engagement against zmap's LIVE stock,
   numpy only, independent of engine code.
2. Flags: spikes above --engage-max (rough T13 default 2.032 mm via --optimal-load x 1.0 for roughing? use the
   explicit --engage-max when given; else 1.5 x --optimal-load), and feed moves entering stock steeper than
   --ramp-angle (deg). Report count, max, top 10 spots (line, XY, value).
3. Connector: both reports in check.json under "warnings" for adaptive_rough and both stages of slope_split_finish
   (finish stage: threshold off or from the finish stepover - say which); warnings never fail a run; all existing
   gates (gouges, rapid collisions, over-flute/shank, holder, clcheck) unchanged.
4. Tests: zero-length move, full slot, arc, helix -> finite values <= D; strict-JSON test on a real sample program;
   existing tests all pass: /opt/homebrew/bin/python3 -m pytest verify connector -q (the connector e2e tests must
   pass too; if one fails, find the cause in your changes).
