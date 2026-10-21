# Task HR1 results — per level, hug rings emitted AFTER that level's Adaptive2d regions

Branch `hr1` = main 9ba2f88 + this change. Files touched: `engine/rough.py`
(+18/-11), `engine/test_engine.py` (+new test `test_hr1_rings_after_a2d`,
registered in `_main`). Nothing committed. All numbers below were produced
this session from files under `/Users/James/ai-sandbox/stevecam-hr1/out/`.

## The change (engine/rough.py, per level)
`n_a2d = len(regions)` right after `_run_a2d(...)`; the RT nearest-neighbour
travel now runs in two phases: all a2d regions (NN among themselves from the
previous level's end position), then ALL hug-ring regions (NN among the rings
starting from where the last a2d region left the tool). Links, entries, ramp,
helix, clip logic, retract_to/enter_at/descend_feed untouched.

## New test (engine/test_engine.py::test_hr1_rings_after_a2d)
Synthetic part (slab 40x32 top Z6 + central wall top Z12 whose grown forbidden
band leaves a 0.6 mm neck at the stock edge -> territory splits into two a2d
regions per level + fused fins giving the wall ring multiple runs). Wraps
`_run_a2d`/`hug_regions` to tag every emitted horizontal cutting move at a
level Z as a2d or ring, asserts no ring move precedes an a2d move at the same
Z. Must-fail proof on main's code (before the rough.py edit, via the slot):
`FAIL ... level Z=6.381: hug-ring cutting moves do not follow all a2d cutting
moves (emitted order ['ring', 'a2d'])` (out/hr1_test_before3.log, EXIT=1).
After the edit: `PASS hr1 rings after a2d: 2 level(s) with ring+a2d moves,
every ring follows all a2d at its Z` (out/hr1_test_after.log, EXIT=0).

## Judge runs (exact commands)
Core Front T13 (out/hr1_cf_judge.log):

    /Applications/VibeCAD.app/Contents/Resources/bin/python out/hr1_run_part.py out/hr1_cf_capture.pkl \
      --step samples/core_front_setup.step \
      --stock -128.651 128.651 -82.55 82.55 0.0 60.96 \
      --tool flat:12.686:0.0 --floor 24.765 --leave 0.381 --stepdown 19.05 \
      --optimal-load-mm 2.032 --stepup 1.905 --hf out/core_front_setup_hf.npy \
      --min-rest 0.5 --out out/hr1_cf.ngc
    /Applications/VibeCAD.app/Contents/Resources/bin/python verify/zmap.py out/hr1_cf.ngc \
      --part out/cf_hf01_z5b.npy --tool flat --dia 12.686 \
      --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438 \
      --jobs 6 --ae2-dump out/hr1_cf_ae2.json --out-json out/hr1_cf_zmap.json

(hr1_run_part.py = engine.cli rough, byte-identical emission, plus an
in-process monkeypatch capture of per-level region kinds for AFTER tagging -
no engine change for tags.)

Test block (out/hr1_tb_gates.log):

    /Applications/VibeCAD.app/Contents/Resources/bin/python out/hr1_run_part.py out/hr1_tb_capture.pkl \
      --step samples/test_block.step --stock -50 50 -40 40 0 38 \
      --tool flat:12.686 --floor 20 --leave 0.381 --final-zmin 20.381 \
      --stepdown 19.05 --optimal-load-mm 2.032 --hf out/test_block_hf_0.5.npy \
      --out out/hr1_tb.ngc
    /Applications/VibeCAD.app/Contents/Resources/bin/python verify/zmap.py out/hr1_tb.ngc \
      --part out/test_block_hf_0.1.npy --tool flat --dia 12.686 \
      --stock -50 50 -40 40 0 38 --engage-max 2.438 \
      --ae2-dump out/hr1_tb_ae2.json --out-json out/hr1_tb_zmap.json

