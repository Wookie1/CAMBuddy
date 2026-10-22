# FL1b results — floor exemption tightened to the stock box (branch fl1b @ main 3e8b7b5)

## Change (engine/finish.py +45/-13 — ~20 code lines, rest docstring/comments; engine/test_finish.py +64 = tests)
- `floor_net(paths, srcs, floor_z, bbox, stock_box=None, tool_r=0.0)`: the FL1 exemption
  for pad-frame edge passes now applies ONLY to vertices OUTSIDE the stock box + tool
  radius. A below-floor vertex between the part bbox and the stock box (where stock
  stands) is DROPPED and the path split, like any other below-floor vertex.
- `finish()` derives the stock box from the heightfield it already receives
  (`--stock-from`, or `--rest-from` for the rest pass): grid extent
  `(x0, x0+(nx-1)*cell, y0, y0+(ny-1)*cell)` + `tool/2`. The interim judge chain and
  the new test pass `--stock-from`, so the strict rule governs every judged number.
- engine/cli.py NOT touched (it already passes `--stock-from` through to finish()).
  opencode.json untouched (pre-existing local modification, not mine).

### Documented deviation + question for the supervisor
Task text: "If no stock box is available, exempt nothing." Measured (scratchpad
`fl1b_diag.py`, both engines): with NO stock model the strict rule drops the 8
edge-roll pad vertices past the hemisphere plate bbox (-32 mm cut_len -> 2891),
breaking the S2c calibration band of the EXISTING `test_no_duplicate_raster_rows`
(lower bound 0.8 x 3641 = 2913; HEAD was at 2923). Relaxing that test is forbidden,
so when no stock model is given floor_net falls back to FL1's part-bbox exemption;
the stock-box rule applies whenever a stock box exists. Physical note: past the stock
edge the ball contacts the wall plane exactly AT floor level (tip -0.0004 mm, contact
z ~ 0), i.e. it cuts nothing below the floor there. On the real chain (stock model
always present via --stock-from) behavior is exactly as specified. OK?

## Test (engine/test_finish.py: test_floor_pad_rows_inside_stock_box)
Two-step block, part bbox +-6 x +-4, stock box +-12 x +-8 (stock stands between them);
floor_z=5; the raster pad row at y=4.1 rides the LOW step edge (CL ~3 < floor).
- ON MAIN'S CODE (HEAD finish.py in shadow tree): **FAILS** —
  `AssertionError: finish: 4 feed moves below floor_z inside the stock box (min 2.999 at y=4.10)` (exit 1).
- ON FIXED CODE: **PASSES** — `floor-pad finish: feed=4308 inbox=4308 dropped=12 kept_above=4308`,
  `floor-pad rest: feed=3319 inbox=3319 dropped=16 kept_above=3319` (both with stock_from/rest_from).

## Judge — interim chain (templates adapted), BEFORE (HEAD engine, shadow fl1b_main) vs AFTER (fixed worktree)
Rough zmap (this session, `fl1b_zrough.py` on out/interim_rough.DO_NOT_RUN.nc, flat 12.686):
gouges 0, rapid_collisions 0, axial_raw 451 (documented baseline), cycle 3709.0 s;
its stock (out/fl1b_stock_after_rough.npy) feeds BOTH sides' finish checks.
Same flags both sides: `engine.cli finish --stl out/interim_model.stl --tool ball:9.525
--stepover 0.3 --stepdown 0.3 --slope-threshold 40 --floor 24.765 --cut-feed 3429
--ramp-feed 1270 --post-grid-mm 0.001 --stock-from out/interim_rough_engine_stock.npy`,
post T20 program 1002; rest T33 ball 3.142 program 1004 (`--rest-from` the zmap finish
stock, `--flute 6.35 --shank 3.142 --stickout 20.8 --holder BT30-ER20-80`); zmap chain
and exact engine/probe_clcheck on the POSTED programs; own floor parser = G1/G2/G3 modal,
endpoint Z < 24.764.

