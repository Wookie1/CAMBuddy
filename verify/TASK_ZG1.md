# Task ZG1: the zmap gouge rule's blind spot at the global part minimum. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit engine/ or opencode.json; zmap stays independent of engine code: no engine imports in verify/ (tests too).
Do NOT regenerate or edit any fixture or fixtures/manifest.json (that is the supervisor's job).
CONTINUE: continue from your plan; don't stop before the test exists and has run.
Edit verify/zmap.py, verify/heightfield.py, verify/hf_extent.py (only if needed) and verify/test_zmap.py only. Write
results to the NEW file verify/ZG1_RESULTS.md.
BUDGET: <= 30 changed non-test lines in verify/ vs the base commit, STOP at ~45. FRESH session, HARD CAP 2 h (run
`date` at start and write it in the results file). Worktree /Users/James/ai-sandbox/stevecam-zg1, branch zg1 at the
commit carrying this brief (= main 04eea8d + the test_block_hf_0.1 manifest entry 413a91a + this brief).
AT-RISK existing tests (run these plus your new tests; NOT the full suite): every test in verify/test_zmap.py whose
name contains gouge, ze2, ze2b, axial, strict or leftover, and test_zmap_matches_neutral in engine/test_post.py.
Engine-free pytest runs go through the small lane only if they run judges on real parts:
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.

## Facts (supervisor)
- verify/zmap.py analyze() (about line 2198): `bottom = np.min(part)`, `footprint = part > bottom + 1e-9`,
  `mask = valid & footprint`, gouge = mask & (stock < part - GOUGE_TOL). Every cell AT the global part minimum is
  excluded from the gouge rule, so a cut into a part face that sits at the part's lowest Z (a plate's floor face, a
  pocket floor at the minimum) is never reported as a gouge.
- heightfield.py fills cells with no part geometry with the shape's ZMin (same value as real part cells at the
  minimum), which is why analyze() cannot tell them apart today.
## Change
0. FIRST, before changing behaviour: list every fixtures/manifest.json entry and every archived judge input the
   tests use that lacks a part mask (.hit.npy), and for each say what the strict-everywhere fallback (item 1) would
   do to its verdict (read the tests and fixtures; you may run the current judge on them). Write this list in
   verify/ZG1_RESULTS.md first. If any currently-green fixture/test would turn red, STOP after the list and report;
   do not regenerate fixtures.
1. heightfield.py also writes `<stem>.hit.npy` (bool, same grid: True where part geometry was hit). analyze() uses it
   when present: gouge mask = valid & hit. When it is absent, fail closed: judge every valid cell strictly and put
   "part_mask": "missing" in the JSON (and "present" when used).
2. below_stock_bottom becomes a HARD gate (non-zero exit), reported with count, max depth, worst xy and first line.
## Tests (verify/test_zmap.py, new)
- Flat plate: a part whose top face is at the part's global minimum plus a cut 0.1 mm into it must be reported as a
  gouge (fails today); with a .hit mask and without one (fallback).
- Mutations, each must fail a test by MEASURED depth (mm), not a counter: (a) drop the hit-mask use; (b) drop the
  fail-closed fallback; (c) drop the below_stock_bottom gate. Apply mutations only in a scratch copy, never commit.
## verify/ZG1_RESULTS.md: the item-0 list first, then the change with file:line, line count, PASTED exit codes of the
at-risk + new tests and the mutation outputs. Then stop.
