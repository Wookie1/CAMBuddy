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

## chain7 record (supervisor, 2026-10-25, CF lane)
rr1b fa54f9b rest-rough on the current Core Front part (chain4 recipe, pinned chain4 judges: fe5 zmap for ZB, the
ze2b worktree for ZE2B). Finish half not run (main lacks fe5 --ramp-angle-deg).
- Rest-rough gen rc 0: 10278 moves, 837.7 s, 22 levels, 2 passes skipped. Exact CL: 0 below / 10010 pts.
- ZB judge rc 0: gouges 0, rapid collisions 0, over-flute 0, holder 0; axial ZB 19 entries over the 0.2 floor,
  max 0.247 mm. ZE2B rr rc 0.
- Judge-measured ZB, worst three of all 128 recorded entries (covers every descent re-entry):
  0.247 mm line 989 XY (71.045, -2.003) Z 38.979, margin 0.253; 0.2432 mm line 2899 (-18.611, -8.977) Z 45.014,
  margin 0.257; 0.2404 mm line 5361 (-21.763, -10.683) Z 43.014, margin 0.260.
- Engine side: no entry accepted above 0.25 at any step on CF (max: step1 0.225, step2 0.247, step4 0.249,
  bore 0.028), so DEEP_TOP changed no CF decision.

---

## RRA3 (fresh session, started `date` = Sun Oct 25 02:53:27 MST 2026)

Task: pin DEEP_TOP's scope at step-1 straight descents (TEST ONLY - no engine
change). Plan:
- Scene: uniform 29.87 mm stock top over a wide rectangular pocket (floor
  29.4, frame/part top 29.8); level t = floor_z + rest_leave = 29.6, so EVERY
  live disk_depth probe at the level reads exactly stock_top - t = 0.27 mm,
  inside the (0.25, 0.3] window, independent of where the engine's entry
  column lands. Clean tree: step1 refuses (0.27 > 0.25), step-2 ramp accepts
  at L ~ 0.6 mm where the top reads 0.249 <= 0.25.
- New test test_rra3_straight_descent_scope asserts every recorded step-1
  entry <= 0.25 mm (printing measured depth) and non-vacuity via a
  LiveStock.disk_depth spy: the first probe IS the step-1 attempt at the
  ladder entry column and must read in (0.25, 0.3] with NO step-1 entry
  recorded (refused on the clean tree).
- Mutation B (step1 `d <= shallow` -> `d <= DEEP_TOP`) in a scratch copy must
  make the test FAIL by the accepted straight-descent depth (~0.27 mm).
Test scene validated (scratch/rra3_probe.py, EXIT=0, ~queued slot wait):
uniform stock 29.87 over pocket floor 29.4 -> level 29.6; first live
disk_depth probe (the step-1 attempt at the ladder entry column
(18.558, 12.9, t=29.6)) reads 0.2697 mm (in (0.25, 0.3]) and is REFUSED
(no step-1 entries); zone entered via step-2 ramp L=0.6 at 0.249 mm;
1 level, 444 moves, validate_exact 0 gouges, 0 passes skipped.
Writing the new test now.

### Clean-tree run of the new test (slot_m4, ~03:35 MST)

  slot_m4.sh python scratch/rra3_run.py test_rra3_straight_descent_scope
  PASS rra3 straight-descent scope: step-1 column 0.270 mm (in (0.25, 0.30])
  refused; 2 step-2 ramp entries, none deeper than 0.25
  0 failure(s)
  EXIT=0

`git diff --numstat` at this point: 79 1 engine/test_engine.py (one new test
+ one _main tuple line), 30 0 engine/RRA_RESULTS.md, 23 2 opencode.json
(pre-existing dirty, untouched). Next: the 4 at-risk tests, then mutation B.

### Mutation B (scratch/rest_rough_mutB.py: step1 `d <= shallow` -> `d <= DEEP_TOP`)

Run (slot_m4, ~03:55 MST): the mutant is loaded as engine.rest_rough by
scratch/rra3_mut.py; the engine on disk is untouched.

  slot_m4.sh python scratch/rra3_mut.py
  FAIL test_rra3_straight_descent_scope: straight descent 0.270 mm accepted
  where 0.25 must hold (DEEP_TOP applies only at step-2 descent re-entries,
  never to step1): [{'zone': 0, 't': 29.6, 'step': 1, 'kind':
  'direct-descent', 'depth_mm': 0.27}, {'zone': 0, ... 'depth_mm': 0.27}]
  1 failure(s)
  EXIT=1

