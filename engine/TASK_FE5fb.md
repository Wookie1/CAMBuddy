# Task FE5f-b: skip only the illegal FRAGMENT, keep the rest of the pass. Fix, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests (you may only
STRENGTHEN test_fe5f_skip_bore_entries as below); do NOT edit verify/ or opencode.json; NEVER lower the ZB floor; NEVER
skip anything that can be entered legally. Edit engine/finish.py and engine/test_finish.py only.
BUDGET: <= 40 changed non-test lines vs 1f499f5 (`git diff --numstat 1f499f5 -- engine/finish.py`, adds + dels), STOP at
~55. FRESH session, HARD CAP 1 h. Never print NGC/G-code or large outputs; rg / sed -n line ranges, never read big files
whole. Small tests ONLY via the small-test lane
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). NO Core Front / interim-model engine or zmap job. Worktree /Users/James/ai-sandbox/stevecam-fe5,
branch fe5 at 1f499f5 (FE5f; read engine/FE5f_RESULTS.md).

## Why
FE5f (engine/finish.py ~2308-2331, 2401) drops the WHOLE pass (`ordered[k] = None`) when its entry cannot be made legal.
Shallow-area raster passes that cross a bore would lose their whole stripe across the boss and beyond - area outside the
bores left unfinished.

## Change
Trim only the fragment: from the illegal entry along the pass to the next point where FE5e's rule (top-clear ramp, live
depth <= 0.25 at the descent column; same _fe5_pick_ramp logic) can make a legal re-entry; keep the rest of the pass (it
is entered legally there). If no such point exists on the pass, drop the pass as today. Record only the dropped
fragment's vertices in fe5_skip_pts / the clusters.

## Test (engine/test_finish.py) - strengthen test_fe5f_skip_bore_entries
Also assert that the dome surface OUTSIDE the bore - every finish-relevant cell beyond bore radius + tool radius + 0.5 mm
- is still finished: no skipped vertex there, and the emitted passes cover it (e.g. cut points within one stepover of
every such cell, or the same coverage the e773afa finish had there). It must FAIL BY ASSERTION on 1f499f5 (whole-pass
drop) - show it with a `git archive 1f499f5` extract - and pass after your change. Keep every other FE5/FE5e/FE5e-t/FL1b
test green; run the full engine/test_finish.py at the end.

## engine/FE5fb_RESULTS.md (required)
(1) line count; (2) change with file:line; tests with exit codes; fail-on-1f499f5 proof; (3) anything not done. Then stop.
