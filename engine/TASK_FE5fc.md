# Task FE5f-c: finish FE5f-b (fragment trim) + never plunge a one-point pass. Fix, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances (test_fe5f_skip_bore_entries and
the two test_fe5fb_* tests from f2e0c10 included); add NEW tests (or new assertions inside your own new tests) only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; do NOT edit verify/ or opencode.json;
NEVER lower the ZB floor; NEVER skip anything that can be entered legally. Edit engine/finish.py and engine/test_finish.py only.
BUDGET: <= 55 changed non-test lines vs 1f499f5 (`git diff --numstat 1f499f5 -- engine/finish.py`, adds + dels; the
f2e0c10 WIP is already 27), STOP at ~70. FRESH session, HARD CAP 1 h 30. Never print NGC/G-code or large outputs; rg /
sed -n line ranges, never read big files whole. Small tests ONLY via the small-test lane
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). NO Core Front engine or zmap job. Worktree /Users/James/ai-sandbox/stevecam-fe5, branch fe5 at the
FE5f-b WIP f2e0c10 (fragment-only trim, engine/finish.py ~2320-2350; read engine/TASK_FE5fb.md for its goal).

## Why (supervisor's Core Front chain judge, FE5f 1f499f5)
- T20 finish: clean (ZB 0, gates 0, clcheck 0); skips only in through-holes. But the T33 rest (finish --rest-from) skipped
  274 whole passes: cut length 13924.8 -> 8194.4 mm, clusters outside every hole ~270 mm2 (e.g. near (30.2,1.0),
  (-33.1,0.9), (+-23..25,1.0), rows y=+-16.2). Whole passes lost far beyond the illegal fragments: FE5f-b's concern, real.
- T33 still plunges once: a ONE-POINT pass (G0 over, G1 straight down 1.06 mm into stock at (-23.64,1.68), straight up).
  `len(pth) < 2` (and `total < 1e-9`) passes skip every FE5e/FE5f check (finish.py ~2274 `n_unchanged`).

## Change
1. Finish FE5f-b: the WIP's two tests fail only because skip vertices off the grid (live depth inf) get recorded. Record
   ONLY on-grid (finite live depth) fragment vertices in fe5_skip_pts / the clusters; never invent a depth for them.
2. A pass with < 2 points or zero length whose entry live depth exceeds ZB_FLOOR_BALL is SKIPPED (counted in
   fe5_skipped_n, its vertex clustered) instead of plunged; shallower ones unchanged.

## Tests (engine/test_finish.py) - new tests must FAIL BY ASSERTION on 1f499f5 (`git archive 1f499f5` extract, never checkout)
- the two test_fe5fb_* tests and test_fe5f_skip_bore_entries pass unchanged;
- NEW rest-like case: one long raster pass whose first part is buried > 0.5 with no legal ramp at either end (a deep
  narrow pocket at each end, high rest stock), and a shallow legal middle: on 1f499f5 the whole pass is dropped (assert
  cut length kept / cells covered in the middle); after your change the middle is cut, the illegal fragments are not, and
  no emitted move enters stock deeper than 0.5 axially;
- NEW one-point pass case: a lone deep point is skipped (no straight plunge), a lone shallow point is unchanged.
Full engine/test_finish.py green at the end.

## engine/FE5fc_RESULTS.md (required)
(1) line count; (2) change with file:line; tests with exit codes; fail-on-1f499f5 proof; (3) anything not done. Then stop.