MEASURED VALUE: 0.270 mm - both ladder entries become straight descents in
(0.25, 0.3] under mutation B, refused on the clean tree at the identical
columns (spy: first probe 0.2697 mm). (An intermediate test revision failed
mutation B one assertion earlier - "scene must still be cut via the step-2
ramp", same 0.27 mm entries printed; the pin assertion was moved first so
the failure message leads with the measured straight-descent depth.)

### Clean-tree PASS of the final test + all 4 at-risk tests (slot_m4, ~04:05 MST)

  slot_m4.sh python scratch/rra3_run.py test_rra3_straight_descent_scope \
      test_rra2_deep_top_scope test_rr1c_thin_band_inpass_ramp \
      test_rr1c3_bay_deep_groove_top_down \
      test_rr1c5d_live_grid_fine_for_coarse_stock
  PASS rra3 straight-descent scope: step-1 column 0.270 mm (in (0.25, 0.30])
  refused; 2 step-2 ramp entries, none deeper than 0.25
  PASS rra2 DEEP_TOP scope: max level-entry top 0.245 mm <= 0.25
  PASS rr1c5d live grid: 0.100 mm for a 0.5 mm input stock
  0 failure(s)
  EXIT=0

(test_rr1c_thin_band_inpass_ramp and test_rr1c3_bay_deep_groove_top_down
print nothing on success; the runner mirrors _main - an AssertionError would
have printed FAIL and forced exit 1. All five passed: EXIT=0.)

### The scene (test_rra3_straight_descent_scope, engine/test_engine.py)

Closed pocket 12 x 24 mm, floor 29.4, frame part top 29.8 (five boxes, the
rr1c box-union style); stock = UNIFORM top 29.87 on the usual 0.5 mm grid.
Single level t = floor_z + rest_leave = 29.6, so every live disk_depth probe
at the level reads 29.87 - 29.6 = 0.27 mm (uniform top: position-independent,
the disk never sees a taller neighbour column), inside the (0.25, 0.3]
window. min_excess 0.2 keeps the frame (excess 0.07) out of the zone.
Clean tree: step1 refuses the ladder's entry column (0.2697 > 0.25), the
step-2 in-pass ramp accepts at L = 0.6 mm with top 0.249 <= 0.25; zone
entered, 1 level, validate_exact clean. The test asserts (1) every recorded
step-1 entry <= 0.25 mm (message prints the measured depth), (2) non-vacuity
via a LiveStock.disk_depth spy (observation only): the FIRST probe - step1
is the first ladder call and nothing probes disk_depth before it - reads in
(0.25, DEEP_TOP] at the level, and no step-1 entry exists, i.e. that column
was REFUSED as a straight descent; (3) the scene is still cut via step 2.

### RRA3 summary

- New test: test_rra3_straight_descent_scope + one _main() tuple line.
  No existing test, tolerance, gate or engine file touched; no engine code
  change (test-only task); no Core Front job; slot waits observed but no
  stuck lock.
- Clean tree: EXIT=0 (new test, twice incl. final combined run; at-risk x4
  in the same combined run EXIT=0).
- Mutation B (scratch copy only): EXIT=1, FAILS BY THE MEASURED accepted
  straight-descent depth 0.270 mm.
- Scratch artifacts (untracked scratch/): rra3_probe.py, rra3_run.py,
  rra3_mut.py, rest_rough_mutB.py.

### Final diff (`git diff --numstat`, 04:09 MST)

  116 0  engine/RRA_RESULTS.md   (this file; RRA3 section appended)
  85  1  engine/test_engine.py   (new test + one _main tuple line)
  23  2  opencode.json           (pre-existing dirty at session start -
                                  harness model config; NOT touched)

No commits made. Session start 02:53 MST, finish 04:09 MST (~1 h 16 m,
inside the 2 h cap).

---

## RR1c5e (started Sun Oct 25 05:03:42 MST 2026, hard cap 2 h)

Task: test_rr1c5d_front1_chord_offset_slabs is vacuous ("no deep cutting-feed
windows"). Bisect engine commits, decide legit-vs-regression, re-scope scene
only if legitimate. Test/scene edits only (engine/test_engine.py), <= 20
changed lines, threshold and vacuity guard unchanged.

NOTE: at session start this file was mistakenly rewritten before its tracked
contents were checked; it has been restored byte-for-byte from
git show HEAD:engine/RRA_RESULTS.md with this RR1c5e section appended.

### Cause analysis (step 1) - IN PROGRESS

### Bisect table

| commit | deep-window count | max depth | verdict |
|---|---|---|---|

### Decision

### Scene change (step 2)

### Test runs / exit codes

### Mutation record
