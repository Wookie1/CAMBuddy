# Task FL1b: tighten FL1's floor exemption to the STOCK box. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/. Edit engine/finish.py (and only where the stock box must be passed in: engine/cli.py) and engine/test_finish.py
(add a test). Do NOT touch opencode.json. Budget ~15 changed lines plus the test. Report ONLY numbers you produced this
session under /Users/James (worktree /Users/James/ai-sandbox/stevecam-fl1b, branch fl1b = main 3e8b7b5). Long runs:
nohup + short polling; never end your turn while one runs. ONE-JOB SLOT - every heavy run via
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
If blocked, write the question into engine/FL1b_RESULTS.md and stop.

## Change
engine/finish.py floor_net() exempts CL vertices outside the PART bbox (the raster's half-stepover pad rows). Stock
exists between the part bbox and the stock box, so the exemption must apply only when the vertex is ALSO outside the
stock box (+ tool radius): a vertex below floor_z inside the stock box is dropped like any other. The finish already
receives the stock heightfield / box (--stock-from / runner); use that box. If no stock box is available, exempt nothing.
## Test
A part whose bbox is smaller than the stock box with a below-floor raster row between them: no feed move below floor_z
inside the stock box. Must fail on main's code (fl1's exemption).
## Judge (interim chain as engine/TASK_FL1.md on main; templates out/judge_template.py, out/zrough_template.py)
Finish + rest, before (main) vs after: feed moves below floor_z - 0.001 in the posted programs (own parser) = 0; ZB counts;
zmap gates 0; exact clcheck 0; coverage over the part surface ABOVE floor_z only (fraction of part cells with part Z >=
floor_z whose final stock is within 0.5 mm) before vs after; cycle. Suites (fixtures, test_engine, test_finish, pytest
verify connector engine/test_post.py) green, real exit codes, all via the slot. Write engine/FL1b_RESULTS.md. Then stop.
