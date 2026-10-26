# Task BS1a4d8b: no straight cutting-feed move between an entry and a path, or between pieces, unless simulated and within limits. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d8b" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. CAUSE: given below (supervisor-measured); confirm it in the results by reading the named code, no new full CF run.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/band.py, engine/rough.py and engine/test_engine.py only.
BUDGET: <= 50 changed non-test engine lines vs 63db90f; STOP and report at ~65. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= BS1a4d8 63db90f + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 22): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0, test_bs1a4d7_sub1mm_tail_merges_not_dropped, test_bs1a4d8_arrival_gate_reads_judge_skin, plus your new tests.

## Facts (supervisor, measured on the FULL Core Front with an instrumented scratch copy of 63db90f: every emitted move
## tagged with emit()'s caller line, every lnk_cut_ok logged including its early link_clear=True exit)
- CF line 64233, Z 42.354: a 25.2 mm G1 F3429 from (26.7568, 13.4273) to (1.6689, 10.7822), judged ae_eff 9.319, a 18.61.
  It is the FIRST point of a region's cut run, emitted by the band/region run loop at rough.py:2355
  (`for (x, y) in run: emit({"g": 1, ..., "f": cut_feed})`). Immediately before it: a helix entry by try_cand
  (rough.py:1291; F1270 helix, then try_cand's own 1.5 mm F3429 feed-in at rough.py:1396) to (26.7568, 13.4273) =
  that region's stored start res["start"] (q4). The region is ENTERED at q4, but its cutting path (the re-planned
  lightest option) starts at (1.6689, 10.7822). The entry candidate rule (rough.py:2090 / :2129, `pts0 =
  [res["start"], fc[0]]`) lets the entry target be q4 while the run starts at fc[0]; nothing checks the gap between
  the entry end and path[0] (the d_chord > 0.6 re-entry test only runs inside the loop's own gap branch).
- lnk_cut_ok was NOT called for that move. The only check touching its target was an enter_at route-1 'tolk'
  lnk_clear_true for a DIFFERENT segment (23.709, 13.047) -> (1.669, 10.782).
- CF Z 40.289: same site and same shape, (26.147, 7.590) -> (1.569, 10.803), 24.8 mm, judged 12.118 (full width).
- 8 more such moves into (1.6689, 10.7822) (19.3-20.5 mm) from the same site after pieces near (20.5-21.8, 6.9-7.1)
  were entered at their own q4; they judge ~0 only because earlier pieces already cut that corridor.
- BS1a4d8 (eps 0 in lnk_cut_ok, enter_at route 1, offset_down) did not touch this site.
## Items (coordinator spec)
(a) Fix the named site, PREFERRED way (keeps entry and path consistent): after a lightest-option re-plan, the
    region's entry target IS the emitted path's first point. Plan and credit the entry there - its own bore or ramp -
    with the predictor and the re-check simulated from that point; the helix at the stale q4 is then NOT emitted for
    that region. FALLBACK, only where entering at fc[0] fails its own checks: treat entry-end -> path[0] as a gap
    (lift -> rapid at clearance -> proper entry at path[0]).
    Plus an ASSERT-style guard in the run loop: it never emits path[0] at cutting feed farther than one step from the
    current tool position unless that move is a simulated link (this is (b)'s backstop at this site, and the test
    must measure it).
(b) Emission backstop: ANY straight cutting-feed move between two emitted pieces or regions (entry end -> path, piece
    -> piece, region -> region) that is not part of a simulated path is simulated against the LIVE stock right before
    it is written (eps 0, as lnk_cut_ok). If it is over the limits, or its a exceeds the level step with ae_eff >
    2.44, it becomes lift -> rapid at clearance -> proper entry (enter_at). Every emitter goes through this one check,
    whatever site produced the move. Count backstop firings in stats.
(c) TESTS: NO test may depend on a fixture derived from James's part (out/ Core Front data stays out of git, and a
    test that skips when its fixture is missing is a quiet bypass). Build a SYNTHETIC scene in code with the same
    features: two pieces/regions at one Z; a standing-stock corridor between them whose floor sits a hair (<= 0.05 mm)
    above Z; the emitter about to link them straight at cutting feed (e.g. a region entered at a stored start that is
    not its path's first point). Assert (verify/zmap) that the emitted program has NO cutting-feed window over 2.44
    on that link and that the transition is a lift plus an entry (measured from the emitted moves). Mutation (scratch
    copy, revert): backstop off AND (a) reverted -> the test must fail by the MEASURED overloaded link (ae_eff and a,
    printed). Also a second mutation with only the backstop off but (a) kept: say what it shows.
(d) The CF supervisor run afterwards will check CF lines 64233 / Z 40.289 - you do NOT need a full CF run.
## engine/BS1a4d6_RESULTS.md "BS1a4d8b": confirmation of the cause (file:line), the change with file:line, line count vs
63db90f, PASTED exit codes of all at-risk tests + the new tests, both mutation outputs, git diff --numstat. Then stop.
