# Task BS1a4d: failing credit-0 regions take the lightest option, credit = real bore, trochoids start inside the bore, links never cut. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code NEVER imports zmap/verify (tests may); no margin/leave change; no feed
reduction. Edit engine/band.py, engine/rough.py (band-region backing only) and engine/test_engine.py only.
BUDGET: <= 40 NEW non-test lines over 22cdff7 (`git diff --numstat <that commit> -- engine/band.py
engine/rough.py`, adds + dels), STOP at ~55. FOREGROUND RULE: run every command in the foreground and wait. FRESH session, HARD CAP 2 h (run `date` at start). Never print NGC/G-code or large outputs; rg /
sed -n line ranges, never read big files whole. Tests ONLY via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). Engine tests are NOT pytest: VibeCAD python, call the functions; full suite
`.../python engine/test_engine.py`. NO Core Front engine or zmap job. Worktree /Users/James/ai-sandbox/stevecam-bs1a4,
branch bs1a4 at 22cdff7 (BS1a4c, the supervisor's post-entry-helix removal 351ce50, and BS1a4c-2's
segment-sampled chord check). Read engine/BS1a4_RESULTS.md sections (10)-(12) and scratchpad/bs1a5/BS1a5_DIAG.md first.

## Facts (BS1a4c)
Under-read (zmap - engine) is 1.49 mm on the test block: 69 of the 70 windows over 0.15 come from band._simulate's
cell-centre disk sampling on the 0.5 mm stock grid missing partial cells that zmap (0.1 mm part grid) counts; 1 window
((6.72,-4.00), -0.25) comes from the credit being a start-centred disk while the real helix bore is off-centre plus a
floor circle. Over-read (engine - zmap) is up to +14.07 at the region's first window for the same bore reason.

## Change
(a0) FIRST: at emit, a credited band region that fails the credit-0 re-check (today `replan0_drop`, an unconditional
    drop in rough.py's band backing block) is exactly Fix 1's case - it fails its gate at every level under honest
    credit. Route it into Fix 1's lightest-option choice (shrink levels re-simulated with credit 0 on the live stock vs
    drop-to-ring, same ranking: FW windows at cutting feed, then max ae, then length over 2.44). Record it in BOTH
    lists: stats["credit_fallback"] keeps the act, stats["failed_region_emitted"] gets place, Z, area, option chosen,
    engine max ae. Never emit anything not CL-checked (no move after enter_at except the region's own cutting paths).
    Reuse band.py's shrink ladder (factor it into a callable rather than duplicating it). Extend the test
    test_bs1a4c_fix_no_post_entry_helix's scenario family with a NEW test covering this route.
(c) The credit is the REAL bore footprint: the swept cutter disk along the emitted helix path plus its floor circle,
    not a start-centred disk.
(d) The band trochoid STARTS INSIDE the real bore: its first loop is centred on the entry helix, or it starts at the
    bore edge - no cutting-feed move leaves the bore into raw stock. (BS1a5: on the test block the helix bores at its
    centre and the trochoid starts 1.5 mm away in raw stock; the 1.5 mm cutting-feed link between them takes an
    8.47 x 10.62 mm bite - the region's max window; step and radius do not move it.)
(e) Link rule (same class as link_clear): in rough.py, every feed link at depth must be stock-clear at its Z against the
    LIVE stock; otherwise it is a cut and must meet the load bar, or it goes through enter_at's ladder.
## Report
The test-block region (6.28, -2.08): its new max ae (engine and zmap) and the option chosen - it should now pass a
shrink level honestly. The two L-channel regions after (c)+(d): engine/zmap max ae and options.
## Bars
- Over-read and under-read (engine vs zmap, per window) are REPORTED with the max and the 5 worst windows; the 0.15
  under-read bar is BS1a4e's (0.1 mm resolution), not this round's.
- New assertions FAIL on e5e783e (`git archive e5e783e`, never checkout). Full engine/test_engine.py: every test green
  except possibly test_bs1a_lshaped_channel, which may still fail ON LOAD only (report its windows; it must pass by the
  end of BS1a4e). Run every test yourself and paste the exit codes.
## engine/BS1a4_RESULTS.md - add section (11) BS1a4d: change with file:line, line count, both max differences, the 5
worst over-read windows, the Report items above, PASTED exit codes + fail-on-e5e783e output. Then stop.
