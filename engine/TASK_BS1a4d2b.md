# Task BS1a4d2b: a band channel region's entry bores AT its trochoid start (centred helix). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only. If
test_bs1a4d_credit_real_bore fails after your change, STOP and report - do not touch it.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change. Edit
engine/band.py, engine/rough.py and engine/test_engine.py only.
BUDGET: <= 25 NEW non-test lines vs 2c8e11d (`git diff --numstat 2c8e11d -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~40. FRESH session, HARD CAP 2 h (run `date` at start and write it in the results file). Worktree
/Users/James/ai-sandbox/stevecam-bs1a4d2b, branch bs1a4d2b at the commit carrying this brief (= BS1a4d-f 2c8e11d +
this brief). Read engine/BS1a4_RESULTS.md section (14) first. Do NOT reuse anything from commit 667654e (a rejected
attempt that re-anchored the trochoid on the bore edge - that only moved the bite into a full-width lead-in).
AT-RISK existing tests (run these plus your new test; NOT the full suite): test_bs1a4d_credit_real_bore,
test_bs1a4d_credit0_lightest_option, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a_lshaped_channel, test_hb1v2_flat_floor_circle_after_helix, test_bs1a4c_fix_no_post_entry_helix,
test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical.

## Facts (supervisor, from rough.py at 2c8e11d)
- Band regions carry "helix": None, so helix_entry skips the hc tier and its main tier succeeds first: centre =
  start + (d + rh)*n with d >= 1.5. The return link from the helix end to the start therefore leaves the swept bore
  (radius rh + tool_r about the centre): the start disk pokes d mm past the bore edge into raw stock (test block: 43
  fresh cells, an 8.47 x 10.62 bite). Only the hc tier (circle through the start) and the fine tier at d = 0 give a
  start disk fully inside the bore.
- Fit: in test_bs1a_lshaped_channel's 19 mm (1.5 D) arms the legal centre band is 5.55 mm wide; a circle of rh 1.9
  (0.3*tool_r) through the start, bulging toward the open side, fits at both L-channel starts.
## Change (design fixed - do exactly this)
(d) A keyword on helix_entry, default off (e.g. `centred=False`); ONLY the band channel region entry passes True, so
    every other caller and fixture stays byte-unchanged. With centred=True the ladder tries ONLY bores whose circle
    passes through the trochoid start (centre within rh of the start, so the whole start disk lies inside the swept
    bore and the tool reaches the start through cleared material only), with shrinking rh (the main-tier radii, then
    the fine-tier radii), each CL/island/bore-containment-checked exactly as today. The ladder stays the only entry.
    If no centred bore passes, the region gets credit 0 and Fix 1's lightest option (shrink_ladder rules), and is
    listed in credit_fallback (and failed_region_emitted when it fails its credit-0 re-check). No silent emit.
## Test (engine/test_engine.py) - must FAIL BY ASSERTION on 2c8e11d (`git archive 2c8e11d`, never checkout)
- NEW: on the test-block scene (and the L-channel scene), every band region entry's start disk has NO fresh stock
  under it at the cut Z after its helix (0 cells standing above Z + 0.05 inside disk(start, tool_r) that the bore did
  not sweep). 2c8e11d: 43 cells at the test-block region.
## Report
Engine max ae and option for: the test-block region (6.28,-2.08) (2c8e11d: 5.75, shrink0.55); the L-channel regions
(-18.72,-0.12) (7.25, shrink1) and (-2.09,5.74) (5.75, shrink1). Fresh cells under each band entry's start disk (TB
had 43). How many band entries were centred vs fell back to credit 0.
## engine/BS1a4_RESULTS.md - add section (15) BS1a4d2b: change with file:line, line count, the Report items, PASTED
exit codes of the at-risk + new tests and the fail-on-2c8e11d output. Then stop.
