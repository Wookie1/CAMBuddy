# Task RR1c5g: one grid origin for both sims of test_rr1c5d_front1_chord_offset_slabs, then a scene that is deep ON THAT GRID. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: change ONLY test_rr1c5d_front1_chord_offset_slabs (its scene and its guard sim's origin) and _rr1c5b_zmap_gate's
origin computation (moved into ONE shared helper both use). Thresholds (2.286, a > 0.5, 0.9 x feed) and the vacuity
assert stay exactly as they are. Do not touch any other test.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; NO engine change (test/scene only).
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-rr1b/scratch/ - never /tmp.
RESULTS: APPEND a section "RR1c5g" to the END of engine/RRA_RESULTS.md. Never rewrite, move or delete earlier sections.
CAUSE FIRST: copy the facts table below into that section before any change.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/test_engine.py only. BUDGET: <= 25 changed test lines vs ec73844 (helper + scene). FRESH session,
HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit carrying
this brief (= RR1c5f ec73844 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK: test_rr1c5d_front1_chord_offset_slabs, test_rra2_deep_top_scope, test_rra3_straight_descent_scope,
test_rr1c3_bay_deep_groove_top_down, test_rr1c_thin_band_inpass_ramp, test_rr1c_narrow_pocket_side_entry,
test_rr1c5d_live_grid_fine_for_coarse_stock, plus every other test that calls _rr1c5b_zmap_gate (grep for it).

## Facts (supervisor, 2026-10-25, ec73844, scratch mutant of engine/rest_rough.py:760 `c = ae - hch`)
The test runs TWO zmap sims: the gate (_rr1c5b_zmap_gate, grid origin pad-corrected = -2.0) and the vacuity guard
(inline zmap.simulate with origin 0.0, 0.0). "deep" = windows at >= 0.9 x 2280 feed with a > 0.5.
| chord line | gate sim: deep / max a(feed) / over 2.286 / full-width | guard sim: deep / max ae_eff / over / full-width / max a | test |
| c = ae - hch (clean) | 0 / 0.145 / 0.0 mm / 0 | 2 / 17.250 / 2.0 mm / 1 / 1.095 | PASS |
| c = ae | 0 / 0.019 / 0.0 / 0 | 0 / - / 0.0 / 0 / 0.082 | FAIL at vacuity guard only |
| c = ae + hch (worse) | 0 / 0.179 / 0.0 / 0 | 1 / 14.435 / 6.2 mm / 1 / 1.445 | PASS (gate never sees it) |
Cause: the guard's grid is shifted 2 mm against the padded part/stock, so the tool appears to cut stock that is not
there (14-17 mm "full-width" windows even on the clean tree). On the correctly registered grid the ec73844 scene has
NO deep cutting-feed window: the test is still vacuous, and a worse slab cannot fail it.
## Change
1. ALIGN FIRST: one shared origin helper (the pad-corrected one _rr1c5b_zmap_gate uses), called by both the gate and
   the guard - no second copy of the formula. Table the clean tree's numbers of BOTH sims (deep count, max a feed,
   max ae_eff) before and after; after the fix the guard's numbers must equal the gate's.
2. Then re-scope the scene against that grid so the GATE sim has >= 1 deep cutting-feed window and
   stats["rr_clmn_ladder"] >= 1, with the gate still passing on the clean tree. REPLACE ec73844's scene values
   (pocket A top 27.0) - do not stack a second change on them. Table the scenes you tried (gate deep / max a feed /
   max ae_eff / gate PASS?).
3. Mutation (scratch copy only, revert; real engine untouched): a WORSENING chord line (c = ae + hch, or whichever you
   measure as worse) must make the test FAIL AT THE SLAB THRESHOLD in the gate sim (the "ZE2B: ... over 2.286" or
   full-width assert), with deep count still >= 1. Paste the failure line and report slab value vs 2.286 and the deep
   count. Failing only at the vacuity guard does not count.
4. If no reasonable scene gives the gate sim a deep window, STOP: report the tried scenes table and change nothing
   beyond item 1.
## RRA_RESULTS.md "RR1c5g": the facts table, the before/after origin table, the scene table, the change with
file:line, PASTED exit codes of all at-risk tests, the mutation output, git diff --numstat. Then stop.
