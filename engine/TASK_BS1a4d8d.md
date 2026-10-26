# Task BS1a4d8d: ONE entry function for re-planned starts and the in-run guard; the predictor mirrors every emitted entry. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit verify/ or opencode.json; engine code never imports zmap/verify (tests may); no margin/leave/feed change.
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-bs1a4d5/scratch/ - never /tmp.
LIMITS: No limit or floor is raised (ZE2B 2.286 mm, ZE2 2.44, ZA 0.2, ZB 0.5, AE_SPIKE, AE_SS).
RESULTS: APPEND a section "BS1a4d8d" to the END of engine/BS1a4d6_RESULTS.md. Never rewrite, move or delete earlier
sections. CAUSE FIRST for item (C): write it in the results before fixing it.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/rough.py, engine/band.py and engine/test_engine.py only.
BUDGET: TOTAL diff vs 337c44b (dc073a1 included) <= 80 changed non-test engine lines; STOP and report at ~100. FRESH session, HARD CAP 2 h (run
`date` at start). Worktree /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 at the commit carrying this brief
(= BS1a4d8c WIP dc073a1 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK (all 25): test_bs1a4d_credit0_lightest_option, test_bs1a_lshaped_channel, test_bs1a4d_credit_real_bore,
test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load, test_bs1a4d2b_centred_entry_bore,
test_bs1a4d4_credit_entry_matches_prediction, test_bs1a4d4_entry_pinned_to_stored_start, test_bs1a4c_backed_credit,
test_bs1a4b_failed_region_lightest, test_bs1a4b_windows_align_zmap, test_bs1a4c2_band_chord_cl_checked,
test_bs1a4c_fix_no_post_entry_helix, test_bs1a4d3_links_measured_as_cuts, test_bs1a_straight_channel,
test_bs1a3_no_band_after_a2d, test_rough_synth_pocket_repro, test_dt1_synthetic_rough_twice_identical,
test_bs1a4d6b_q4_entry_bore_in_live_stock, test_bs1a4d6c_side_entry_no_under_read, test_bs1a4d6d_approach_simulated_in_window0, test_bs1a4d7_sub1mm_tail_merges_not_dropped, test_bs1a4d8_arrival_gate_reads_judge_skin, test_bs1a4d8b_no_unsimulated_link_into_path, test_bs1a4d8c_inrun_jump_simulated, test_bs1a4d8c_replan_far_piece_enters_own_start, plus your new tests.

## Facts (supervisor + BS1a4d8c's own record)
- BS1a4d8c (dc073a1, WIP, RED): (2) re-plan run from the piece's own start, scoped to replan0-route regions when
  q4 -> piece fails lnk_cut_ok; (1) every in-run cutting pair > 0.6 mm simulated at eps 0, else lift -> rapid ->
  raw enter_at; counters irun_chk/irun_cvt, bstd_skip_*. 73 lines vs 337c44b.
- Its 3 REGRESSIONS vs 337c44b (supervisor committed-code verify of 337c44b passed all three):
  test_bs1a4d2b_centred_entry_bore: "entry bore at (-2.465, 6.448) Z 0.381 is not centred on the start: centre
  (0.53, 7.69) is 3.24 mm away > r + 0.3"; test_bs1a4d_credit_real_bore: "credited split cap (-2.4654, 6.4484)
  Z 0.381 emitted helix centre (0.6785, 7.7506) r 1.9029 has NO planning or re-check sim with that bore ... offset
  1.8337 mm"; test_bs1a4b_windows_align_zmap: "window count differs for region (6.276, -2.0778): engine 791 vs
  zmap 412".
- Root (d8c's record): the L-channel credited split cap at (-2.4654, 6.4484) Z 0.381, whose lightest piece starts
  3.24 mm from q4 over standing rest. At 337c44b that q4 -> piece join was a REAL unsimulated cut (the hole (1)
  closes); now the guard converts it, but the raw enter_at re-enters with a bore centred where the stock edge allows,
  which d2b's centred-bore invariant rejects and no predictor sim covers. THE GUARD IS RIGHT, THE RE-ENTRY IS WRONG.
- The three regressed tests are invariants: do NOT edit them.
- CF judge on dc073a1 (supervisor, full Core Front, holder on): single F3429 moves >= 2 mm over 2.44: 0 (the 25 mm
  move into (1.6689, 10.7822) still exists at line 289258 but judges 0.168; Z 40.289's 24.8 mm link gone). Gates all 0,
  full-width 1 window / 1.1 mm. BUT overload_feeds_ae2 836 / 906.7 mm vs 36319bf 458 / 554.4 (worse), cycle 23,518.4 s
  vs 5,502.9 s (x4.3), program 717,507 lines vs 347,658. Counters: irun_chk 16,231, irun_cvt 965, bstd_chk 9,585,
  bstd_cvt 965, bstd_skip_short 10,281.
- The 965 conversions are mostly unnecessary: 423 lift-and-re-enter events at the same Z found in the program; 394 of
  them were a direct F3429 move p -> q in 36319bf; 36319bf's zmap judged only ONE of those > 2.44 (line 64233, the
  25.2 mm link, 9.319); the other 393 judged <= 2.11 mm; 371 of the 394 are 1-2 mm steps (adaptive's own planned
  segments, already simulated by _simulate at plan time, which lnk_cut_ok - a link-CLEARANCE rule - rejects).
- New overload source: the converted re-entries' OWN final feed-in. 18 over-2.44 cutting-feed windows (27.0 mm) are a
  single move right after an F1270 entry = try_cand's last cutting-feed step into the start (rough.py:1396): worst line
  286133 ae_eff 9.43 a 18.61 (1.5 mm into (1.6689, 10.7822)), 528296 9.37, 285601 8.49, 538913 6.22, 322772 5.83.
## Design (coordinator): ONE entry function used by both sites
(A) Wherever a run's first cutting point is not the entry point and q4 -> piece fails lnk_cut_ok, on ANY route
    (replan0, plan0_split caps, own-region pieces), the piece start becomes the region's start and goes through the
    SAME entry decision as planning: borefn at that point, credit recomputed (a real centred bore there, else credit 0
    through the existing re-plan ladder), the bore stored in res["bore"], and its re-check sim recorded so the
    predictor mirrors it. Expected: the split cap at (-2.4654, 6.4484) enters centred at its own start and satisfies
    test_bs1a4d2b_centred_entry_bore and test_bs1a4d_credit_real_bore.
(B) The in-run guard (CORRECTED scope, coordinator): it covers ONLY pairs that are NOT part of a planned, simulated
    path - i.e. joins assembled at emit (mark piece boundaries when the run is built: q4 -> piece, piece -> piece,
    rejoined pieces). Planned segments keep their plan-time simulation and are never re-judged by lnk_cut_ok. A join
    that fails is converted by calling the SAME entry function as (A) for the far point - never a raw enter_at - with
    its bore and sim recorded the same way. Folding (A) and (B) into one helper should pay for its lines.
(B2) That one entry function simulates its OWN last feed-in step (try_cand's final cutting-feed move into the start,
    rough.py:1396) under the d6c/d6d approach rule and emits it only if within the limits; otherwise it takes the next
    ladder option. Prefer ramp or side entry at entry feed over a helix when it fits, through the EXISTING ladder
    order - no new entry types.
(C) Engine windows mirror what is emitted: CAUSE FIRST - find why region (6.276, -2.0778) reads 791 engine windows vs
    412 zmap after the change (likely the converted pair's simulated windows kept alongside the emitted ones, or the
    re-entry's windows counted twice) and make the emitted moves the ONLY source. test_bs1a4b_windows_align_zmap must
    pass unedited.
(D) Re-run ALL mutations on the FINAL code (d8c's ran before its last edits): (A) reverted + (B) on -> bstd_cvt 1;
    both reverted -> measured zmap ae_eff; join check bypassed -> measured zmap ae_eff; entry feed-in sim bypassed
    -> measured zmap ae_eff of the feed-in; planned segments NOT exempt (guard on every pair) -> the conversion count
    on a synthetic adaptive path rises (measured); plus one for (B): the guard's
    conversion through a raw enter_at -> the d2b / credit_real_bore failure. Paste the exact failure lines.
(E) Counters by provenance: conversions split into joins vs anything else (expect joins only), plus irun_chk/irun_cvt,
    bstd_skip_<reason>. Synthetic in-code scenes only; no fixture derived from James's part; no full CF run (the supervisor runs it).
## engine/BS1a4d6_RESULTS.md "BS1a4d8d": cause of (C), the change with file:line, TOTAL line count vs 337c44b, PASTED
exit codes of all 25 at-risk tests + new tests, all mutation outputs, git diff --numstat. Then stop.