| metric | BEFORE (main) | AFTER (fixed) |
|---|---|---|
| feed moves below floor_z in POSTED finish (own parser) | **63** (min Z 23.925, pad frame outside the part bbox, inside the stock box) | **0** |
| feed moves below floor_z in POSTED rest | 0 | 0 |
| ZB axial plunges, zmap report floor 0.2 mm — finish | 531 (max 4.2757) | **523** (max 4.2757) |
| ZB axial plunges — rest | 113 (max 0.986) | 113 (max 0.986) |
| exact probe_clcheck below_cl finish / rest | 0 (max 0.00392) / 0 (max 0.00279) | 0 (max 0.00392) / 0 (max 0.00279) |
| zmap finish gouges / rapids / over_flute / holder / outside_grid | 0/0/0/0/0 | 0/0/0/0/0 |
| zmap rest gouges / rapids / over_flute / holder / outside_grid | 0/0/0/0/0 | 0/0/0/0/0 |
| coverage ABOVE floor_z only (part cells part Z >= floor_z, stock within 0.5 mm; 3,015,074 cells) — finish | 0.95148 | 0.95148 (unchanged) |
| coverage above floor — rest | 0.95601 | 0.95601 (unchanged) |
| zmap all-surface within_0p5mm_fraction finish / rest | 0.89970 / 0.90365 | 0.89970 / 0.90365 (unchanged) |
| cycle time finish / rest | 5609.5 s / 422.2 s | 5603.8 s / 422.2 s |
| engine stats n_floor_dropped finish / rest | 7755 / 0 | **8112** (+357) / 0 |

- The 63 BEFORE violations sit at x ~ +-126.3, y ~ +-70 (just outside the part bbox
  +-126.36 x ~+-70, well inside the stock box +-128.651 x +-82.55) at Z 23.925..24.763:
  exactly the below-floor stock between part bbox and stock box that FL1 exempted. All gone after.
- Coverage over the part surface above floor_z is EXACTLY unchanged before/after (only
  below-floor stock cutting was removed); cycle slightly down (-5.7 s finish).
- Final-code reproducibility: regenerating finish AND rest with the final engine
  (`fl1b_q6.sh`) gives ngc outputs **byte-identical** (cmp) to the judged AFTER programs.

## Suites (all via the one-job slot, real exit codes)
- `scripts/check_fixtures.py` -> `fixtures: 10 ok, 0 bad`, exit 0 (fresh worktree
  fixtures restored by copy from /Users/James/ai-sandbox/stevecam, every file
  sha256-verified against fixtures/manifest.json — no mismatch).
- `engine/test_engine.py` (VibeCAD python): exit 0.
- `engine/test_finish.py` (VibeCAD python, full incl. new test): exit 0,
  `ALL FINISH TESTS PASSED` (new test OK in 1.1 s; S2c hemisphere calibration
  green at 2923 mm via the documented no-stock-box fallback).
- `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q`:
  **218 passed**, exit 0 (952.8 s).

## Exact commands
    # every run through the slot (logs out/fl1b_q*.log); PYV=VibeCAD python, PYH=homebrew python3,
    # SD=/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad
    nohup SD/slot.sh bash SD/fl1b_q1.sh > out/fl1b_q1.log 2>&1 &   # new test must-fail-on-main / must-pass-on-fix
    nohup SD/slot.sh bash SD/fl1b_q2.sh > out/fl1b_q2.log 2>&1 &   # zrough + judge before (q2c reran the report steps after a judge-script import fix; heavy steps cached)
    nohup SD/slot.sh bash SD/fl1b_q3.sh > out/fl1b_q3.log 2>&1 &   # judge after + fixtures + test_engine (stopped at q3d by the hemisphere conflict above)
    nohup SD/slot.sh bash SD/fl1b_q4.sh > out/fl1b_q4.log 2>&1 &   # instrumented floor_net diag, both engines
    nohup SD/slot.sh bash SD/fl1b_q5.sh > out/fl1b_q5.log 2>&1 &   # final code: must-fail-on-main, new+FL1 tests, S2c, full test_finish, pytest
    nohup SD/slot.sh bash SD/fl1b_q6.sh > out/fl1b_q6.log 2>&1 &   # byte-identity regen of the judged AFTER programs

Not committed (per task). verify/ untouched (read/run only).
