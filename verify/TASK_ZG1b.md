# Task ZG1b: below_stock_bottom must use the TRUE stock bottom through --stock-in chains. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit engine/ or opencode.json; zmap stays independent of engine code (no engine imports in verify/, tests too); do NOT
regenerate or edit fixtures or fixtures/manifest.json.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-zg1/scratch/ (create it; untracked) -
never /tmp or /private/tmp.
CONTINUE: continue from your plan; don't stop before every new test exists and has run.
Edit verify/zmap.py and verify/test_zmap.py only. Results: APPEND a section "ZG1b" to verify/ZG1_RESULTS.md.
BUDGET: <= 30 changed non-test lines in verify/zmap.py vs the base commit, STOP at ~45. FRESH session, HARD CAP 2 h
(run `date` at start and write it in the results file). Worktree /Users/James/ai-sandbox/stevecam-zg1, branch zg1 at the
commit carrying this brief.
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK: test_stock_chain_cli (must pass UNCHANGED - it fails today), every test_zg1_* test,
test_ze2b_flat_and_bull_json_byte_identical, and every test in verify/test_zmap.py whose name contains stock, chain,
gouge, axial or strict.

## Facts (supervisor)
- ZG1 made below_stock_bottom a HARD gate (zmap.py ~1506 compares the tip against szmin of stock_box; main() exits 1,
  ~2599). With --stock-in and NO --stock, main() DERIVES stock_box from the saved grid (~2480):
  zmin = nanmin(stock_init) = the lowest REMAINING stock, not the stock's real bottom. test_stock_chain_cli's second
  program (legal cut to Z 4.5, true bottom 0.0) then fails "1.500 mm below the stock bottom Z 6.000".
- --stock-out today saves only the .npy (zmap.py ~2583). Chain scripts may write their own stock sidecar .json with
  x0/y0/cell keys; such a sidecar has no stock box.
## Change (coordinator decision)
1. --stock-out writes the ORIGINAL stock box (xmin..zmax of the starting stock: the --stock box, or the box read back
   from the --stock-in sidecar - never the remaining stock) into the stock sidecar `<stock-out stem>.json` under a key
   "stock_box" (merge into an existing sidecar's keys rather than dropping them). --stock-in reads it back, so the
   true bottom travels through the whole chain. An explicit --stock wins if both are given; if they disagree by more
   than 1e-6 mm in any coordinate, fail with a clear error naming both values.
2. No --stock and no sidecar box (old stock files): below_stock_bottom = "unknown". Never gate on a guess, never derive
   the bottom from nanmin(stock_init). The report/summary must say plainly the stock bottom check was not done and why,
   with next_step "pass --stock or regenerate the stock file with this version". (XY box derivation for the grid
   check may stay as it is.)
3. test_stock_chain_cli must pass UNCHANGED.
4. NEW test: a chained run (program 1 --stock-out, program 2 --stock-in, no --stock) where program 2 cuts below the
   TRUE bottom must fail; assert the measured depth below the true bottom (the value), not only exit 1.
5. NEW test: a stock file without a sidecar box gives "unknown" and does NOT exit 1 for that reason.
6. Mutation (scratch copy only, never committed): put back the nanmin(stock_init) bottom (or drop the sidecar read).
   Test 4 or test_stock_chain_cli must fail by a measured value; record which and the number.
7. The report's top-level keys stay as they are: test_ze2b_flat_and_bull_json_byte_identical's extra keys remain
   exactly {below_stock_bottom, part_mask} - the sidecar change adds no report keys.
## ZG1_RESULTS.md "ZG1b": change with file:line, line count, PASTED exit codes of at-risk + new tests, the mutation
output with its number. Then stop.
