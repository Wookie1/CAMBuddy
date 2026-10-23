# Task RR1c-4b: bore entry for top-down levels + merge fragments within D. Build, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only. If an existing test still conflicts, STOP and write that in the results file.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ or opencode.json; no leave/margin change; T20 values stay connector defaults. Edit engine/rest_rough.py and
engine/test_engine.py only.
BUDGET: <= 60 changed non-test lines vs c807939 (`git diff --numstat c807939 -- engine/rest_rough.py`, adds + dels),
STOP at ~80. FRESH session, HARD CAP 2 h. Never print NGC/G-code or large outputs; rg / sed -n line ranges, never read
big files whole. Tests ONLY via the small-test lane
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). The engine tests are NOT pytest: call them with the VibeCAD python, e.g.
`slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import
engine.test_engine as t; t.test_rr1b_rest_rough_synth_pocket()"`; the full suite is
`/Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_engine.py`. NO Core Front engine or zmap job.
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at c807939 (RR1c-4 WIP). Read engine/TASK_RR1c4.md and
engine/RR1c4_RESULTS.md first: its two conflicts (A synth pocket, B curved band) are what this round resolves.

## A. Bore entry (every multi-level zone)
1. The zone's helix (the same 2 deg helix + floor circle d46a04a already emits, helix_entry ~L450) runs from the top
   down to the LOWEST legal level, as a BORE. Its time does not grow.
2. Then rise inside the bore to the top level. Cut each level top-down, rings inside-out starting from the bore.
3. Enter each lower level by descending INSIDE the bore. Each descent is a real move: it must pass the exact CL check
   and the ball ZB floor measured on the LIVE stock (live depth <= 0.5). Never assume it is air.
4. A zone with no legal helix site fails closed and is reported, as now.
## B. Fragment merge distance
Merge a fragment into a zone when it lies within the tool DIAMETER D (not R) of it, ONLY if the bridge from fragment to
zone is CL-legal and stock-clear (link_clear) at the cutting Z. Otherwise it becomes a mini-zone (cut only where the
ladder finds a legal entry). Fragments farther than D: mini-zone, or listed in fragments_dropped with a reason.

## Tests (engine/test_engine.py) - each NEW test must FAIL BY ASSERTION on d46a04a (`git archive d46a04a`, never checkout)
- Synthetic plateau (like the Core Front's 3.26 mm block over a flat floor, with a lower legal entry pocket): max axial
  engagement a at cutting feed <= stepdown + 0.05, and the ring ae within the load bar (ZE2B via verify/zmap.py,
  read-only use, padded part grid: 0 mm over 2.286 at cutting feed, 0 full-width windows).
- Closed pocket with >= 3 levels whose lower levels are entered through the bore, with ZB 0 (no axial entry deeper than
  0.5 into live stock) and exact clcheck 0.
- The two existing conflict tests (test_rr1b_rest_rough_synth_pocket, test_rr1c3_curved_thin_band_centre_line) pass
  UNCHANGED; full engine/test_engine.py green.
Run every test yourself and paste the exit codes.

## engine/RR1c4b_RESULTS.md (required)
(1) line count; (2) change with file:line; (3) PASTED exit codes of every test run and the fail-on-d46a04a output;
(4) anything not done. Then stop.
