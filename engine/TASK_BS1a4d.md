# Task BS1a4d (again, smaller scope): (a0) failing credit-0 regions take the lightest option; (c) credit = the real bore footprint. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change. Edit
engine/band.py, engine/rough.py (band-region backing only) and engine/test_engine.py only.
BUDGET: <= 40 NEW non-test lines vs 22cdff7 (`git diff --numstat 22cdff7 -- engine/band.py engine/rough.py`; report
MOVED lines - code moved unchanged into a function - separately; they do not count), STOP at ~55. FRESH session, HARD
CAP 2 h (run `date` at start). FOREGROUND RULE: run every command in the foreground and wait; the session ends when you
end your turn. Work ONLY from this brief and the engine/ code - do not browse the scratchpad. Never print NGC/G-code or
large outputs; rg / sed -n line ranges. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4); engine tests are NOT pytest (VibeCAD python, call the functions; full suite
`.../python engine/test_engine.py`). NO Core Front job. Worktree /Users/James/ai-sandbox/stevecam-bs1a4d, branch bs1a4 at
the commit carrying this brief (= BS1a4c-2 22cdff7 + briefs). Read engine/BS1a4_RESULTS.md sections (10)-(12) first.

## You may reuse ONE function from an earlier attempt
`git show ecf4e9b -- engine/band.py` contains `shrink_ladder(seg, stock, z, tool_r, cell, credit=None, dropopt=None)`:
channel_regions' shrink ladder plus Fix 1's lightest-option ranking as one callable. You may copy ONLY that function
(and replace the inline ladder in channel_regions with a call to it). Do NOT copy anything else from ecf4e9b (in
particular not its helix-centre refusal in rough.py helix_entry - that is not part of this task).

## Change
(a0) At emit, a credited band region that fails the credit-0 re-check (rough.py's band backing block, today
     `replan0_drop`, an unconditional drop) goes into Fix 1's lightest-option choice: the shrink levels re-simulated
     with credit 0 on the LIVE stock vs drop-to-ring, same ranking (FW windows at cutting feed, then max ae, then length
     over 2.44) - via shrink_ladder. Record it in BOTH lists: stats["credit_fallback"] keeps the act,
     stats["failed_region_emitted"] gets place, Z, area, option chosen, engine max ae. Never emit a move that is not
     CL-checked (no move after enter_at except the region's own cutting paths, which BS1a4c-2 already chord-checks).
(c) The entry credit is the REAL bore footprint: the swept cutter disk along the emitted helix path plus its floor
     circle - not a disk of radius tool_r centred on the path start. (The L-channel maxima 15.25 / 13.50 are entry
     windows that do not change with shrink level: the start-centred disk is the cause.)
## Tests (engine/test_engine.py) - each NEW test must FAIL BY ASSERTION on 22cdff7 (`git archive 22cdff7`, never checkout)
- (a0): a credited band region that fails the credit-0 re-check is NOT silently dropped: it is listed in
  failed_region_emitted with the option chosen, and the program passes CLCHECK.
- (c): the band planning sim's credit at a helix-entered start equals the swept helix + floor-circle footprint (e.g.
  cells cleared by the emitted helix are exactly the credited cells).
Full engine/test_engine.py green (test_bs1a_lshaped_channel included); run every test yourself; paste the exit codes.
## Report
The test-block region (6.28, -2.08) and the two L-channel regions ((-18.72,-0.12), (-2.09,5.74)): new engine max ae and
the option chosen.
## engine/BS1a4_RESULTS.md - add section (13) BS1a4d: change with file:line, NEW vs MOVED line counts, the Report
items, PASTED exit codes + fail-on-22cdff7 output. Then stop.
