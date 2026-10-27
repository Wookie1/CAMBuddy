# Task FE5h: the entry-depth estimate never under-reads the true live stock (ZB). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate (ZB floor
ZB_FLOOR_BALL 0.5, RAMP_TRIGGER, CLCHECK, gouge checks unchanged); do NOT edit verify/ or opencode.json; engine code never imports
zmap/verify (TESTS MAY use verify.zmap); never move an existing pass point; never skip whole passes.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-fe5t/scratch/ - never /tmp.
RESULTS: create engine/FE5h_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and what it
printed. Start with a short CAUSE section.
CONTINUE: continue from your plan; don't stop before the red test (b) exists and has run on the UNCHANGED code, and every
test below has run.
Edit engine/entry_depth.py (and engine/finish.py only where it calls the estimator).
BUDGET: <= 60 changed non-test engine lines vs a49c8d3 (`git diff --numstat a49c8d3 -- engine/entry_depth.py engine/finish.py`);
STOP and report at ~90. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-fe5t, branch
fe5-trial at the commit carrying this brief (= FE5g a49c8d3 + brief).
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Engine test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_finish as t; t.<test_name>()"
Connector/verify test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"
RED TESTS (must turn green):
 (a) connector/test_connector.py::TestZg1connStockBottomE2E::test_tb_rest_chain_checks_stock_bottom (on a49c8d3: the T20 finish
     fails ZB with 2 axial plunges, max 1.130 mm at XY (-34.763, 34.744), finish.nc line 27680 - an ENTRY link: G0 XY, then a
     vertical G1 Z down at a pass start; ~8 min run).
 (b) YOU WRITE IT FIRST, as a NEW test in engine/test_finish.py, test_fe5h_entry_estimate_not_below_true_depth: a focused
     synthetic scene where a ball entry sits beside a near-vertical wall corner, with a live stock (stock_from) such that the
     engine's entry estimate at that entry reads <= 0.25 mm while the TRUE depth, measured INDEPENDENTLY on a 0.1 mm stock grid
     (the test builds it; it may use verify.zmap's simulation or its own exact disk/ball computation, never the engine's
     LiveStock), reads > 0.5 mm. Assert: every entry's true depth <= 0.5, and the estimate >= the true depth - 1e-6 at every
     entry the finish emits. Run it on the UNCHANGED code first and paste its measured numbers (it must FAIL there by them).
AT-RISK (must stay green, or change only as allowed here; run ALL, paste exit codes): the whole engine/test_finish.py
(test_fe5f_skip_bore_entries must still report 16 skips in the same cluster [0.0, -0.466]), engine/test_entry_depth.py,
verify/test_zmap.py -k "zg1 or ze2b", connector/test_tlg1.py, engine/test_engine.py tests test_rr1b_rest_rough_synth_pocket,
test_rr1c3_bay_deep_groove_top_down, test_rra2_deep_top_scope, test_rra3_straight_descent_scope,
test_rr1c5c_closed_pocket_bore_entry_no_deep_axial.

## Facts (supervisor + FE5g diagnosis, measured on a49c8d3 / 5d9a70a)
- Entry decisions (FE5e ramp / FE5f skip) use engine/entry_depth.py LiveStock: the COARSE engine stock (0.5 mm,
  stock_after_rough_engine.npy in the connector chain), resampled, stamped with the generated passes only.
- zmap judges against the 0.1 mm full-simulation stock. At the TB entry (-34.763, 34.744) the engine estimate read <= 0.25 (so a
  straight G1 drop-in was allowed) while zmap measures 1.130 (stock top ~29.13 vs tip 28.0). FE5g's diagnosis: footprint-boundary
  cells at a near-vertical ball surface (a cell at 4.7640 from the path vs R 4.7625 counts in one model, not the other) move
  ~1 mm of apparent stock top. Before FE5g this corner was entered via a lifted vertex at a higher Z, masking it.
- Run files for DIAGNOSIS ONLY (never a fixture): /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/fe5g_e2e/stevecam-home0/runs/1950/
## Items (coordinator spec)
1. Fix in entry_depth.py: the entry-depth estimate must NEVER be below the true depth on a 0.1 mm grid. Max-pooled coarse->fine
   resampling or a wall-adjacent margin are both allowed - name your choice and why in the results. ZB floor 0.5 unchanged.
2. Entries whose decision changes (straight -> ramp, ramp -> skip, ...) are listed in stats: "fe5h_changed_n" and "fe5h_changed"
   [{"x","y","z","before","after"}] (cap 400).
3. Everything else unchanged.
## engine/FE5h_RESULTS.md: CAUSE, the change (file:line), line count vs a49c8d3, red test (b)'s numbers before and after, red (a)
before/after, PASTED exit codes of every test above, git diff --numstat. Then stop. (Supervisor verifies from committed code:
mutation estimator reverted -> (a) and (b) fail by measured depth; full suites; CF chain.)
