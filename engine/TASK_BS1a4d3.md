# Task BS1a4d3: (e) a cutting-feed link that is not stock-clear on the cut-time stock is checked as a cut. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change. Edit
engine/rough.py, engine/band.py (only to reuse _simulate) and engine/test_engine.py only. Do NOT overwrite
engine/BS1a4_RESULTS.md - APPEND your section to it.
BUDGET: <= 30 NEW non-test lines vs d4ced08 (`git diff --numstat d4ced08 -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~45. FRESH session, HARD CAP 2 h (run `date` at start and write it in the results file). Worktree
/Users/James/ai-sandbox/stevecam-bs1a4d2b, branch bs1a4d2b at the commit carrying this brief (= BS1a4d2b d4ced08 +
this brief).
AT-RISK existing tests (run these plus your new test; NOT the full suite): test_bs1a4d2b_centred_entry_bore,
test_bs1a4d_credit_real_bore, test_bs1a4d_credit0_lightest_option, test_bs1a4b_windows_align_zmap,
test_bs1a4c2_band_chord_cl_checked, test_bs1a_lshaped_channel, test_hb1v2_flat_floor_circle_after_helix,
test_bs1a4c_fix_no_post_entry_helix, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical.

## Facts (supervisor inventory of cutting-feed link emit sites in rough.py @ d4ced08)
Covered today (stock-clear on the cut-time stock, or inside a swept bore) - leave them alone:
- enter_at step 1 tool-down link (~:1679): corridor_ok + stock.link_clear(.., z) + rise_clear.
- Adaptive2d "linkclear" at-depth link / dlink (~:2311): link_clear(z) + link_clear(z+lift) + _strip_engage <= 2.438.
- helix_entry return feed (~:1385): must lie inside the swept bore (containment check); band bores are centred.
NOT covered - these three emit cutting-feed moves through stock that is not verified clear at Z:
1. Adaptive2d feed link "flink" (~:2340-2356): only link_clear at z + lift; at Z it may shear stock (top > z + 0.05),
   gated only by _strip_engage <= 2.438 (one perpendicular chord), not by the window measure cutting moves use.
2. Clip bridge (~:2198-2215, emitted with the next run ~:2279): a chord <= clip_bridge_mm (5 mm) across a forbidden
   sliver, checked only for island legality (isl_ok3) - no stock check at all.
3. offset_down feed-in at depth (~:1510-1523) when find_shift(.., flank=True) (RP2 open side entry): the feed-in may
   engage this level's stock with the flank; it is never measured as a cut.
## Change
Each of the three: if the link is NOT stock-clear on the cut-time (live) stock at its Z (stock.link_clear(.., z) false),
it is checked AS A CUT with the same window measure the band planner uses for cutting moves (band._simulate on the live
stock at Z, credit 0). If its max window reads over 2.44 (AE_SPIKE), it is not emitted as a link: lift and re-enter
through enter_at's ladder (enter_at stays the ONLY entry). Links that read <= 2.44 stay as cuts (so cycle time does
not balloon). Count per site in stats: links checked, links converted to lift + re-entry.
## Test (engine/test_engine.py) - must FAIL BY ASSERTION on d4ced08 (`git archive d4ced08`, never checkout)
- NEW: a scene where at least one of the three link kinds crosses standing stock at Z with a MEASURED bite (replay the
  emitted link moves on the live stock - e.g. band._simulate or verify.zmap from the test - and read the max window)
  over 2.44 on d4ced08; with the change every emitted cutting-feed link reads <= 2.44 or was converted. The assertion is
  on the measured bite, not on a stats key.
## Report
Per site: links checked, converted to lift + re-entry; cycle time (moves length or estimated time) of the test-block
and L-channel scenes before/after.
## engine/BS1a4_RESULTS.md - APPEND section (16) BS1a4d3: change with file:line, line count, the Report items, PASTED
exit codes of the at-risk + new tests and the fail-on-d4ced08 output. Then stop.
