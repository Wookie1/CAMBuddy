# HB1 v2 RESULTS — one flat floor circle at each helix bottom, at the helix (ramp) feed

Branch `hb1v2` = main `843337a` (HR1) + commit `3b5a2d3`. Not committed further (per task).
Change: `engine/rough.py` +20 lines (10 comment, 10 logic: after each helix entry emit ONE full
flat circle at the helix bottom Z on the helix path — same centre/radius — at the ramp feed,
milled honestly into the live stock model; pitch untouched, no cap). `engine/test_engine.py` +87
lines (test `hb1v2 floor circle`).

## Ablation — containment fallback (v1's tiers), task item 3
`out/hb1v2_containment.patch` (hc-centred bore `max(r0, helix_dia/2)` + hc-containing circle
tiers) applied vs NOT applied, everything else equal, Core Front:

| | without (committed) `out/hb1v2_cf*` | with `out/hb1v2_cfa_*` |
|---|---|---|
| FW windows (ae_eff >= 0.9·12.686, a > 0.5) | 275 / 285.5 mm | 275 / 285.5 mm |
| overload windows (ae_eff > 2.4384, a > 0.5) | 689 / 764.5 mm | 689 / 764.5 mm |
| FW at cutting feed (zmap) | 154 / 161.2 mm | 154 / 161.2 mm |
| zmap cycle_time_s | 4980.1 | 4980.8 |
| gouges / rapids / plunges / outside_grid | 0/0/0/0 | 0/0/0/0 |

The programs really differ (147,607 NGC lines differ; all 73,192 ae2 windows differ in position)
yet FW/OV counts and lengths are IDENTICAL: **containment removes zero real full-width windows at
the cutting feed** -> per task item 3 the fallback is NOT kept (committed code has none).

## Ridge vs band classification of a2d_first full-width, before (main) vs after
Script `out/hb1v2_classify.py` (report-only; verify/ untouched); RIDGE = Z is a helix bottom
(|dz| <= 0.01) and a <= that helix's measured pitch + 0.05, tool centre within helix bore
r + R; BAND = everything else. BEFORE = main (`out/hb1v2_cfmain_ae2.json` /
`out/hr1_tb_ae2.json`; CF owners from the byte-identical labelled run `out/hr1l_labels.json`).
Helix geometry is unchanged by HB1v2, so helices are parsed from the AFTER ngc for both sides.

Core Front (`out/hb1v2_cf_classify.json`):
- BEFORE: FW 302 / 330.2 mm; a2d_first FW = **138 / 158.0 mm**, all at helix-bottom Z inside the
  bore (the ridge-shear mechanism), with a = 2.07–18.61 mm (full slab depth) > pitch+0.05, so
  under the strict definition they classify BAND (ridge-type a2d_first = 0 already before; the
  meaningful before/after delta is the a2d_first FW total and helix-bottom FW below).
- AFTER: FW 275 / 285.5 mm; **a2d_first FW = 0** (OV 1 / 1.1 mm) -> **ridge-type a2d_first
  full-width = 0 PASS**. Ridge-type total after = 121 / 124.2 mm — ALL on the floor-circle moves
  (entry feed, part of the entry), none attributed to a2d_first. Band-type after = 154 / 161.2 mm
  (all hug_boundary; main's hug FW was 162 / 169.3 mm -> improved).

Test block (`out/hb1v2_tb_classify.json`): BEFORE FW 39 / 42.2 mm (hr1_tb_ae2.json predates ZE2F
feed tags — all feed=None; main emits no entry-feed horizontal moves, so effectively cutting
feed). AFTER FW 32 / 32.7 mm = 24 / 24.7 mm floor-circle windows (entry feed) + 8 / 8.0 mm
band. **ridge-type a2d_first FW = 0 PASS** (no a2d_first FW windows at all after).

## Helix-bottom full-width at CUTTING feed
- Restricted to the ENTRY moves (helix return-feed / circle moves on the entry): CF before 2 /
  3.0 mm (helix_bottom owner) -> **after 0 PASS**; TB before 0 -> **after 0 PASS**.
- Broadest reading (ANY FW window at a helix-bottom Z inside the bore, all owners):
  CF 160 / 181.0 mm -> **12 / 12.0 mm**; TB 31 / 34.2 mm -> **3 / 3.0 mm**. Every remaining
  window matches one of main's OWN hug_boundary windows at distance 0.0 mm (same z, a, length;
  CF main had 20 / 20.0 mm there) — band-type boundary skims, not entry/ridge windows, and no
  new offenders (`after_FW_unmatched_not_circle = []` for CF; all TB non-circle FW match main
  geometrically). Flagging for the supervisor: literal "=0" under this broadest reading is not
  met by 12+3 band windows that exist identically on main.

