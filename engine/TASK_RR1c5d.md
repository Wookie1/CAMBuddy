# Task RR1c-5d: front 1 of each zone/level is offset from cleared ground by the ball's chord, not ae/2. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate, the ZB
floor 0.5, the validate_exact tolerance or the leave; do NOT edit verify/ or opencode.json; engine code never imports
zmap/verify (tests may). EVERYTHING ELSE IS FROZEN. Edit engine/rest_rough.py and engine/test_engine.py only.
BUDGET: <= 25 NEW non-test lines vs 035e590 (`git diff --numstat 035e590 -- engine/rest_rough.py`, adds + dels), STOP
at ~40. Generation time must not rise more than 5%. FRESH session, HARD CAP 2 h (run `date` at start, write it in the
results file). Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit carrying this brief
(= RR1c-5c 035e590 + this brief).
AT-RISK existing tests (run these plus your new test; NOT the full suite): test_rr1c5b_varying_width_band_fronts,
test_rr1c5b_open_edge_proud_block, test_rr1c5b_fully_walled_band_bore_seed, test_rr1c5b_mixed_band_core_front,
test_rr1c5c_closed_pocket_bore_entry_no_deep_axial, test_rr1c4b_closed_pocket_bore_levels,
test_rr1b_rest_rough_synth_pocket, test_rr1c2_cf_rapid_shapes_clear_stock.

## Facts (supervisor, measured on the Core Front chain with 035e590)
Fronts are offset(C, ae/2 + k*ae) (engine/rest_rough.py:730-737), C = columns cleared at this Z. For fronts k >= 1 the
engaged width is ae, and the judge (ZE2B) agrees. FRONT 1 is not: with its CL ae/2 from cleared ground the ball
engages ae/2 + c(a)/2, where a = live material height above Z and c(a) = 2*sqrt(a*(D - a)) is the ball's chord at
that depth. CF centre band: Z 44.965, a 0.755: 0.95 + 2.57 = 3.5 mm engaged (ZE2B ae_eq 2.66); Z 42.965, a ~2.1:
0.95 + 3.96 = 4.9 mm (ae_eq 3.55). All 146 cutting-feed windows over ae_eq 2.286 are on front 1. The pre-emit check
(:899-912) measures only the CL distance to the cleared mask (~0.95 for front 1), so it passes.
## Change (design fixed - do exactly this)
- Front 1 of each zone and level: a1 = the max live material height above Z along that zone's cleared edge, read
  from the PLANNING stock (no new 0.1 model, no ZE2B call in the engine). Its offset from cleared ground is
  c0 = ae - c(a1)/2 (negative when the chord is wider than ae: the CL sits INSIDE cleared ground), clipped to the legal
  CL region (CL check and leave exactly as now). Later fronts are c0 + k*ae, otherwise unchanged.
- Pre-emit check for front 1: flag when dv + c(a1)/2 > ae + CELL, with dv SIGNED (negative inside cleared ground).
  Fronts 2+ keep today's check.
- If clipping keeps front 1 from getting far enough inside, it is still emitted but listed in rr_ring_failed with its
  estimated width. Nothing silent.
## Test (engine/test_engine.py) - must FAIL BY ASSERTION on 035e590 (`git archive 035e590`, never checkout)
- NEW: two slabs beside cleared ground, one ~0.75 mm and one ~2.1 mm above the cutting Z; generate the rest-rough
  program and judge it with verify/'s ZE2B (as existing tests use verify.zmap): every front-1 window at cutting feed
  has ae_eq <= 2.286 and no full-width flag. The assertion is on MEASURED ae_eq, not on a stats key.
## Report
Each front 1's a1, c0 and estimated width in the new test scene (NO Core Front job - the supervisor measures the CF
centre band at Z 44.965 / 42.965 in the next chain). Generation time of the new test scene before/after.
## engine/RR1c5d_RESULTS.md: change with file:line, line count, the Report items, PASTED exit codes of the at-risk + new
tests and the fail-on-035e590 output. Then stop.
