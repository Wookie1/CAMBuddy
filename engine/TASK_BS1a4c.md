# Task BS1a4c: honest (backed) entry credit in band.py's planning sims, then assert the alignment bar. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only. You MAY turn your own BS1a4b test test_bs1a4b_windows_align_zmap's report into an
assertion (it is new in this branch, not an existing test) - or add a separate new test that asserts.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code NEVER imports zmap/verify (tests may); no margin/leave change; no feed
reduction. Edit engine/band.py, engine/test_engine.py, and in engine/rough.py ONLY the emit-time backing of BAND regions
(see 1); leave rough.py's own sims (_stepdown_rings ~959, ~994-995) alone - they are BS1b's.
BUDGET: <= 30 NEW non-test lines over 72ea825 (`git diff --numstat 72ea825 -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~45. FRESH session, HARD CAP 2 h (run `date` at start). Never print NGC/G-code or large outputs; rg /
sed -n line ranges, never read big files whole. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). Engine tests are NOT pytest: VibeCAD python, call the functions; full suite
`.../python engine/test_engine.py`. NO Core Front engine or zmap job. Worktree /Users/James/ai-sandbox/stevecam-bs1a4,
branch bs1a4 at 72ea825. Read engine/BS1a4_RESULTS.md (sections 4, 7) first.

## Facts
After BS1a4b the engine's and zmap's window BOUNDARIES are identical (791 vs 791) but the VALUES differ by up to
+3.88 / -3.87 mm. The under-read comes from band._simulate's synthetic entry-bore pre-clear (1.3 x tool_r, about
band.py:352) - the planner assumes every path starts in an already-cleared bore.

## Change
1. Port the BACKED entry credit into band.py's planning sims, re-implemented to MATCH the logic of bs1b's f3f2165
   (read it with `git show f3f2165:engine/band.py` lines ~192-210 and ~365-392, and `git show f3f2165:engine/rough.py`
   lines ~2280-2310 - read only, NEVER cherry-pick or checkout): a start is credited ONLY where an emitted helix
   really bores at least that much, or where the live stock is clear under the start disk at emit time; otherwise the
   credit is 0. band regions carry their credit; the emit loop backs it for BAND regions (ladder helix, else credit-0
   re-check, else not emitted) and records each fallback in stats["credit_fallback"].
2. Alignment test ASSERTS the bar on the test block: in every window the engine is never more than 0.15 mm BELOW zmap.
   Over-read (engine above zmap) stays report-only - report its max.
3. Re-measure both max differences. If the under-read is still over 0.15: STOP (no more fixes) and report every
   window over 0.15 with its place and cause: credit / stock divergence (which earlier move kind the engine stock
   missed, or grid resolution) / windowing.
## Tests - each NEW assertion must FAIL on e5e783e (`git archive e5e783e`, never checkout)
Confirm in the results that test_engine.py's only "-" line vs e5e783e is the _main tuple's closing line (no existing
assertion changed). Full engine/test_engine.py green; run every test yourself and paste the exit codes.

## engine/BS1a4_RESULTS.md - add section (10) BS1a4c: change with file:line, line count, both max differences, the
window list if the bar fails, PASTED exit codes + fail-on-e5e783e output. Then stop.
