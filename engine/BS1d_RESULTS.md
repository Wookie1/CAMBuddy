# BS1d results (final)

Started Tue Oct 27 04:06 MST, finished ~05:20 (within the 2 h cap).
Branch bs1d @ 3e16730 (brief) on main 605fffa. Nothing committed.

## The change (72 changed non-test engine lines vs 605fffa)

`git diff --numstat 605fffa -- engine/band.py engine/rough.py`
    33	1	engine/band.py
    34	4	engine/rough.py

Item 1 - counted a2d drop (engine/rough.py):
* rough.py:952 `_a2d_new(...)` - the Adaptive2d config factored out, so every
  Execute gets a fresh instance (primary call configured exactly as before).
* rough.py:970 `_run_a2d(..., z, stats)`: every StartPointNotFound result of
  the primary call is summed into stats["a2d_spnf"]; when the primary call has
  any SPNF, each outer is re-run ALONE at the primary helix on a fresh
  Adaptive2d (with the same holes+islands); if that yields no region (no
  non-SPNF result with a non-empty Cutting path) the outer is appended to
  stats["a2d_dropped_outers"] as {"z", "polygon"}. No ladder, no fallback:
  the returned regions are exactly main's; levels without SPNF make no extra
  Execute.
* rough.py:1189 stats init: "a2d_spnf": 0, "a2d_dropped_outers": [].
* rough.py:2160 call site passes z, stats.

Item 2 - overload trigger (engine/band.py):
* band.py:48-49 OVL_BAND_MM = 1.0, OVL_STAND_MM = 2.032 next to FW_TRIGGER.
* band.py:154 `_stands(stock, p, c, z, dist)` - stock stands beside the ring:
  the live top at dist from ring point p, along the path normal through the
  sliver centre c, exceeds z + OVL_STAND_MM on the ISLAND side (away from c,
  where the wall/strip is) while the CHANNEL side (where the CL room is)
  holds no such stock (off-grid channel = no evidence = no fire).
* band.py:440-467 `channel_regions`: dense samples whose window is over
  SPIKE_MM but under fw_min become overload candidates (`ovl`); besides the
  full-width trigger they are marked (same FW_LEAD_PTS lead-in/out) when
  _stands fires at tool_r + leave + OVL_BAND_MM. Downstream is unchanged:
  the marks feed the same centre line, MIN_SLIVER, shrink_ladder, gates,
  entries, done-marking and failed_region_emitted; the blocked report stays
  full-width-only.

