# Task BS1a4d: band planning measures at zmap's resolution and credits the real bore footprint. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code NEVER imports zmap/verify (tests may); no margin/leave change; no feed
reduction. Edit engine/band.py, engine/rough.py (band-region backing only) and engine/test_engine.py only.
BUDGET: <= 40 NEW non-test lines over 351ce50 (`git diff --numstat 351ce50 -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~55. FRESH session, HARD CAP 2 h (run `date` at start). Never print NGC/G-code or large outputs; rg /
sed -n line ranges, never read big files whole. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). Engine tests are NOT pytest: VibeCAD python, call the functions; full suite
`.../python engine/test_engine.py`. NO Core Front engine or zmap job. Worktree /Users/James/ai-sandbox/stevecam-bs1a4,
branch bs1a4 at 351ce50 (BS1a4c + the supervisor's fix: the credit backing never emits a helix after enter_at).
Read engine/BS1a4_RESULTS.md section (10) and `git show 351ce50` first.

## Facts (BS1a4c)
Under-read (zmap - engine) is 1.49 mm on the test block: 69 of the 70 windows over 0.15 come from band._simulate's
cell-centre disk sampling on the 0.5 mm stock grid missing partial cells that zmap (0.1 mm part grid) counts; 1 window
((6.72,-4.00), -0.25) comes from the credit being a start-centred disk while the real helix bore is off-centre plus a
floor circle. Over-read (engine - zmap) is up to +14.07 at the region's first window for the same bore reason.

## Change
(a0) FIRST: at emit, a credited band region that fails the credit-0 re-check (today `replan0_drop`, an unconditional
    drop in rough.py's band backing block) is exactly Fix 1's case - it fails its gate at every level under honest
    credit. Route it into Fix 1's lightest-option choice (shrink levels re-simulated with credit 0 on the live stock vs
    drop-to-ring, same ranking: FW windows at cutting feed, then max ae, then length over 2.44). Record it in BOTH
    lists: stats["credit_fallback"] keeps the act, stats["failed_region_emitted"] gets place, Z, area, option chosen,
    engine max ae. Never emit anything not CL-checked (no move after enter_at except the region's own cutting paths).
    Reuse band.py's shrink ladder (factor it into a callable rather than duplicating it). Extend the test
    test_bs1a4c_fix_no_post_entry_helix's scenario family with a NEW test covering this route.
(b) band._simulate measures at zmap's resolution: a 0.1 mm grid (or equivalent sub-cell sampling) over each region's
    local bbox, for BAND PLANNING only (the 0.5 mm live stock stays the planning stock). Report band planning time on
    the test block before vs after (the supervisor measures Core Front).
(c) The credit is the REAL bore footprint: the swept cutter disk along the emitted helix path plus its floor circle,
    not a start-centred disk.
## Bars
- The alignment test passes AS WRITTEN: in every window the engine is never more than 0.15 mm below zmap, on the test
  block. Over-read stays report-only: report the max and the 5 worst windows (place, value).
- New assertions FAIL on e5e783e (`git archive e5e783e`, never checkout). Full engine/test_engine.py green. Run every
  test yourself and paste the exit codes.
## engine/BS1a4_RESULTS.md - add section (11) BS1a4d: change with file:line, line count, both max differences, the 5
worst over-read windows, TB band planning time before/after, PASTED exit codes + fail-on-e5e783e output. Then stop.
