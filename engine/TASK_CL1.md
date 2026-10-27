# Task CL1: one shared emit-time segment clearance check (sampled 0.25 mm). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only if needed.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate (CLCHECK,
allowance post-check, hf backstop, isl_ok tolerances stay as they are); do NOT edit verify/ or opencode.json; engine code never
imports zmap/verify (tests may); no margin/leave/feed change; never MOVE or edit Adaptive2d's points (skipping a segment via
the existing clip-break fallback is allowed - that is what a failing point already does); no Adaptive2d setting change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-cl1/scratch/ - never /tmp.
LIMITS: No limit or floor is raised.
RESULTS: create engine/CL1_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and
the stats it printed. (Cause given below; no cause section needed.)
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/rough.py only (the red test is already committed in engine/test_engine.py).
BUDGET: <= 40 changed non-test engine lines vs main 7923643 (`git diff --numstat 7923643 -- engine/rough.py`); STOP and
report at ~60. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-cl1, branch cl1
at the commit carrying this brief (= main 7923643 + red test 5bac33b + brief).
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Run a test like this (no pytest in VibeCAD python): /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_engine as t; t.<test_name>()"
RED TEST (must turn green): test_cl1_pins_segment_clearance.
AT-RISK (must stay green; run ALL and paste exit codes): test_rough_synth_pocket_repro, test_rough_testblock_r2,
test_rough_testblock_r4, test_dt1_synthetic_rough_twice_identical, test_hr1_rings_after_a2d, test_rough_rt_entries,
test_se2_side_entries_only_through_cleared, test_rr1c5c_closed_pocket_bore_entry_no_deep_axial,
test_rr1c4c_floor_circle_over_rising_surface, test_hb1v2_flat_floor_circle_after_helix, test_fi1_entry_feedin_within_limit,
test_rr1b_rest_rough_synth_pocket, test_bs1a_straight_channel, test_bs1a_lshaped_channel, test_bs1a3_no_band_after_a2d,
test_bs1a4b_windows_align_zmap, test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d8e_inrun_guard_skips_planned_paths, test_bs1a4d9_no_entry_at_stale_q4, test_bs1d_overload_band_on_standing_strip,
test_bs1d_a2d_drop_counted.

## Facts (supervisor, measured on main 7923643)
- RED scene: 60 x 50 pocket, six 1 x 1 mm pins 18 mm tall. rough() raises "rough CLCHECK FAILED: 32 sample(s) below CL +
  axial_leave" for ONE move: G1 at cutting feed, Z 0.381, (-3.920, -16.750) -> (3.456, -16.748), 7.38 mm long. It is
  points 1497 -> 1498 of one Adaptive2d CUTTING path (tagged by matching both endpoints to the a2d region paths). Both
  points pass isl_ok; the segment's middle passes 6.25 mm from the pin at (0, -10) - inside the pin's forbidden zone.
- The cutting emit (rough.py ~:2417, `good = isl_ok(pts)` in the `for (kind, pts) in res["paths"]` loop - a2d regions,
  hug rings and bands all pass through it) checks POINTS only. A failing point already falls back: the path is treated
  as broken there (`gap`), and the next good point is reached by the clip bridge (chord sampled at 0.5 mm, ~:2444,
  only if <= clip_bridge_mm and itself clear) or a clip break + corridor-checked re-entry (stats["n_clip_breaks"]).
- Other emit paths with coarse or points-only checks (CL1 list, line numbers drifted since): the clip bridge chord (0.5 mm),
  the a2d deep link corridor (0.4 mm), RT at-depth feed links (points), link landing, enter_at straight links (0.4 mm),
  HB1v2 floor circles (~0.5 mm), the helix return (0.4 mm), SE2 feed-in (0.4 mm), entry candidates (points).

## Items (coordinator spec)
1. Add ONE module-level helper in rough.py, `_seg_clear(ok_fn, a, b, step=0.25)`: True iff ok_fn holds at a, b and at
   samples every <= step mm along the straight a -> b (use the same oracle the call site already uses for its points,
   e.g. isl_ok / isl_ok3; one batched ok_fn call per segment).
2. Use it in the cutting emit: a segment pts[i-1] -> pts[i] whose endpoints are good but which is NOT _seg_clear is
   handled exactly like a failing point (break there; the existing bridge / clip-break re-entry logic reaches the next
   point). Count each such break in stats["cl1_seg_breaks"] (int, init 0) and log {"z", "x", "y"} (the segment's
   midpoint) in stats["cl1_seg_log"] (list, init [], cap 200 entries; the count is never capped).
3. Use the same helper for the clip bridge chord (replacing its 0.5 mm sampling). Then, ONLY within the budget, the other
   listed paths in this order: enter_at straight links, SE2 feed-in, helix return, HB1v2 floor circle, a2d deep link
   corridor. Any not done: list them in the results file as "not done (budget)". A failing move falls back the way that
   path already falls back today - no new fallback logic.
4. Programs where no segment fails must be byte-identical (test_dt1 / test_bs1a3 etc.).
## engine/CL1_RESULTS.md: the change with file:line, line count vs 7923643, which paths use the helper, the red test's printed
numbers, PASTED exit codes of the red test and all at-risk tests, git diff --numstat. Then stop. (Supervisor verifies from
committed code, runs a mutation (_seg_clear -> lambda *a, **k: True must bring the refusal back), the full engine suite and the
Core Front judge vs main: gates incl. holder, clcheck, overload windows/mm, cycle within +2 %.)
