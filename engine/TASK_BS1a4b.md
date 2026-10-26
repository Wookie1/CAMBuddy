# Task BS1a4b: finish BS1a4 - a failing band region takes its lightest measured option, never silently. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; NEVER relax a
gate (AE_SS, AE_SPIKE); do NOT edit verify/ or opencode.json; engine code NEVER imports zmap/verify (tests may); no
margin/leave change; no feed reduction. Edit engine/band.py, engine/rough.py and engine/test_engine.py only.
BUDGET: <= 80 changed non-test lines vs e5e783e IN TOTAL (`git diff --numstat e5e783e -- engine/band.py
engine/rough.py`, adds + dels; the WIP d41c89d is already 52), STOP at ~80. FRESH session, HARD CAP 2 h (run `date`
at start). Never print NGC/G-code or large outputs; rg / sed -n line ranges, never read big files whole. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). Engine tests are NOT pytest: call them with the VibeCAD python
(`.../python -c "import sys; sys.path.insert(0,'.'); import engine.test_engine as t; t.test_x()"`); full suite
`.../python engine/test_engine.py`. NO Core Front engine or zmap job. Worktree /Users/James/ai-sandbox/stevecam-bs1a4,
branch bs1a4 at d41c89d (BS1a4 WIP). Read engine/TASK_BS1a4.md and engine/BS1a4_RESULTS.md first.

## Keep
Fix 2 (window alignment: _simulate's first move in a real, non-zero-length window) stays as in d41c89d.
## Revise Fix 1 (supervisor decision)
A region where every shrink level fails its gate takes the LIGHTEST measured option among {each shrink level, dropping
it to the ring}. Lightest = fewest full-width windows at cutting feed, then the lowest max ae, then the shortest length
over 2.44 - measured with the ALIGNED _simulate (for the drop option: the ring's own simulated windows over that
stock). Whatever is emitted for a failing region is NEVER silent: stats["failed_region_emitted"] lists each one with
place (x, y), Z, area, the option chosen, and the engine max ae. On the test block this must keep the trochoid (zmap
8.47 there) over the ring slot (zmap 12.6, full width).

## Tests (engine/test_engine.py) - each NEW test must FAIL BY ASSERTION on e5e783e (`git archive e5e783e`, never checkout)
- Failing region: on the test block (or a synthetic channel where every shrink level fails), the region is listed in
  failed_region_emitted with the fields above, and FW at cutting feed (zmap, padded 0.1 grid) is not higher than main's.
- Alignment proof: replay the same band moves through _simulate and zmap's engagement measure: identical window
  boundaries, and the engine never reads more than 0.15 mm lower than zmap in any window, on the test block. Report the
  max difference BOTH ways.
- Full engine/test_engine.py green. Run every test yourself and paste the exit codes.

## engine/BS1a4_RESULTS.md - fill in the pending sections (4) and (5), add (7) revised Fix 1 with file:line, (8) PASTED
exit codes + fail-on-e5e783e output, (9) the failed_region_emitted list on the test block. Then stop.
