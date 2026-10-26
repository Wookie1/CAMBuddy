# Task BS1a4d8: no emitted band piece arrives sideways at cutting feed into standing stock unless that arrival is simulated and within the limits. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d8" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. CAUSE FIRST: write item 0 there before any code change.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py, engine/rough.py and engine/test_engine.py only.
BUDGET: <= 40 changed non-test engine lines vs f81eaa7; STOP and report at ~55. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= BS1a4d7 f81eaa7 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 21): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0, test_bs1a4d7_sub1mm_tail_merges_not_dropped, plus your new test.

## Facts (supervisor, CF rough on 36319bf = BS1a4d6d, judged by its own zmap; pickled engine spies + the ae2 dump)
Program: /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/d6dcf2/cf.ngc
(read-only; ae2.json, zmap.json, cf_stats.json and spies.pkl {ladder, emitted, moves, stats} beside it; moves[i] is
program line i + off, off = first motion line). Gates all clean (gouges/rapid/axial/outside/holder/over_flute/clcheck 0)
but these cutting-feed (F3429) windows are judged far over 2.44:
- line 64232 -> 64233, Z 42.354: ONE G1 F3429 from (26.7568, 13.4273) to (1.6689, 10.7822) = a 25.2 mm straight move
  between two pieces, no lift. Judged ae_eff 9.319 mm, a 18.61. Line 64232 itself: the ramp/helix ends at (25.6961,
  12.3666) F1270, then a 1.5 mm F3429 feed-in to the piece start (26.7568, 13.4273) - judged 8.486, a 18.61.
  (26.7568, 13.4273) is failed_region_emitted shrink0.55 max_ae 126.25 (area units); (1.6689, 10.7822) is
  credit_fallback plan0_splitbore.
- line 233705 -> 233706, Z 40.289: ONE G1 F3429 (22.6527, 7.056) -> (1.5693, 10.8034) = 21.4 mm, judged 10.586;
  then 233710 6.584, 233714 4.204.
- line 82421 -> 82422, Z 42.354: ramp ends (0.9287, 9.5767) F1270, then G1 F3429 3.75 mm sideways to the shrink1 piece
  start (-2.8094, 9.3176); 82423 judged 6.304, 82442 3.712. Same shape at 258544 -> 258545 (Z 40.289): 258546 6.333.
- line 104980 / 104962, Z 42.926, piece (24.0234, 6.3083) replan0_shrink0.4: judged 2.741 / 2.639.
- 7 failed_region_emitted starts are NOT an emitted G1 at their Z: (1.818, 9.996) and (-2.809, 10.118) Z 42.354,
  (-46.465, -40.087) and (23.229, 6.407) Z 42.926, (1.716, 10.017) and (-2.806, 10.207) Z 40.289 (+ one more) - entered
  elsewhere (rotated pc[1]?) - find where each was actually entered.
- Engine prediction for those windows (engine window located by travel along the simulated path; width = area /
  window travel): 64233 engine 0.000 vs judged 9.319, 233706 0.000 vs 10.586, 64237 0.000 vs 8.071 - the 25 mm link is
  NOT in any simulated path (the sim starts at the piece's P0); 82423 4.496 vs 6.304, 258546 5.246 vs 6.333;
  64232 2.935 vs 8.486. The spy did not record entry=/approach kwargs: instrument them yourself.
- Two window-count mismatches seen (engine 13 vs zmap 14, 40 vs 41, 15 vs 16) on emitted band regions - check whether
  that is d6d's approach window.
## Items (coordinator spec)
0. CAUSE FIRST, per arrival (64232/64233, 233705/233706, 82422, 258545, 104980, and the 7 starts not found): how the
   piece is entered (own-region more_pcs entry, rotated pc[1], inter-piece link, entry ladder), WHICH code emits the
   straight cutting-feed move into it (file:line), which _simulate call (if any) predicted it, with which entry= and
   approach, and why window 0 missed it. Add entry=/approach logging at EVERY _simulate call site (band.py and rough.py)
   for this - it also settles the off-by-one window counts below. Measure on the real CF inputs (the CLI recipe below), not by reading.
   CF rough recipe (same as the supervisor's): engine.cli rough --step samples/core_front_setup.step --stock -128.651
   128.651 -82.55 82.55 0.0 60.96 --tool flat:12.686:0.0 --floor 24.765 --leave 0.381 --stepdown 19.05
   --optimal-load-mm 2.032 --stepup 1.905 --hf /Users/James/ai-sandbox/stevecam/out/core_front_setup_hf.npy --min-rest
   0.5 (a FULL CF rough takes ~15 min: at most ONE full run, through slot_m4.sh; prefer a crop, item 2).
1. Rule: a move at cutting feed between pieces or regions (and a piece's arrival feed-in) is allowed ONLY if it is
   simulated through the LIVE stock (approach included) and predicted within the limits. Otherwise it becomes: lift ->
   rapid at clearance -> a proper entry at the next piece (enter_at with a helix or ramp at entry feed, as for any
   region). The predictor mirrors whatever is emitted.
2. NEW test: L does not reproduce this, so build a small CF CROP scene around the failing arrivals - stock window and Z
   range around (1.67, 10.78) and (26.76, 13.43) at Z 42.354, from the CF inputs (out/ fixtures, never committed) -
   deterministic and fast (< ~2 min). Assert the judged (verify/zmap) first-window ae_eff <= 2.44 for every own-region
   or rotated piece there. The crop MUST contain the 64232 -> 64233 link case. Assert: no cutting-feed move on the crop
   has a judged window over 2.44, and the inter-piece transition there is a lift plus an entry (measured from the
   emitted moves). Print the values. Mutation (scratch copy, revert): restore the straight link; the test must fail by
   the measured ae_eff (~9.3) and a (~18.6). Record both.
## engine/BS1a4d6_RESULTS.md "BS1a4d8": item 0 per arrival, the change with file:line, line count vs f81eaa7, PASTED exit
codes of all at-risk tests + the new test, the mutation output, git diff --numstat. Then stop.
