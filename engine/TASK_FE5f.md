# Task FE5f: skip (never plunge) finish/rest entries FE5e cannot make legal; report the skipped area. Build, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ or opencode.json; NEVER lower the ZB floor; NEVER skip a pass entry that can be entered legally (FE5e's top-clear
ramp or the reverse end). Edit engine/finish.py, connector/runner.py (summary only), engine/test_finish.py.
BUDGET: <= 80 changed non-test lines vs e773afa (`git diff --numstat e773afa -- engine/finish.py connector/runner.py`,
adds + dels), STOP at ~110. Fresh session, HARD CAP 2 h; if the same test fails ~3 times with no new idea, stop and write
the results file. Worktree /Users/James/ai-sandbox/stevecam-fe5, branch fe5 (e773afa = FE5e + FE5e-t). Cite only commits
that exist (`git cat-file -t`). NEVER print NGC/G-code or large outputs; rg / sed -n line ranges, never read big files
whole. You run on THIS Mac's model: small tests only via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4) - NO Core Front / interim-model engine or zmap job (the supervisor runs the chain judge).

## Why
James chose "Skip them" for the three ~10 mm through-bores in the bosses (centre-south ~(-0.5, -36.1), corners
~(+-107.3, 50.8); 17.8 mm deep, full of stock; the T20 ball has 0.02-0.05 mm radial room): our programs stay out, he
drills/bores them. Today the finish still descends into them (ZB 1.48 / 0.62 mm at those XYs).

## Change
1. In engine/finish.py where FE5e leaves an entry unresolved (`fe5_top_unresolved`, ~L2225-2280: no top-clear ramp on the
   pass and none from its reverse end) and the entry would be a ZB violation (live depth > the ball ZB floor 0.5): SKIP it -
   drop that pass fragment, or the pass up to its next legal entry (re-checked with the same FE5e rule) - never emit the
   plunge. Record each skip; merge skips into clusters (e.g. within 2 x tool D): centre, bbox, max live stock depth, area.
   Stats: fe5_skipped_clusters (list), fe5_skipped_n.
2. Same for the T33 rest pass (same code path when rest_from is used).
3. connector/runner.py: copy each program's skipped clusters into check.json under
   "left_for_hole_op_or_another_setup": {"finish": [...], "rest": [...]} so James sees them in the summary.

## Test (engine/test_finish.py) - must FAIL BY ASSERTION on e773afa (git archive extract, never checkout)
A synthetic dome boss with a 10 mm through-bore full of stock (stock top above the boss) and the 9.525 ball: the finish
emits 0 entries with live depth > 0.5 (replay LiveStock over the emitted moves, as test_fe5t does), AND the skip report
lists the bore (one cluster whose centre is within 1 mm of the bore axis). Keep every FE5/FE5e/FE5e-t/FL1b test green.

## engine/FE5f_RESULTS.md (required)
(1) line count (`git diff --numstat e773afa`, non-test vs test); (2) change with file:line, tests with exit codes,
fail-on-e773afa proof; (3) anything not done and why. Then stop.