## Circle windows (entry feed) — ZE2F pitch-propagation caveat, task item 3
ZE2F attaches `helix_pitch` only to the FIRST window after a descent run (`desc_run` ends at the
first horizontal move), so later floor-circle windows show as `fw_entry_not_allowed` in
verify/zmap.py (`roughing_target_ae2.fw_entry_not_allowed` CF 113, TB 22). From
`out/hb1v2_classify.py` (`circle_windows`, per-window a vs pitch in the JSON):
- CF: 121 circle FW windows, all at helix-bottom Z, all at ramp feed 1270, **all 121 with
  a <= pitch + 0.05** (a 0.509–1.067, max a − pitch = **−0.026**); ZE2F allows 8 / 121 today.
- TB: 24 circle FW windows, all at helix-bottom Z and ramp feed, **all 24 with a <= pitch +
  0.05** (a 0.504–1.080, max a − pitch = **−0.017**); ZE2F allows 2 / 24 today.
With the pitch propagated along the contiguous entry-feed run at the helix-bottom Z (supervisor's
verify/ fix, landed during this session as stevecam-ze2f2 `0b4835b` "ZE2F2: carry the helix pitch
along the contiguous entry-feed run at the helix bottom Z"; NOT merged into this worktree's verify/
— untouched per HARD RULES) all 121 / 24 circle windows become allowed_helix_bottom and
fw_entry_not_allowed drops to 0.

## Owners vs main (Core Front; FW count / FW mm / OV count / OV mm)
before: a2d_first 138/158.0/269/308.5 · a2d_mid 0/0/34/55.3 · a2d_reentry_cut 0/0/7/8.5 ·
helix_bottom 2/3.0/21/31.5 · hug_boundary 162/169.3/482/529.5
after: a2d_first 0/0/1/1.1 · a2d_mid 0/0/31/50.3 · a2d_reentry_cut 0/0/6/7.3 ·
helix_bottom 0/0/7/10.5 · helix_bottom(new) 121/124.2/172/176.8 · hug_boundary 154/161.2/472/518.6
-> **no existing owner worse than main** (every owner's FW and OV length improved).
Totals: FW 330.2 -> 285.5 mm, OV 933.2 -> 764.5 mm. TB (no owner labels for main): FW
42.2 -> 32.7 mm, OV 92.0 -> 68.6 mm.

## zmap gates + cycle (this session's files)
- CF after (`out/hb1v2_cf_zmap.json`): gouges 0, rapid_collisions 0, axial_plunges 0,
  outside_grid 0; cycle_time_s **4980.1 vs main 4851.6 (+128.5 s <= +240 PASS)**.
  roughing_target_ae2: fw_cutting_feed 302 -> 154, fw_entry_not_allowed 0 -> 113 (all floor
  circles, see caveat), met false -> false.
- TB after (`out/hb1v2_tb_zmap.json`): gouges 0, rapid_collisions 0, axial_plunges 0,
  outside_grid 0; cycle_time_s 369.1 s; fw_cutting_feed 8, entry 24 (not_allowed 22, caveat).
  BEFORE zmap JSON for TB does not exist in this worktree (only main's ae2 dump
  `out/hr1_tb_ae2.json`), and re-running main's TB engine was forbidden by RESUME — TB-before
  numbers above are computed from that ae2 dump.

## Helix minutes before/after
Helix geometry untouched -> helix feed time unchanged: CF 51,581.5 mm = **40.62 min** at F1270
before AND after; the 186 floor circles add 3,280.2 mm = **2.58 min**; observed CF cycle delta
+128.5 s (< the 154.9 s of circle feed — shortened links/rapids offset part). TB: helix
3,488.6 mm = 2.75 min unchanged; 12 circles add 224.4 mm = 0.18 min.

## Tests / fixtures
- New test FAILS on main: `out/hb1v2_test_main.log` EXIT=1 — "AssertionError: helix at
  (-7.96,-7.36) Z 6.381: no ramp-feed floor circle after the helix bottom (next move f=3429.0)".
- engine/test_engine.py on the fix: prior session `out/hb1v2_gates.log` RC_ENG=0; re-run THIS
  session with VibeCAD python: 26 PASS incl. "PASS hb1v2 floor circle: 4 helix entry/entries each
  followed by one full flat circle at the helix bottom Z, ramp feed", 0 failure(s), **RC_ENG=0**
  (`out/hb1v2_test_engine_rc.log`).
- engine/test_finish.py (VibeCAD python): ALL FINISH TESTS PASSED, RC_FIN=0 (`out/hb1v2_gates.log`).
- pytest verify connector engine/test_post.py -q: 218 passed, RC_PY=0 (`out/hb1v2_gates.log`).
- scripts/check_fixtures.py, this session: "fixtures: 10 ok, 0 bad", **RC_FIX=0**
  (`out/hb1v2_fixtures.log`). (The earlier gates run recorded RC_FIX=1 only because three frozen
  golden files in out/ were missing from the interrupted worktree; they are present and hash-ok.)

## Commands (all heavy runs via the one-job slot:
`nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <cmd> > out/<log> 2>&1 &`)
Pre-outage runs (same commands as engine/TASK_HR1.md judge; reconstructed — logs in out/ prove
the outputs):
- CF engine: `/opt/homebrew/bin/python3 -m engine.cli rough --step samples/core_front_setup.step
  --stock -128.651 128.651 -82.55 82.55 0.0 60.96 --tool flat:12.686:0.0 --floor 24.765
  --leave 0.381 --stepdown 19.05 --optimal-load-mm 2.032 --stepup 1.905
  --hf out/core_front_setup_hf.npy --min-rest 0.5 --out out/hb1v2_cf.ngc` -> `out/hb1v2_cf_judge.log`