## Owners
BEFORE: out/ov0_cf_labels.json (CF) and ov0_tb_labels.json (TB, from the OV0
run; matches hb1_tb_before.ngc line-for-line); window owner = majority class
by move length over the window span (OV1 convention); hug* -> ring, a2d* ->
a2d. AFTER: own capture (out/hr1_<part>_capture.pkl) tags each move by the
cutting points of the region that emitted it. Full analysis:
out/hr1_analyse.py, out/hr1_analyse_len.py -> out/hr1_numbers.json,
out/hr1_numbers_len.json.

## Numbers — Core Front (before = out/ze2_main_ae2.json + ov0 labels; after = this run)
| metric | before | after |
|---|---|---|
| hug-ring full-width length (ae_eff >= 11.4174, a > 0.5), ring-owned windows | **1051.7 mm / 975 win** (supervisor's stated before: 876.8 mm / 970 win) | **172.3 mm / 164 win** |
| overload length (ae_eff > 2.4384, a > 0.5), owner = ring | 1454.5 mm | **555.0 mm (-62%)** |
| overload length, owner = a2d | 252.7 mm | **378.3 mm (+125.6)** |
| overload length, owner = other | 30.0 mm | 0 mm |
| total overload length | 1737.2 mm | **933.3 mm (-46%)** |
| ring ae_eff p95 / max (all ring windows) | 12.70 / 12.818 | **5.193 / 12.815** (6385 ring windows) |
| zmap gouges / rapid collisions / axial plunges / outside_grid | - | **0 / 0 / 0 / 0** |
| cycle time (zmap) | 4893.4 s | **4851.6 s (-41.8 s)** |

Residual FW rings: 172.3 mm sits 2.3 mm above the <= 170 bar, and every
residual window is at Z 40.289/42.354/42.926 at minimum distance 16.5 mm
from ANY a2d centre at the same Z (> R = 6.343): these bands are never
touched by a2d at their Z (territory/clip-limited, clip logic untouched per
task), so no ordering can make them skims. All FW rings that had a nearby
a2d pass were fixed by the reorder (975 -> 164 windows).

a2d-owner overload rises +125.6 mm: where the ring previously pre-cut the
wall band full-width before its level's a2d passes, the a2d boundary pass now
meets virgin stock first - the engagement transfers owners; total overload
still drops 46% and ring FW collapses 84%.

## Numbers — test block (before = out/hb1_tb_before_ae2.json + ov0 tb labels)
| metric | before | after |
|---|---|---|
| hug-ring full-width length | **18.0 mm / 18 win** | **19.5 mm / 19 win** |
| overload length ring / a2d / other | 39.0 / 48.5 / 4.5 mm | 43.5 / 48.5 / 0 mm |
| ring ae_eff p95 / max (all ring windows) | 8.24 / 12.70 (577 win) | **8.24 / 12.70** (582 win) |
| zmap gouges / rapid collisions / axial plunges / outside_grid | - | **0 / 0 / 0 / 0** |
| cycle time (zmap) | 358.7 s | **358.7 s** |

TB already had rings almost fully after a2d on main (18 mm FW); the reorder
changes it marginally (+1.5 mm / +1 FW window, +4.5 mm ring overload - a
different NN start position slightly changes one ring's path).

## Gates (via the slot; logs)
First gate pass (out/hr1_tb_gates.log) failed ONLY on missing local untracked
fixtures in this fresh worktree (out/test_block.stl, out/core_front_roughG.ngc,
out/core_front_rough_X7.nc, out/core_front_roughRT_before.ngc) - no code
failures; fixtures regenerated/copied per fixtures/manifest.json and gates
re-run (out/hr1_refix.log), final state **REFIX_RC=0**:
- scripts/check_fixtures.py: exit 0 (fixtures ok after regen)
- engine/test_engine.py (VibeCAD python): `0 failure(s)` - includes the new
  test_hr1_rings_after_a2d (out/hr1_refix.log)
- engine/test_finish.py (VibeCAD python): `ALL FINISH TESTS PASSED`
  (out/hr1_tb_gates.log; unaffected by this change, re-verified in the same
  session)
- /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q:
  `215 passed, 32 warnings in 942.19s` exit 0 (out/hr1_refix.log)
