# Task BS1a4: a band region that fails its own gate is never emitted; the engine's windows match zmap's. Report first, then fix. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ or opencode.json; engine code NEVER imports zmap/verify (a test may import both); no margin/leave change; never
post-edit Adaptive2d's cutting moves; no feed reduction. Edit engine/band.py, engine/rough.py and engine/test_engine.py
only.
BUDGET: <= 60 changed non-test lines vs e5e783e (`git diff --numstat e5e783e -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~80. FRESH session, HARD CAP 2 h (run `date` at start). Never print NGC/G-code or large outputs; rg /
sed -n line ranges, never read big files whole. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). Engine tests are NOT pytest: call them with the VibeCAD python
(`.../python -c "import sys; sys.path.insert(0,'.'); import engine.test_engine as t; t.test_x()"`); full suite
`.../python engine/test_engine.py`. NO Core Front engine or zmap job - the supervisor runs the Core Front part.
Worktree /Users/James/ai-sandbox/stevecam-bs1a4, branch bs1a4 = main e5e783e (BS1a3 band trochoids merged).
Fixtures: out/test_block.stl, out/test_block_hf_0.5.*, out/test_block_hf_0.1.* (padded judge grid).

## Facts (found by BS1b-2e on the bs1b branch; same code as main here)
1. engine/band.py channel_regions shrink ladder (~L326-350 on main): shrink 1.0/0.75/0.55/0.4 breaks when
   `ss <= AE_SS and spike <= AE_SPIKE`; if NO level passes, the loop falls through and the last-tried path is EMITTED
   anyway (no reject branch). A gate that fails still emits.
2. band._simulate (~L131-190): its first window starts with zero length (the whole first-move disk goes into a
   zero-length window), so every engine window closes one move later than zmap's move-aligned windows
   (verify/zmap.py _ae2_windows ~L973-1029). A replica replay matched zmap's per-window AREAS exactly; only the
   boundaries differ - e.g. a 2.75 mm2 crescent over 1.03 mm reads 2.66 in zmap but about 2.0 in the engine, so the
   planner cannot see what the judge measures.

## Step 0 (report only, NO engine code change; written in the results file first)
On the TEST BLOCK, on main: list every band region emitted with no shrink level passing its gate: place, Z, area, the
best level's max ae from the engine (_simulate) and from zmap (the same moves through verify/zmap.py). For each, say
who would cut its stock if it were dropped (a later layer, the hug rings, the a2d remainder) and at what zmap load.
(The supervisor does the same on Core Front in the CF lane.)
## Fix 1
A region that fails its gate at every shrink level is NEVER emitted. Re-plan it with an existing fallback if the code
has one; otherwise drop it, leave its stock in the live stock every later planner reads (rings, link_clear, side
entries, a2d, re-mill), and record it in stats["bs1a_rejected"] (x, y, z, area, best_ae). Count
stats["failed_region_emitted"] (must be 0).
## Fix 2
_simulate's windows match zmap's exactly: the first move goes into a real, non-zero-length window (~L176-178), so every
window spans what zmap's does. Proof test: replay the same band moves through _simulate and zmap's engagement measure:
window boundaries identical, and the engine never reads more than 0.15 mm lower than zmap in any window, on the test
block. Report the max difference both ways.
## STOP and report (before any further change) if:
a dropped region's stock is unseen by any later planner; FW at cutting feed rises; overload rises; any gate or
clcheck is not 0; or an existing test fails.

## Tests - each NEW test must FAIL BY ASSERTION on e5e783e (`git archive e5e783e`, never checkout)
- Fix 1: a band case whose every shrink level fails its gate: the region is not emitted, is listed in bs1a_rejected,
  and its stock is still in the live stock afterwards (cut later or reported).
- Fix 2: the window-alignment proof above.
Full engine/test_engine.py green; run every test yourself and paste the exit codes.

## engine/BS1a4_RESULTS.md (required)
(0) the Step-0 table; (1) line count; (2) change with file:line; (3) PASTED exit codes + fail-on-e5e783e output;
(4) the max engine-vs-zmap window difference both ways; (5) anything not done. Then stop.
