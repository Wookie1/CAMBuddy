# Task Z6: engagement warning thresholds per operation (report-only). Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests;
verify/ must NOT import engine/. Warnings stay warnings: no new gate, no change to any pass/fail logic.
1. verify/zmap.py: when only --optimal-load is given (roughing), derive engage_max = 1.2 x optimal load (today 1.5x).
   Update the --optimal-load / --engage-max help text to say: roughing 1.2 x optimal load; finishing passes an explicit
   --engage-max (1.5 x stepover).
2. connector/runner.py: pass the rough threshold explicitly (--engage-max 1.2 x rough optimal load) on every roughing
   zmap call; keep the finishing call at 1.5 x stepover. Name both factors as module constants
   (ROUGH_ENGAGE_FACTOR = 1.2, FINISH_ENGAGE_FACTOR = 1.5).
3. connector/README.md and the panel gate-help line: engagement warnings fire above 1.2x the optimal load (roughing,
   e.g. 2.438 mm for 2.032) and 1.5x the stepover (finishing).
4. Tests: zmap with --optimal-load 2.032 reports threshold_mm 2.4384; the connector check.json carries the rough
   threshold 1.2x and finish 1.5x. Run /opt/homebrew/bin/python3 -m pytest verify connector -q. Short outputs.