- CF zmap: `/opt/homebrew/bin/python3 verify/zmap.py out/hb1v2_cf.ngc --part out/cf_hf01_z5b.npy
  --tool flat --dia 12.686 --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438
  --jobs 6 --ae2-dump out/hb1v2_cf_ae2.json --out-json out/hb1v2_cf_zmap.json`
- TB engine: `/opt/homebrew/bin/python3 -m engine.cli rough --step samples/test_block.step
  --stock -50 50 -40 40 0 38 --tool flat:12.686 --floor 20 --leave 0.381 --final-zmin 20.381
  --stepdown 19.05 --optimal-load-mm 2.032 --hf out/test_block_hf_0.5.npy --out out/hb1v2_tb.ngc`
  -> `out/hb1v2_tb_judge.log`
- TB zmap: `/opt/homebrew/bin/python3 verify/zmap.py out/hb1v2_tb.ngc --part
  out/test_block_hf_0.1.npy --tool flat --dia 12.686 --stock -50 50 -40 40 0 38 --engage-max
  2.438 --ae2-dump out/hb1v2_tb_ae2.json --out-json out/hb1v2_tb_zmap.json`
- ablation (with containment): apply `out/hb1v2_containment.patch`, CF engine ->
  `out/hb1v2_cfa_cf.ngc` (`out/hb1v2_ablate_with.log`) + same zmap -> `out/hb1v2_cfa_*`; revert.
- classification (report-only, this session):
  `/opt/homebrew/bin/python3 out/hb1v2_classify.py out/hb1v2_cf_ae2.json out/hb1v2_cf.ngc
  out/hb1v2_cfmain_ae2.json out/hb1v2_cfmain_zmap.json out/hb1v2_cf_zmap.json
  out/hr1l_labels.json > out/hb1v2_cf_classify.json` and
  `/opt/homebrew/bin/python3 out/hb1v2_classify.py out/hb1v2_tb_ae2.json out/hb1v2_tb.ngc
  out/hr1_tb_ae2.json - out/hb1v2_tb_zmap.json - > out/hb1v2_tb_classify.json`
This session:
- `/opt/homebrew/bin/python3 scripts/check_fixtures.py` -> RC_FIX=0 (`out/hb1v2_fixtures.log`)
- slot: `/Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_engine.py` ->
  `out/hb1v2_test_engine_rc.log`
