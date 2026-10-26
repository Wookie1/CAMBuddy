# Task RR1c-2: fix the rest-rough entry ladder per engine/RR1c_DIAG.md. Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests - do NOT edit
the assertions or tolerances of test_rr1c_thin_band_inpass_ramp or test_rr1c_narrow_pocket_side_entry; no new skip path
that makes a test pass by cutting nothing (the thin band must actually be CUT). Do NOT edit verify/, opencode.json,
engine/entry_depth.py, engine/test_entry_depth.py. Edit engine/rest_rough.py (engine/cli.py only if a parameter is needed).
BUDGET: <= 200 changed non-test lines vs 885ee43 (`git diff --numstat 885ee43 -- engine/rest_rough.py engine/cli.py`,
adds + dels), STOP at ~250. Deleting dead ladder code is welcome. HARD CAP: 2 h. If the same test fails ~3 times with no
new idea, stop and write the results file.
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b (885ee43 = RR1c WIP; f23b97f adds engine/RR1c_DIAG.md - READ IT
FIRST, it names the file:line causes). Cite only commits that exist (`git cat-file -t <hash>`). NEVER print NGC/G-code or
large outputs (cmp, diff --stat, wc, head -3; rg / sed -n line ranges - never read a big file whole).
Runs: small tests via /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4, VibeCAD python for engine/test_engine.py, /opt/homebrew/bin/python3 for pytest). NO Core Front engine
or zmap job - the supervisor runs the Core Front chain judge after you.

## Order (stop after 3)
1. test_rr1c_thin_band_inpass_ramp passes unchanged: step-2 direction from the region's long axis when p0 has none;
   zigzag_runs fixed (a centre run for a strip narrower than ae; `ys` for vertical runs); a centre-line pass when the
   level region's max distance < ae/2 (no rings exist there). Every scored entry <= 0.5, validate_exact 0.
2. test_rr1c_narrow_pocket_side_entry passes unchanged with 0 gouge points: the step-4 descent column and EVERY feed-in
   point checked against the exact part CL (cl_ok / batched drop-cutter), never skipped because the stock is cleared.
   Generalise: every emitted entry move (descents, ramps, helix, floor circle, side entry, feed links) passes the same
   exact CL check as the passes; make the ladder ONE function used by both the zone entry and the per-pass links.
3. The 7 rapid collisions RR1b's Core Front program had (out/rr1b/zmap_rest.json at RR1b, program out/rr1b/rest_rough_cf.ngc):
   find each by reading zmap's first_line and the code path that emitted it (no Core Front re-run); fix with the existing
   rapid-rise + whole-G0 swept check against the LIVE stock (g0 in rest_rough.py). Add a synthetic test that reproduces
   the failing rapid shape and fails on 885ee43.
Keep RR1b's two tests green; run the full engine/test_engine.py and engine/test_finish.py once at the end.

## engine/RR1c2_RESULTS.md (required sections)
(1) line count: `git diff --numstat 885ee43` - non-test engine lines vs test lines;
(2) per item: what changed (file:line), test results with exit codes, fail-on-885ee43 proof for any new test (git archive
    extract - never checkout); for the rapid collisions: each one found, fixed or not, why;
(3) anything not done and why. Then stop.
