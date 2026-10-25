# Task RR1c-5b: rest-rough passes are FRONTS grown from the cleared side; links never cut. Build, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate, the
validate_exact tolerance or the leave; do NOT edit verify/ or opencode.json; engine code never imports zmap/verify;
cutting values are parameters only (no feed reduction). Edit engine/rest_rough.py and engine/test_engine.py only.
BUDGET: <= 60 changed non-test lines vs 45d8685 (`git diff --numstat 45d8685 -- engine/rest_rough.py`, adds + dels),
STOP at ~80. FRESH session, HARD CAP 2 h (run `date` at start). FOREGROUND RULE: run every command in the foreground
and wait; the session ends the moment you end your turn. Never print NGC/G-code or large outputs; rg / sed -n line
ranges. Tests ONLY via scratchpad/slot_m4.sh (ENGINE_WORKERS <= 4); engine tests are NOT pytest (VibeCAD python, call
the functions; full suite `.../python engine/test_engine.py`). NO Core Front job - the supervisor runs the judge.
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit carrying this brief (45d8685 + briefs +
RR1c-5 Step 0 4ff88da). Read engine/TASK_RR1c5.md (facts) and engine/RR1c5_RESULTS.md (Step 0) first.

## Facts
TASK_RR1c5.md's facts stand. Step 0 (RR1c5_RESULTS.md): the Core Front centre band is MIXED at every level - its north
edge (y ~ 0.4) and east end are WALLED, its south side and inland gaps are OPEN (the existing SE2 side entries use those
open mouths). Closed rings offset from the WHOLE zone boundary fail both ways: inside-out leaves the spine uncut
(chain4), and outside-in puts a ring with uncut stock on its inner side along the walled edge (a full-width slot, the
earlier chain's failure).

## Change - passes are FRONTS grown from the CLEARED side
- C = the OPEN boundary segments of the zone at that Z (live stock clear just outside), plus any seed bore.
- Pass k = the part of offset(C, k*ae) lying inside the zone's legal CL region: an open-path offset of the open
  segments, intersected with the zone, using the EXISTING polygon offset/clip machinery. Each front's cleared side is C
  or the previous front.
- The wall-hug pass along a walled edge comes LAST, once the front is within ae of it.
- A zone with NO open edge: C = its helix bore; the fronts grow through necks on their own (no spine trochoid).
- Several disjoint pieces per front are fine: join them with stock-clear links (below) or the existing ladder. Enter
  through the existing SE2 mouths where they exist.
- Engagement check before emit: every pass meets radial <= ae against the LIVE stock (the planner's own disk model); a
  pass that still fails after the fallbacks is NEVER silent - stats["rr_ring_failed"] with place, Z, measured
  w_plan / ae_eq.
- AXIAL report beside it (report only this round): live a vs ap (cusp included), listed with place, in
  stats["rr_axial_over"].
- No link cuts: a feed link at depth must be stock-clear at the cutting Z (stock.link_clear, 0.05 tolerance);
  otherwise the existing ladder.
## Tests (engine/test_engine.py) - each NEW test must FAIL BY ASSERTION on 45d8685 (`git archive 45d8685`, never checkout)
- a varying-width band (tiny innermost loops + an uncut spine);
- an open-edge proud block;
- a fully walled band;
- a MIXED band shaped like the Core Front centre band (open south side, walled north edge).
Each: zmap (verify/zmap.py, padded part grid, --engage-max 2.286) shows 0 mm over 2.286 and 0 full-width windows at
cutting feed, and no feed link at depth crosses standing stock. Every existing test passes unchanged; full
engine/test_engine.py green. Run every test yourself and paste the exit codes.
## engine/RR1c5b_RESULTS.md (required)
(1) line count; (2) change with file:line; (3) the rr_axial_over report for each test case; (4) PASTED exit codes +
fail-on-45d8685 output; (5) anything not done. Then stop.
