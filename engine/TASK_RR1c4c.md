# Task RR1c-4c: every emitted rest-rough move kind checks exact CL + rest leave before emit. Fix, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ or opencode.json; NEVER loosen validate_exact's 0.005 tolerance or the rest leave. Edit engine/rest_rough.py
and engine/test_engine.py only.
BUDGET: <= 25 changed non-test lines vs d08749a (`git diff --numstat d08749a -- engine/rest_rough.py`, adds + dels),
STOP at ~40. FRESH session, HARD CAP 2 h (run `date` at start). Never print NGC/G-code or large outputs; rg / sed -n
line ranges, never read big files whole. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). Engine tests are NOT pytest: call them with the VibeCAD python
(`.../python -c "import sys; sys.path.insert(0,'.'); import engine.test_engine as t; t.test_x()"`); full suite
`.../python engine/test_engine.py`. NO Core Front engine or zmap job. Worktree /Users/James/ai-sandbox/stevecam-rr1b,
branch rr1b at d08749a (RR1c-4b; read engine/RR1c4b_RESULTS.md).

## Facts (supervisor, Core Front rest-rough from d08749a)
The rest-rough refused to post: validate_exact (rest_rough.py:210) found feed points below the exact part CL + rest
leave 0.2. An instrumented re-run dumped all 64 sampled points: every one is at RAMP feed, ABOVE the exact CL but up to
0.115 mm INSIDE the leave - a helix end + floor circle + bore-descent link at (-22.4..-26.2, 19.5..21.7) Z 42.616
(moves 3021-3047, 4030-4031) and a floor circle at (-32.8..-36.4, -33.3..-36.4) Z 42.548 (moves 4262-4274).
Cause: the emit-time helpers cl_ok (rest_rough.py:360) and cl_ok_path (:368) check the exact CL only
(`v <= z + 0.005`), not CL + rest leave, while validate_exact checks CL + leave. Every entry/link site uses them
(:393, 421, 429, 454, 459, 492, 668, 694, 701, 796, 841), plus the fragment bridge's own batch_drop check (~L92 of the
RR1c-4b diff). Where a floor circle or link overhangs a rising part surface, it passes the helper and fails the
whole-program check.

## Change (close the bug class)
Every emitted move kind - ramps, side entries, helices, floor circles, bore descents and links, fragment bridges,
mini-zone entries, feed links - must pass the SAME exact CL + rest leave check (the validate_exact rule, 0.005
tolerance) before it is emitted. A move that fails is not emitted: it falls back exactly as a CL failure does today
(next ladder step, smaller floor circle, skip-and-report, or no_entry). Prefer one shared rule over per-site edits.

## Tests (engine/test_engine.py) - each NEW test must FAIL BY ASSERTION on d08749a (`git archive d08749a`, never checkout)
- A synthetic zone whose helix / floor circle (or bore-descent link) would overhang a rising part surface so it sits
  above the exact CL but inside the rest leave: after the rest-rough, validate_exact on its moves gives 0 (and the
  zone is either cut legally or reported), where d08749a emits points inside the leave.
- Every existing test passes unchanged; full engine/test_engine.py green. Run every test yourself, paste exit codes.

## engine/RR1c4c_RESULTS.md (required)
(1) line count; (2) change with file:line; (3) PASTED exit codes + fail-on-d08749a output; (4) anything not done.
Then stop.
