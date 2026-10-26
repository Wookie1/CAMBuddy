# Task RR1c-3b: make RR1c-3's two new tests pass (they fail on its own code). Fix, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests - do NOT change
the assertions or thresholds of test_rr1c3_curved_thin_band_centre_line or test_rr1c3_bay_deep_groove_top_down (or any
other test); no skip path that makes a test pass by cutting nothing. Edit engine/rest_rough.py only. Do NOT touch
verify/, opencode.json, engine/entry_depth.py, engine/test_entry_depth.py.
BUDGET: <= 60 changed lines in engine/rest_rough.py vs 6913c3f (stop ~80). FRESH session, HARD CAP 2 h; if the same test
fails ~3 times with no new idea, stop and write the results file. Never print NGC/G-code or large outputs; rg / sed -n
line ranges, never read big files whole. Small tests ONLY via the small-test lane
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). NO Core Front engine or zmap job.
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at 6913c3f (RR1c-3, read engine/RR1c3_RESULTS.md and
engine/RR1c3_DIAG.md).

## Facts (supervisor's run of RR1c-3's own queued test job)
- fail-proof on e206c56: A fails-by-assertion "centre-line pass cut 2.4 mm of 47.1 mm centre line (want >= 80%)";
  B fails-by-assertion "only the entered level cut".
- on 6913c3f (RR1c-3): A FAIL "centre-line pass cut 0.0 mm of 47.1 mm"; B FAIL "only the entered level cut" (zone levels 1,
  entry_steps [2]). So neither the centre-line pass nor the top-down descent emits anything yet.
- every other test_engine test and all of test_finish pass.

## Do
1. Find (with a small instrumented call of rest_rough() on each test's synthetic input) why the centre-line paths and
   the descent levels produce no cut moves: paths empty, all rejected by cl_ok_path, entry refused, or the cut loop
   skips them. Fix the cause; keep every point through the exact CL check.
2. Both tests pass; the full engine/test_engine.py and engine/test_finish.py pass.
3. Justify test A's ">= 80% of the centre line": report how much of the 47.1 mm centre line is cut and what the rest is
   (e.g. unreachable end caps with numbers); if more than end caps is missing, say so.

## engine/RR1c3b_RESULTS.md (required)
(1) line count; (2) cause found (file:line), fix (file:line), tests with exit codes; (3) item 3's numbers; (4) anything not
done and why. Then stop.
