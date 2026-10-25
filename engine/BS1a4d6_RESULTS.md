# BS1a4d6 RESULTS

Session start (`date`): Sun Oct 25 04:38:50 MST 2026
Worktree: /Users/James/ai-sandbox/stevecam-bs1a4d5, branch bs1a4d5 @ 582d668 (b6c48e1 + brief).

## Status log
- 04:38 started; scratch/ created.
- 04:44 first lane call (`slot_m4.sh python -c "print(version)"`) exceeded a 5-min
  timeout before completing — slot appears queued/busy. Retried with a longer
  timeout; per LOCKS, no lock files touched. Second attempt completed OK.

## CAUSE (before any code change) — who hits replan0_drop and why (diag: scratch/diag_cause.py)

Scene: the L channel (tris of test_bs1a4d_credit0_lightest_option), Z 0.381.
Identical acts with and without the link_clear-forcing spy. Exactly ONE piece
hits replan0_drop:

- piece start q4 = (-6.2719, 3.5231) @ Z 0.381, replan0 = 2 (plan0_splitbore),
  stored bore = centre (-6.0997, 3.1074) r 0.5 (small bore, below min helix r).
  Its real-bore emit re-check (band._simulate with the stored bore) fails the
  gate, so it takes the credit-0 shrink ladder on the live stock.
- The lightest option is shrink0.75: max window 2.5 mm, best area 70.50 mm2 —
  lighter than drop_ring (2.5 mm ring windows recorded at the same place).
- WHY it cannot rejoin q4: shrink_ladder rebuilds the trochoid over the WHOLE
  centre-line segment res["seg"], so the option path starts at
  pnew[0] = (-18.724, 0.6852) — 12.771 mm from q4. The join test
  _split_at_jumps(isl_ok3, [q4] + pnew) yields pcs[0] = [q4] alone
  (1 point of 2065): the straight chord q4 -> pnew[0] fails the
  segment-sampled CL check (it crosses the forbidden wall between the channel
  arms), so len(pcs[0]) < 4 and b6c48e1 drops the cut (stock left for the
  ring) -> test_bs1a4d_credit0_lightest_option ("... 'replan0_drop' not EMITTED
  as its lightest option: {... 'option': 'drop_ring', 'max_ae': 2.5}") and
  test_bs1a_lshaped_channel ("7 full-width window(s) ... 12.0-12.5 mm wide",
  the ring slotting the dropped piece's stock).
- All other replan0 failures on the scene DO rejoin (pcs[0] = 148 or 681 of
  2698-3986 points, chord 2.7-3.5 mm) and already emit at their lightest
  option (replan0_shrink1 / replan0_shrink0.55) — unchanged by this task.

## Plan
(a) rough.py emit fallback: when the lightest option's first piece cannot join
    q4, emit that piece as its OWN region at its own enter_at entry (normal
    ladder, enter_at stays the only entry), act "replan0_<opt>", listed in
    failed_region_emitted (option=opt, measured max_ae) and credit_fallback.
    Never dropped. Drop stays only as the last-resort when NO piece >= 4 pts
    exists at all.
(b) test_bs1a4d_credit_real_bore (approved): scope the "extra > 100" assert to
    emitted bores r >= min helix r (0.3 x tool_r = 1.9029 ~ 1.903); for smaller
    emitted bores add a replacement assert that the credited area equals the
    emitted bore's own sim footprint (helix centre, r + tool_r, plus landing
    disk) within grid tolerance.
