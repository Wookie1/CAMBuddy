# Task SP2: zmap per-move speed-up with EXACTLY the same results. Build, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; NO approximation of any
kind; verify/zmap.py imports NO engine code; do NOT edit engine/ or opencode.json. Edit verify/zmap.py and verify tests
only.
BUDGET: <= 40 changed non-test lines vs e5e783e (`git diff --numstat e5e783e -- verify/zmap.py`, adds + dels), STOP at
~60. FRESH session, HARD CAP 2 h (run `date`). FOREGROUND RULE: run every command in the foreground and wait; the
session ends when you end your turn. Never print NGC/G-code or large outputs. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(`/opt/homebrew/bin/python3 -m pytest verify -q`). NO Core Front job. Worktree /Users/James/ai-sandbox/stevecam-sp2,
branch sp2 = main e5e783e. Keep the change easy to merge with branch ze2b (a6fc8c7), which also edits verify/zmap.py:
read `git show a6fc8c7 --stat` and touch as few of its lines as you can.

## Facts (supervisor PR0 profile, test-block finish, --jobs 1)
zmap.py simulate (~L1194) is 118 s self of 225 s; per move it rebuilds a footprint grid: 2.36 M calls each of
np.meshgrid (34 s) and dz (~L435, 28.9 s), plus broadcast_arrays / copy / clip / max reductions (~40 s more).
## Change
Remove the per-move overhead WITHOUT changing any number: move positions are not on grid cells, so a per-cell dz
precompute is likely NOT bit-exact - if it is not, batch or vectorize the EXACT per-move arithmetic instead (same
operations, same order, same dtype). Prove equality, do not argue it.
## Proof
- The FULL zmap JSON output (every key, not only the gates) is BYTE-IDENTICAL before vs after, for each of these SMALL
  test-block programs (copied for you into out/sp2/, gitignored; run from the worktree root, small lane only):
    P1 finish: python3 -m verify.zmap out/sp2/prof_tb_fin.nc --part out/test_block_hf_0.1.npy --tool ball --dia 9.525
       --corner 4.7625 --stock -50 50 -40 40 0 38 --jobs 1 --out-json <json>
    P2 rough:  python3 -m verify.zmap out/sp2/prof_tb_rough.nc --part out/test_block_hf_0.1.npy --tool flat --dia 12.686
       --engage-max 2.438 --stock -50 50 -40 40 0 38 --jobs 1 --out-json <json>
    P3 rest:   python3 -m verify.zmap out/sp2/prof_tb_rr.nc --part out/test_block_hf_0.1.npy --tool ball --dia 9.525
       --corner 4.7625 --stock -50 50 -40 40 0 38 --jobs 1 --out-json <json>
  plus the verify tests green (`/opt/homebrew/bin/python3 -m pytest verify -q` - the verify suite only, never the
  engine suite). The supervisor runs the same cmp on the Core Front archives in the CF lane before merge. Write a small
  script that runs both versions (before = `git archive e5e783e` extract, never checkout) and cmp's the JSON.
- MEASURE FIRST: before any further optimisation, report the before/after wall time of P1 (the test-block finish) in
  SP2_RESULTS.md - the supervisor needs the realistic saving before any Core Front proof.
- Report the time per program before/after.
## verify/SP2_RESULTS.md: change with file:line, line count, per-program cmp results and times, PASTED exit codes.
Then stop.
