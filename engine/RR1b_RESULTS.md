# RR1b — T20 ball rest-rough (Core Front): RESULTS

Status: IN PROGRESS — generation/judging runs queued in the one-job slot
(occupied by the stevecam-r2 session). Numbers below are from this session;
pending items marked PENDING.

## What was built (all uncommitted, per task)
- `engine/rest_rough.py` — 324 lines, new. Ball rest-rough generator:
  exact-CL zone detection (tip-Z convention), helix entry at
  r_h = 0.8·r_max gated by min_helix_r, flat floor circle at ramp feed,
  z-level contours TOP-DOWN at c = ae/2 stepping ae (each level's ring
  band is one stepover wide; a bottom-up floor-first order cannot legally
  feed the outer rings — the descent would be a plunge > zb_floor),
  inter-level helical descents (atan(stepdown/2πr_h) < MAX_RAMP_DEG, so
  never scored as ZB), FE5 live-stock disk rule for every entry
  (engine/entry_depth.LiveStock, stamp_chord order), fail-closed
  validate_exact vs the exact ball CL (0.005 mm).
- `engine/cli.py` — +110 lines: `rest-rough` subcommand; every T20 value is
  a required CLI parameter (--floor/--stepdown/--ae/--rest-leave/
  --min-excess/--min-helix-r/--cut-feed/--ramp-feed/--spindle/...); no T20
  numbers in engine code. Refuses non-ball tools; refuses to post when
  validate_exact > 0.
- `engine/entry_depth.py` (359 l) + `engine/test_entry_depth.py` (192 l):
  copied BYTE-IDENTICAL from branch fe5 (commit 8a2a9a0); `cmp` clean;
  not modified.
- `engine/test_engine.py` — +147/−0 net: two new tests
  (test_rr1b_rest_rough_synth_pocket, test_rr1b_rest_rough_reports_small_
  pocket) + registration. The two pre-existing DT1 tests that an earlier
  edit of mine had dropped were restored byte-identical from main.
- `connector/catalog.py` +55, `connector/runner.py` +30: rest_rough_*
  parameters + James's T20 defaults only (REST_ROUGH_DEFAULTS).
- Budget: 324 + 110 + 55 + 30 = **519 changed non-test lines** (+ test
  additions). Over the ~450 target, within the ~550 stop limit.

## Exact-CL rest zones (this session, out/rr1b/probe_exact.py)
PCL grid 0.2 mm from the tessellated part (out/rr1b/PCL_exact.npy):
54 components ≥ 5 mm², total **6782.9 mm² / ~7100 mm³** above floor+0.5.
Enterable (r_max ≥ 1.903 at leave 0.2): zone 29 centre membrane
x[-23.4..26.8] y[-21.4..0.6] r_max 5.188 zbot(CL) 42.965; bay X−71 zone 36
r_max 2.163 zbot 38.965; bay X+71 zone 37 r_max 2.126 zbot 38.965.
No legal entry (REPORTED): corner pockets zones 53/54 (r_max 1.0,
zbot 40.965), centre-south pocket zone 2 (r_max 1.0), flank bands 7/8
(~2286 mm², ~1786 mm³ each, r_max 0.72/0.57), zone 49 (r_max 1.2),
small zones r ≈ 0.283.

## Tests (this session)
- engine/test_engine.py RR1b tests: 2/2 PASS under VibeCAD python
  (synthetic 20 mm pocket: helix entry r_max_cl 5.0, 3 levels, floor
  leftover ≤ 0.4 mm where the ball holds leave, validate_exact 0, FE5
  entries all ≤ 0.5 mm; 8 mm pocket: REPORTED r_max_cl < 1.903, no feed
  inside). Full-suite rerun + fail-on-main: PENDING (slot queue).

## Commands
Generation (queued, out/rr1b/pipeline2.sh):
```
/Applications/VibeCAD.app/Contents/Resources/bin/python -m engine.cli rest-rough \
  --step samples/core_front_setup.step \
  --stock-from out/rr0_ref/stock_after_rough.npy \
  --out out/rr1b/rest_rough_cf.ngc \
  --tool ball:9.525 --floor 24.765 --stepdown 2.0 --ae 1.905 \
  --rest-leave 0.2 --min-excess 0.5 --min-helix-r 1.903 \
  --cut-feed 2280 --ramp-feed 850 --spindle 9500 --workers 8 \
  --post lnc --program 1003 --op-name "ROUGH REST" --metric \
  --tool-number 20 \
  --stats-json out/rr1b/rest_rough_cf_stats.json
```
(out/rr0_ref/stock_after_rough.npy had no sidecar; created
out/rr0_ref/stock_after_rough.json x0=-140.001 y0=-93.9 cell=0.1 from
out/cf_hf01_z5b.json.)

Judge + chain: out/rr1b/pipeline3.sh (zmap gates with
`--tool ball --dia 9.525 --flute 22.225 --shank-dia 9.525
--holder BT30-ER20-60 --stickout 46.2`, probe_clcheck, finish T20
FL1b-flags from rest stock, zmap --stock-in chain, rest T33
`ball:3.142 --flute 6.35 --shank 3.142 --stickout 20.8
--holder BT30-ER20-80`).

## Bar results
PENDING (slot queue behind stevecam-r2).
