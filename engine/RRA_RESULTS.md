# RR-A Results — rest-rough bay test under RR1c-5d (A)

Session start: Sat Oct 24 23:14:21 MST 2026 (HARD CAP 2 h → end by 01:14 MST)
Base commit: 1720097 (branch rr1b)

## Status log (running)
- (init) results file created. No code changes yet. No tests run yet.
- 23:20 lane smoke OK via slot_m4.sh (python 3.11.14, numpy+opencamlib import ok). NOTE: lane queues ~2-4 min per run.
- 23:35 traces captured (rra_trace.py, instrumented disk_depth/disk_top/batch_drop) on git-archive scratch copies
  base=07f0c7e (trace_base.jsonl, 3511 lines) and head=1720097 (trace_head.jsonl, 3699 lines). No worktree change.

## STEP 1 RESULT — the first differing decision (07f0c7e vs HEAD), bay scene

Only engine diff between the two trees (rest_rough.py/entry_depth.py): the (A) line
`live = fin.LiveStock(..., fine=min(stock[3], fin.FINE))` (rest_rough.py:265) — live grid 0.5 mm -> 0.1 mm.

FIRST differing DECISION (control flow flips; earlier lines differ only in reading precision, same verdict):
- Trace index 604/605. Check: **step 4 (SE2 side entry) descent-column acceptance**
  `live.disk_depth(sx, sy, t) <= shallow (0.25)` at level t = 28.2, column **(16.364, 10.293)**.
  - 07f0c7e (fine 0.5): depth = **0.2281 mm** <= 0.25 -> ACCEPTED, SE2 entry emitted, the 28.2 pass
    at (19.9, 6.76) is cut (base: 0 passes skipped).
  - HEAD (fine 0.1): depth = **0.2664 mm** > 0.25 -> REFUSED; scan exhausts all 7 distances x 16 angles,
    step4 fails, that pass is SKIPPED (head stats passes_skipped: t=28.2, xy [19.9,6.76], live_depth 1.8).

DECISION THAT REFUSES THE DEEPER (groove) LEVEL — same check family, level t = 26.208 (floor-hugging,
zmin 26.008 + leave 0.2): **step 2 in-pass ramp top-clear rule** (FE5e) in step2_dir:
`d = live.disk_depth(ax, ay, az) <= shallow (0.25)` at the ramp top. The 51.2 mm centre-line pass at
(17.0, 8.1) is entered in BASE by a 2-deg ramp whose top is at **(17.0, 58.3, az = 27.9613)**:
  - 07f0c7e (fine 0.5): d = **0.2435 mm** <= 0.25 -> ACCEPTED -> groove cut (levels = 2).
  - HEAD (fine 0.1): d = **0.2571 mm** > 0.25 -> REFUSED. Neighbouring probe tops on the fine grid:
    y 58.1 -> 0.2631, 58.3 -> 0.2571 (scan minimum), 58.5 -> 0.2821, 59.3 -> 0.2963; the groove level
    region reg_cur ends at y ~ 59.3 so the scan stops. step1 reads 2.5802 at the pass start, step4 scans
    224 columns at t = 26.208 with min depth 1.993 -> all refused -> pass SKIPPED, levels = 1 -> TEST FAILS.
Both flips are pure grid-resolution reads of the SAME terrain (identical moves until the flip): the 0.5
grid under-read by 0.014-0.038 mm here, landing both true depths just ABOVE the engine's shallow=0.25
gate while the scored judge gate (ZB) is 0.5. The bore/helix is geometrically impossible here in BOTH
trees (floor circle r >= min_helix_r 1.903 at z 26.2 violates CL 26.17 at x = 17 +- 1.9; helix: 0.0 both).

## STEP 2 - the fix (engine/rest_rough.py; git diff --numstat: 22 added / 10 deleted)

Cause: the step-2 ramp TOP-CLEAR gate `d <= shallow (0.25)` in step2_dir was calibrated for a planner
grid that could UNDER-read the ZB judge (up to 0.64 mm on coarse stock). After (A) the planner live
grid is fine=min(stock cell, 0.1) - at least as fine as the judge's 0.1 grid (same conservative
resample, same stamp model, same A) - so that read is no longer an under-read, and the fixed margin
now refuses legitimate descent re-entries whose true scored depth is 0.2571 mm vs the ZB limit 0.5.

Change (a threshold, NOT one of the LIMITS; (A) untouched; no margin/leave/feed change):
- rest_rough.py:63  new constant DEEP_TOP = 0.3, with the measured justification in the comment.
- rest_rough.py:415,426,440  step2/step2_dir take `deep`; the top-clear uses DEEP_TOP only when deep.
- rest_rough.py:524  enter() takes `deep` and forwards it to step2 only (steps 1 and 4 unchanged).
- rest_rough.py:900,913  deep=True ONLY at the two pass-loop DESCENT re-entry sites (dzd > 1e-9: a
  lower level entered from the level just cleared). Zone entry, lateral links, step1, step4 SE2,
  bore-descent (zb_floor), cl_ok/cl_ok_path and validate_exact all keep their existing gates; a
  descent ramp top deeper than 0.3 is still refused.

Measured values justifying 0.3: with the fix the accepted ramp top is y = 58.1, az = 27.9543,
d = 0.2631 mm (scan minimum 0.2571 at y = 58.3); the judge-equivalent replay reads the same grid, and
the scored ZB limit is 0.5, so the accepted entry keeps >= 0.237 mm of margin. Pre-fix that same top
reads 0.2571 > 0.25 and is refused, so the new behaviour fails by a measured value on pre-fix code.

## Test runs (appended per run)

- 00:36 MST, via slot_m4.sh + targeted runner (rra_run.py; VibeCAD python has no pytest, test file is
  standalone-style). `test_rr1c3_bay_deep_groove_top_down` -> **PASS**, EXIT=0. Output: "PASS
  test_rr1c3_bay_deep_groove_top_down / RESULT: ALL PASS". git diff --numstat (engine/rest_rough.py):
  22 10. (opencode.json 24/3 was already dirty at session start, NOT touched by this task.)


