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



## RRA2 (fresh session, started `date` = Sun Oct 25 01:32:22 MST 2026)

Plan: (1) replace DEEP_TOP's comment with the one-line text; (2) new test
test_rra2_deep_top_scope pinning DEEP_TOP to the descent re-entry sites;
(3) mutation on a scratch copy only (apply 0.3 at a level entry / straight
descent) must fail the new test by a measured top depth in (0.25, 0.3].

### Comment change (engine/rest_rough.py)

Replaced the 7-line RR-A comment above `DEEP_TOP = 0.3` with exactly one line:
`# descent re-entry top-clear; calibrated at live grid 0.1, judge ZB 0.5`.
Comment-only: the constant line and all code are untouched (git diff of
rest_rough.py is 1 insertion / 7 deletions, all comment lines).

### New test (engine/test_engine.py)

`test_rra2_deep_top_scope` (added to the file and to the `_main()` runner
tuple). Uses the thin-band scene of test_rr1c_thin_band_inpass_ramp, which is
SINGLE-level (stats zones[0]["levels"] == 1, asserted): every ladder entry is
then a level entry / same-level link / straight descent (deep=False), so the
shallow 0.25 top-clear gate must hold for EVERY recorded entry and DEEP_TOP
(0.3) must never apply. The test asserts no entry in stats["entries"] reads
deeper than 0.25 mm and fails printing the measured depth. Measured on this
tree: max entry top 0.245 mm (zone-entry ramp L=8.8), plus a direct-descent
at 0.047 mm -> passes. (The complementary half - DEEP_TOP DOES apply at
descent re-entries - is already pinned by test_rr1c3_bay_deep_groove_top_down,
whose accepted descent ramp top reads 0.263 mm.)

### Test runs (all via slot_m4.sh + VibeCAD python, targeted only)

- New test on this tree: "PASS rra2 DEEP_TOP scope: max level-entry top
  0.245 mm <= 0.25 / PASS test_rra2_deep_top_scope" -> EXIT=0.
- At-risk + new test, per-test exit codes (~01:38 MST):
  test_rr1b_rest_rough_synth_pocket        EXIT=0
  test_rr1c_thin_band_inpass_ramp          EXIT=0
  test_rr1c_narrow_pocket_side_entry       EXIT=0
  test_rr1c3_bay_deep_groove_top_down      EXIT=0
  test_rr1c4b_plateau_topdown_axial_load   EXIT=0
  test_rr1c5d_live_grid_fine_for_coarse_stock EXIT=0
  test_rra2_deep_top_scope                 EXIT=0

### Mutation (scratch copies under the session temp dir, NEVER committed)

- Mutation A - leak at the LEVEL ENTRY (step-2 ramp): `top_lim = DEEP_TOP if
  deep else shallow` -> `top_lim = DEEP_TOP` in the scratch copy. New test
  output: "FAIL test_rra2_deep_top_scope: level-entry top 0.294 mm accepted
  where 0.25 must hold (DEEP_TOP applies only at descent re-entries):
  [{'zone': 0, 't': 29.847, 'step': 2, 'kind': 'in-pass-ramp 2.0 deg
  L=7.4', 'depth_mm': 0.294}]" -> EXIT=1. MEASURED VALUE: 0.294 mm, a top in
  (0.25, 0.3] accepted at L=7.4 where the clean tree refuses it and accepts
  L=8.8 at 0.245 mm. This is the required measured-value failure.
- Mutation B - leak at the STRAIGHT DESCENT (step1): `d <= shallow` ->
  `d <= DEEP_TOP` in step1 only, scratch copy. The test still passes (EXIT=0)
  on this scene: the step1 candidate column in the thin band reads ~0.55 mm
  (rest 30.4 - level 29.847), above 0.3, so step1 fails under BOTH gates and
  the leak is invisible here. No existing at-risk scene was found to route a
  straight descent through a column depth in (0.25, 0.3] without inventing
  geometry; the test's assertion already covers step-1 entries too (it checks
  ALL recorded entries against 0.25), so a (0.25, 0.3] straight descent, if
  a scene produced one, would fail it by the same measured-depth message.
  Mutation A is the demonstrated pin.

### Diff size at finish (`git diff --numstat`, 01:38 MST)

  7  0  engine/RRA_RESULTS.md   (this file; RRA2 section appended)
  1  7  engine/rest_rough.py    (comment-only)
  60 1  engine/test_engine.py   (new test + one tuple line)
  23 2  opencode.json           (pre-existing dirty at session start - model
                                 config written by the harness; NOT touched)

No commits made. No limits/floors/gates changed; no existing test altered.
