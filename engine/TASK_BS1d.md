# Task BS1d: band trigger for overloaded ring stretches beside standing stock + counted a2d drop. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only if needed.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change; never
post-edit Adaptive2d's cutting moves; no Adaptive2d setting changes (helix stays 0.8 x 2 tool_r; NO helix ladder / fallback).
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1d/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS, SPIKE_MM, MIN_SLIVER, FW_TRIGGER).
RESULTS: create engine/BS1d_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code
and the stats it printed. (Cause given below; no cause section needed.)
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py and engine/rough.py only (the red tests are already committed in engine/test_engine.py).
BUDGET: <= 60 changed non-test engine lines vs main 605fffa (`git diff --numstat 605fffa -- engine/band.py engine/rough.py`);
STOP and report at ~90. FRESH session, HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1d,
branch bs1d at the commit carrying this brief (= main 605fffa + red tests 6a9c099 + brief).
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Run a test like this (no pytest in VibeCAD python): /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_engine as t; t.<test_name>()"
RED TESTS (must turn green): test_bs1d_overload_band_on_standing_strip, test_bs1d_a2d_drop_counted.
AT-RISK (must stay green; run ALL and paste exit codes): test_bs1a_straight_channel, test_bs1a_lshaped_channel,
test_bs1a4b_windows_align_zmap, test_bs1a3_no_band_after_a2d, test_bs1a4d2b_centred_entry_bore, test_bs1a4c_fix_no_post_entry_helix,
test_bs1a4d8e_inrun_guard_skips_planned_paths, test_bs1a4d9_no_entry_at_stale_q4, test_hb1v2_flat_floor_circle_after_helix,
test_rough_synth_pocket_repro, test_rough_testblock_r2, test_rough_testblock_r4, test_dt1_synthetic_rough_twice_identical,
test_hr1_rings_after_a2d, test_rough_rt_entries, test_se2_side_entries_only_through_cleared,
test_rr1c5c_closed_pocket_bore_entry_no_deep_axial, test_rr1c4c_floor_circle_over_rising_surface,
test_rr1c5b_varying_width_band_fronts, test_rr1c5b_open_edge_proud_block, test_rr1c5b_fully_walled_band_bore_seed,
test_fi1_entry_feedin_within_limit, test_rr1b_rest_rough_synth_pocket.

## Facts (supervisor, measured on main 605fffa)
- band.channel_regions (band.py ~:380) plans trochoid bands ONLY where a ring's engine ZE2 replay on the live stock (after
  the level's a2d) reaches full width: the mark loop (~:416-428) skips every window with `wins[w] < fw_min`
  (fw_min = FW_TRIGGER 0.85 x D = 10.78 mm). Overloaded-but-not-full-width windows are left to the ring.
- Core Front Z 47.224 (a plateau level): a strip ~3.7 mm beyond leave, 13.74 mm high, stands beside two hug rings. Their
  engine windows peak at 6.25 / 7.25 mm (n >= 10.78: 0; n > 2.44: 50 + 42), so 0 bands are planned and zmap counts 91 ring
  windows over 2.44 there. Same class at 40.289 / 42.354 (bands of 1.6-1.8 mm beyond leave).
- RED scene (test_bs1d_overload_band_on_standing_strip, `_bs1d_ledge_tris`): 60 x 50 pocket, 18 mm walls, 3.7 mm ledge
  (top Z4) along the -y wall. At Z 4.381 the ring along that wall gets 43 over-2.44 windows at cutting feed (zmap max ae
  7.86), engine replay max 17.25 with 48 windows > 2.44; band regions 0. Gates 0.
- Adaptive2d StartPointNotFound is skipped silently in _run_a2d (rough.py ~:952). Measured on the drop scene: 1 SPNF, the
  only outer fully dropped; the BS1a band step then clears that channel (4 band regions) - that stays as is.
- Reference only (do NOT copy its ladder): `git show caa34bd:engine/rough.py` has a counted-SPNF _run_a2d (fresh
  `_a2d_new` instance per Execute; an outer is "fully dropped" when its alone-run at the primary helix yields no region).

## Items (coordinator spec)
1. Counted a2d drop: in _run_a2d count every StartPointNotFound result of the primary call into stats["a2d_spnf"] (int,
   summed over the run, initialised 0 in rough()'s stats). When the primary call has any SPNF, list each FULLY dropped
   outer (alone at the primary helix, fresh Adaptive2d instance, no running region) in stats["a2d_dropped_outers"] as
   {"z", "polygon"} (initialised []). Nothing else changes: the returned regions stay exactly main's; levels without SPNF
   make no extra a2d call.
2. Overload trigger in channel_regions: besides today's full-width trigger, ALSO mark a ring sample (same lead-in/out
   FW_LEAD_PTS) when its window ae > SPIKE_MM (2.44) AND the live stock beside the ring stands: on the channel side (the
   side away from the wall, i.e. where CL room exists), the stock top at distance tool_r + leave + 1.0 mm from the ring
   centre is > z + 2.032 mm (ae target). Name the two numbers as module constants (e.g. OVL_BAND_MM = 1.0,
   OVL_STAND_MM = 2.032) next to FW_TRIGGER. Everything downstream (centre line, MIN_SLIVER, shrink_ladder, gates,
   entries, done-marking, failed_region_emitted) is unchanged: the new stretches go through the SAME trochoid planning.
3. Levels/rings where neither trigger fires must produce byte-identical programs (test_bs1a3_no_band_after_a2d etc.).
## engine/BS1d_RESULTS.md: the change with file:line, line count vs 605fffa, both red tests' printed numbers, PASTED exit
codes of the red tests and all at-risk tests, git diff --numstat. Then stop. (Supervisor verifies from committed code,
runs a mutation (new trigger removed), the full engine suite and the Core Front judge: gates incl. holder/axial, clcheck,
overload windows/mm, per-level ring windows with max ae, band count, FW, cycle vs main 5,326.6 s.)
