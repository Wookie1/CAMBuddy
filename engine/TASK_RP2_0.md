# Task RP2 step 0: DIAGNOSIS ONLY - which roughing regions need a helix, and which can be entered from the side.
No generator behavior change (env-gated instrumentation or a separate engine/probe_rp2.py is fine). Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; do not edit verify/; report ONLY numbers you produced this
session from files that exist under /Users/James/ai-sandbox. Long runs: start with nohup and poll with short sleeps -
never end your turn while one is running. One heavy job at a time.
Context: Core Front T13 rough at 2 deg (this branch = main + RP1(a) at-depth links): ~213 regions, each entered by its
own 2-deg helix -> ~83 m / ~65.6 min of entry feed. Blank: X +-128.651, Y +-82.55 (part bbox X +-126.365, Y +-69.85):
2.286 mm of air beyond the part in X, 12.7 mm in Y. Rough command: engine.cli rough --step samples/core_front_setup.step
--stock -128.651 128.651 -82.55 82.55 0.0 60.96 --tool flat:12.686:0.0 --floor 24.765 --leave 0.381 --stepdown 19.05
--optimal-load-mm 2.032 --stepup 1.905 --hf out/core_front_setup_hf.npy --min-rest 0.5
For every region (per level) classify:
- OPEN: its cutting area touches, at that level's depth, either (i) material already cleared to <= Z + 0.05 (live stock
  model at the moment the region starts) or (ii) air outside the blank - with a contact width >= tool diameter + 2 x
  0.5 mm, so the tool can descend in cleared air/stock beside it and feed in sideways with no axial removal.
- CLOSED: no such access - needs a helix or ramp.
Report (engine/RP2_0_RESULTS.md, < 60 lines): counts per level and total (open / closed), the entry length and time at
2 deg (ramp feed 1270 mm/min) that would remain if ONLY closed regions helix, the same at 5/10/15 deg for information,
and how Adaptive2d's own outside-entry option (if any: e.g. its opType / ClearingOutside / start-from-outside behaviour)
could provide the side entries without a post-pass. Then STOP.
