# Task DT1: the rough's NGC must be byte-identical run to run. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/. Edit engine/ files only; do NOT touch opencode.json. Budget ~80 changed lines plus a test; STOP if it overruns ~100. Report ONLY numbers you
produced this session under /Users/James (worktree /Users/James/ai-sandbox/stevecam-dt1, branch dt1 = main 3e8b7b5).
Long runs: nohup + short polling; never end your turn while one runs. YOUR SLOT (you run on this Mac's own model, so
the memory rule applies): every run goes through
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command> > out/<log> 2>&1 &
TEST BLOCK AND PYTEST ONLY - you must NOT run any Core Front engine or zmap job (the supervisor runs the Core Front
run-twice check later). ENGINE_WORKERS <= 4 (slot_m4.sh caps it). NEVER print NGC/G-code contents or other large
outputs into your context: use cmp, diff --stat, wc and head -3 only.
If blocked, write the question into engine/DT1_RESULTS.md and stop.

## Evidence (supervisor)
Same code, same inputs, Core Front rough run twice: ~150 lines of G0 rapid ORDER differ at one level (around Z 39.6,
line ~202882); cuts identical. Cause candidates: nearest-neighbour ordering ties (engine/rough.py RT travel order over
`cand`, the a2d/ring region orders), set/dict iteration reaching output, thread/worker completion order (workers,
threads, Adaptive2d), float ties.
## Change
Deterministic tie-breaking in every NN ordering (break ties by a stable key, e.g. region index then coordinates) and
sorted iteration wherever set/dict/worker-completion order can reach the output. No behaviour change beyond tie order.
## Test / proof
Run the TEST-BLOCK rough (command in engine/TASK_HR1.md on branch hr1, git show hr1:engine/TASK_HR1.md) twice to two
different files: cmp must report identical; also add a unit test that runs a small synthetic rough twice in-process and
compares the emitted move lists; show main's code is NOT stable (find a pair that
differs, or explain if main happens to tie identically in 3 runs). Add a unit test that fails if a tie in the NN order
is resolved by iteration order (synthetic equal-distance regions). Suites green via the slot (fixtures, test_engine,
test_finish, pytest verify connector engine/test_post.py). Report the test-block zmap gates on the new program (all
0) and that its cut moves are unchanged vs main (same multiset of G1 lines). (Core Front is the supervisor's.) Write engine/DT1_RESULTS.md. Then stop.
