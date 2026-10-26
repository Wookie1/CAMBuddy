# Task RR1c-3: thin strips cut along their centre line; levels top-down. Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests - existing tests'
assertions and tolerances unchanged; no skip path that makes anything pass by cutting nothing. Do NOT edit verify/,
opencode.json, engine/entry_depth.py, engine/test_entry_depth.py. Edit engine/rest_rough.py (engine/cli.py only if a
parameter is needed) and engine/test_engine.py. The three through-bores (centre-south ~(-0.5, -36.1), corners
~(+-107.3, 50.8)) are OUT OF SCOPE - leave their no-entry report as it is.
BUDGET: <= 150 changed non-test lines vs e206c56 (`git diff --numstat e206c56 -- engine/rest_rough.py engine/cli.py`, adds +
dels), STOP at ~200. HARD CAP 2 h; if the same test fails ~3 times with no new idea, stop and write the results file.
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b. READ engine/RR1c3_DIAG.md FIRST (5aa0962: causes with
file:line and probe numbers). Cite only commits that exist (`git cat-file -t`). NEVER print NGC/G-code or large outputs;
rg / sed -n line ranges, never read big files whole. Small tests via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4; VibeCAD python for engine tests, /opt/homebrew/bin/python3 for pytest). NO Core Front engine or
zmap job - the supervisor runs the Core Front chain judge after you.

## Change (order)
1. Thin level strips (max distance < ae/2): cut them ALONG THEIR OWN CENTRE LINE - the ordered polyline(s) of the distance
   field at c = max(maxDz/2, CELL/2) from march_level (rest_rough.py ~614-638) - replacing the axis-aligned zigzag_runs
   fallback for these strips (zig-zag stays only for runs >= D as briefed). Every point through the same exact CL check as
   the passes (cl_ok_path).
2. Levels TOP-DOWN after entry (rest_rough.py:523-614): enter at the HIGHEST level the ladder can enter, cut it, then step
   down level by level - each deeper level re-tried through the one `enter()` ladder from the level just cleared - so the
   bays' deeper narrow levels (t 36.965, 36.365; DIAG (b)) are cut, not skipped.
3. Nothing else (no bore work, no ladder changes beyond using it per level).

## Tests (engine/test_engine.py) - each must FAIL BY ASSERTION on e206c56 (git archive extract, never checkout)
- a CURVED thin band (an arc-shaped 1-2-cell strip on a sloped wall, e.g. a quarter ring) is cut: cut-feed length along it
  >= 80% of its centre-line length, validate_exact 0, every entry <= 0.5;
- a bay whose deepest level is a narrow groove under a wider upper level: after the rest-rough, the LiveStock depth at the
  groove floor is <= 0.5 (target 0.2 + tolerance) - not just the upper level cut.
Keep every RR1a/RR1b/RR1c/RR1c-2 test green; run engine/test_engine.py and engine/test_finish.py fully at the end.

## engine/RR1c3_RESULTS.md (required)
(1) line count (`git diff --numstat e206c56`, non-test vs test); (2) per item: change with file:line, tests with exit
codes, fail-on-e206c56 proof; (3) anything not done and why. Then stop.
