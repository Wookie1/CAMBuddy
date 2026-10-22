# Task RR1a: the rough fails CLOSED on any non-flat tool. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/. Edit engine/cli.py (and engine/rough.py only if the guard belongs there), connector/ only if it accepts a ball
for adaptive_rough, and tests (engine/test_engine.py and/or connector tests). Do NOT touch opencode.json. Budget ~20
changed lines plus tests. Report ONLY numbers you produced this session under /Users/James (worktree
/Users/James/ai-sandbox/stevecam-rr1a, branch rr1a = main). Cite only files that exist and commits `git log` shows.
Long runs: nohup + short polling; never end your turn while one runs. ONE-JOB SLOT - every heavy run via
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
If blocked, write the question into engine/RR1a_RESULTS.md and stop.

## The bug (RR0, verified by the supervisor)
`engine.cli rough --tool ball:9.525` parses the kind (engine/cli.py parse_tool ~line 15, rough_main ~line 468) but passes
only dia/2 and corner to rough(); corner defaults to 0.0, so big_cutter/actual_cutter (engine/rough.py ~95-109) build an
ocl.CylCutter: a ball request silently becomes a FLAT rough.
## Change
The rough refuses any tool kind other than flat (and bull, if bull is genuinely supported end to end - check: bull ->
BullCutter with its corner; if supported, keep it) with a clear error message on stderr and a NONZERO exit, before any
work. Also check what the connector does when STEVE asks for adaptive_rough with a ball tool (connector/catalog.py
tool_type, connector/runner.py): it must REFUSE with a clear message (validation error), never run a flat rough.
Report what it does today and what it does after.
## Tests
A CLI test: `rough --tool ball:9.525 ...` exits nonzero with the message and writes no program; flat still works. A
connector test for the ball refusal if the connector path is touched. Each must fail on main's code.
Suites green via the slot (fixtures, test_engine, test_finish, pytest verify connector engine/test_post.py), real exit
codes. Write engine/RR1a_RESULTS.md. Then stop.