### Deviation from the spec wording (measured, deliberate)
The brief's literal probe ("stock top ... on the channel side ... > z +
2.032") CANNOT fire on the committed red scene: diagnostic
(scratch/diag_bs1d.py, scratch/diag2.log) shows the Z 4.381 overloaded ring
samples at CL x=-23.24 / y=-18.24 hugging the walls - the channel side
(CLR room, march 9.5 mm) reads stock top 0.381 (this level's a2d cleared
it) and the standing strip (top 18.0) is on the WALL side. A first probe
that accepted "either side stands" turned BOTH red tests green but broke
test_bs1a4d2b_centred_entry_bore (it also fired in the test-block Z 27.381
slot, where BOTH sides stand top 38.0, and moved a band region's entry
start so 1 fresh cell stood under its start disk; disabling the trigger
via mutation passes: scratch/mut_no_ovl.log exit 0). The final predicate -
island side standing, channel side cleared - fires on the red ledge scene
and on the Core Front strip class (a2d clears the channel at the plateau
level, the strip beyond the tool's reach stands), and does NOT fire in a
full-height slot. Unit-probed all four combinations (stand/clear x
stand/clear + off-grid) directly: correct.

## Red tests (printed numbers)
* test_bs1d_overload_band_on_standing_strip: exit 0
  "bs1d strip: Z 4.381 band regions 1, over-2.44 windows at cutting feed on
  the ring stretch 2 (max ae 4.60); gates g0 r0 a0 o0 clcheck 0 / PASS
  bs1d: overloaded ring stretch beside standing stock banded"
  (main: 0 band regions, 43 over-2.44 windows, max ae 7.86)
* test_bs1d_a2d_drop_counted: exit 0
  "bs1d drop: a2d_spnf 1, a2d_dropped_outers [(0.381, 24)],
  n_band_regions 4 / PASS bs1d drop counted"

## At-risk tests - ALL exit 0, run through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh
every one run against the FINAL code (the four run earlier under an interim
predicate were re-run):
    test_bs1a_straight_channel              0  "PASS bs1a straight channel: 4 band region(s), 12611.8 mm, 0 full-width windows"
    test_bs1a_lshaped_channel               0  "PASS bs1a L-shaped channel: 34 band region(s), 2264.4 mm, 0 full-width windows"
    test_bs1a4b_windows_align_zmap          0  "PASS bs1a4b alignment: 1 region(s), window boundaries identical"
    test_bs1a3_no_band_after_a2d            0  "PASS bs1a3 no-band-after-a2d: 0 band regions emitted"
    test_bs1a4d2b_centred_entry_bore        0  "PASS bs1a4d2b: centred entry bores - 1 TB + 8 L checked"
    test_bs1a4c_fix_no_post_entry_helix     0  "PASS bs1a4c-fix: L channel roughs CL-clean"
    test_bs1a4d8e_inrun_guard_skips_planned_paths 0 "PASS bs1a4d8e T-scope: 0 conversions"
    test_bs1a4d9_no_entry_at_stale_q4       0  "PASS bs1a4d8c re-plan: far piece entered at its own start"
    test_hb1v2_flat_floor_circle_after_helix 0 "PASS hb1v2 floor circle: 4 helix entries each followed by one full flat circle"
    test_rough_synth_pocket_repro           0  "PASS rough synth_pocket repro: 11353 moves, backstop + clcheck 0"
    test_rough_testblock_r2                 0  "PASS rough test-block R2: 44082 moves, clcheck 0"
    test_rough_testblock_r4                 0  "PASS rough test-block R4: 2308 floor cells 0.381 +- 0.05"
    test_dt1_synthetic_rough_twice_identical 0 "PASS dt1 twice-identical synthetic rough (1896757 chars)"
    test_hr1_rings_after_a2d                0  "PASS hr1 rings after a2d"
    test_rough_rt_entries                   0  "PASS rough rt entries: axial 0"
    test_se2_side_entries_only_through_cleared 0 "PASS SE2 side entries"
    test_rr1c5c_closed_pocket_bore_entry_no_deep_axial 0 (silent test, exit 0)
    test_rr1c4c_floor_circle_over_rising_surface 0 (silent test, exit 0)
    test_rr1c5b_varying_width_band_fronts   0  (silent test, exit 0)
    test_rr1c5b_open_edge_proud_block       0  (silent test, exit 0)
    test_rr1c5b_fully_walled_band_bore_seed 0  (silent test, exit 0)
    test_fi1_entry_feedin_within_limit      0  "PASS fi1 T-feedin: every entry feed-in judged <= 2.44"
    test_rr1b_rest_rough_synth_pocket       0  (silent test, exit 0)

## Notes for the supervisor
* Line count 72 is over the 60 budget but well under the 90 stop; the
  _a2d_new factoring is what item 1's "fresh Adaptive2d instance" costs.
* test_bs1a_straight_channel / bs1a_lshaped_channel band counts moved
  (7->4 / 32->34 across predicate iterations; both tests assert windows and
  gates, not counts, and pass). Determinism: dt1 twice-identical passes.
* This worktree had NO out/ fixtures (the at-risk testblock tests need them)
  - regenerated per fixtures/manifest.json: out/test_block.stl (sha256
  1210a800... matches the pin) and out/test_block_hf_0.5.npy/.json via the
  manifest command (VibeCAD 26.3.1-RC6; bytes differ from the manifest pins,
  which may be version drift - the tests using them pass).
* Slot lane: every test run through /Users/James/ai-sandbox/stevecam-ops/
  slot_m4.sh; no locks touched; no Core Front job; full suite NOT run here.
* opencode.json shows as modified in git status but was not touched by me.
* Scratch kept in scratch/ (diagnostics: diag_bs1d.py, diag2_bs1d.py,
  diag_tb_fires.py, mutation probe mut_no_ovl.py; test logs at_*.log).

## Iteration history (exit codes at each step)
1. literal channel-side probe: red1 exit 1 (band regions 0, 43 windows);
   red2 exit 0.
2. either-side probe: red1 exit 0 (1 region, 2 windows); bs1a4d2b exit 1
   (start disk pokes past swept bore); mutation (trigger off) exit 0.
3. final island-stand + channel-clear predicate: red1 exit 0, red2 exit 0,
   all 23 at-risk exit 0 (table above).
