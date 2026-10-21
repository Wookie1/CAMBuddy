# FL1 results — floor_z respected in EVERY pass type (branch fl1 @ main 87a7057)

## Change (engine/finish.py, +37 lines; engine/test_finish.py +62 = tests)
- New `floor_net(paths, srcs, floor_z, bbox)`: every emitted CL vertex INSIDE the
  part bbox whose tip Z < floor_z is DROPPED and the path split there — never
  raised to the floor (same rule as S4). Applied ONCE, right after `grid_snap`,
  to BOTH `steep_paths` and `shallow_paths`; shallow/parallel, steep/waterline and
  rest all flow through this single place, and links/entries use only these
  (filtered) endpoints — the verified link logic is unchanged. `row_of`/`run_i0`
  alignment travels with the split pieces via `srcs`.
- Vertices OUTSIDE the part bbox are the raster's half-stepover pad rows
  (`raster_cl` pads `arange(ymin, ymax+0.5*stepover)`): stock-edge passes where
  the ball rolls off a vertical face into air. They are kept unchanged (this is
  what the S2c cut_len calibration measures; measured proof that this does not
  weaken the floor rule on the real part: main's posted interim finish has
  **0** below-floor feed moves outside the stock bbox, x range of its 7,910
  violations is −126.36..126.33, all inside ±128.651).
- New stat `n_floor_dropped` (steep+shallow vertices dropped at the floor).

## Tests (engine/test_finish.py)
`floor_dip_stl`: slot along Y (walls x=±6, mouth z=10), floor z=2 BELOW
floor_z=5 for |y|<4, shelf z=7 above the floor outside.
`test_floor_dip_split_finish_and_rest` (finish ball 6; rest ball 3 vs big ball 6,
min_rest 0.5, stock heightfield top+0.381):
- ON MAIN'S CODE (HEAD finish.py in a shadow tree): **FAILS** —
  `AssertionError: finish: 15 feed moves below floor_z (min 2.000)` (exit 1).
- ON FIXED CODE: **PASSES** —
  `floor-dip finish: feed=3395 minz=5.000 dropped=15 kept_shelf=331`
  `floor-dip rest: feed=3956 minz=5.000 dropped=52 kept_shelf=368`
  (no feed move inside the bbox below floor_z; shelf rows above the dip still
  cut -> passes split, not dropped wholesale.)

## Judge — interim chain, BEFORE (main's engine) vs AFTER (fixed engine)
Same flags both sides: `engine.cli finish --stl out/interim_model.stl --tool
ball:9.525 --stepover 0.3 --stepdown 0.3 --slope-threshold 40 --floor 24.765
--cut-feed 3429 --ramp-feed 1270 --post-grid-mm 0.001 --stock-from
out/interim_rough_engine_stock.npy`; post T20 program 1002; rest as the template
(`--rest-from` the zmap finish stock, `--rest-tool ball:3.142 --min-rest 0.5
--flute 6.35 --shank 3.142 --stickout 20.8 --holder BT30-ER20-80`), post T33
program 1004. BEFORE ran with `PYTHONPATH/cwd = shadow tree of HEAD` (main's
finish.py, verified floor_net-free); AFTER in this worktree. No `--ramp-angle-deg`
(not on this branch). Scripts: scratchpad `fl1_judge.py`, `fl1_zrough.py`,
`fl1_axial.py`; all via the one-job slot.

| metric | BEFORE (main) | AFTER (fixed) |
|---|---|---|
| feed moves below floor_z−0.001 in POSTED finish (own parser, G1/G2/G3 modal) | **7,910** (min Z 19.685) | **0** |
| feed moves below floor_z−0.001 in POSTED rest | **0** | **0** |
| ZB axial plunges, ball, >0.5 mm (zmap `_axial_raw`) — finish | **231** (max 5.280) | **33** (max 4.276) |
| ZB axial plunges, ball, >0.5 mm — rest | 5 (max 0.986) | 5 (max 0.986) |
| ZB axial plunges, zmap report floor 0.2 mm — finish / rest | 865 / 113 | 523 / 113 |
| exact probe_clcheck below_cl (posted finish ball 9.525 / rest ball 3.142) | 0 (max 0.00392) / 0 (max 0.00279) | 0 (max 0.00392) / 0 (max 0.00279) |
| zmap finish gouges / rapid_collisions / holder_hits / over_flute / outside_grid | 0/0/0/0/0 | 0/0/0/0/0 |
| zmap rest gouges / rapid_collisions / holder_hits / over_flute / outside_grid | 0/0/0/0/0 | 0/0/0/0/0 |
| finish coverage leftover max/mean/p95 | 35.665 / 0.184 / 0.863 | 35.665 / 0.460 / 5.461 |
| finish within_0p5mm_fraction | 0.941532 | 0.899704 |
| rest coverage leftover max/mean/p95 | 33.782 / 0.172 / 0.700 | 33.782 / 0.448 / 5.461 |
| rest within_0p5mm_fraction | 0.945481 | 0.903653 |
| cycle time finish (zmap) | 6155.8 s | 5603.8 s |
| cycle time rest (zmap) | 422.2 s | 422.2 s |
| engine stats n_floor_dropped finish / rest | — (key absent) / — | 8112 / 0 |

- ZB@0.5 after = **33** on the finish, exactly the expected ~33 (main's 231 minus
  the ~197 that sat below the floor). The 33 remaining are above-floor ball
  plunges, unchanged by this task.
- Coverage drop (within_0p5mm 0.9415→0.8997 finish, 0.9455→0.9037 rest) is the
  intended trade: stock below floor_z is now deliberately left uncut (leftover
  p95 0.863→5.461 = the below-floor region).
- Rough zmap (this session, `fl1_zrough.py`, flat 12.686 on
  out/interim_rough.DO_NOT_RUN.nc): gouges 0, rapid_collisions 0, axial_raw 451
  (documented baseline), cycle 3709.0 s; its stock feeds BOTH sides' finish checks.
- AFTER outputs are identical for the two threshold variants considered: main's
  pipeline had zero below-floor candidates outside the stock bbox, so the bbox
  gate keeps exactly what main emitted there (0 below floor).

## Suites (all via the slot, real exit codes)
- `scripts/check_fixtures.py` -> `fixtures: 10 ok, 0 bad`, exit 0. (The fresh
  worktree was missing the out-of-git fixtures; restored by copying from
  `/Users/James/ai-sandbox/stevecam` after sha256-verifying every file against
  `fixtures/manifest.json` — no hash mismatch.)
- `engine/test_engine.py` (VibeCAD python): exit 0.
- `engine/test_finish.py` (VibeCAD python, full incl. new test): exit 0,
  `ALL FINISH TESTS PASSED` (new test OK in 3.4 s).
- `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q`:
  **218 passed**, exit 0 (954 s).

## Exact commands
    # slot-wrapped queue (out/fl1_queue*.log):
    nohup .../scratchpad/slot.sh .../scratchpad/queue_fl1_mine.sh > out/fl1_queue.log 2>&1 &   # q1-q4 (q4 crashed on my script bug, fixed)
    nohup .../scratchpad/slot.sh .../scratchpad/queue_fl1_resume.sh > out/fl1_queue2.log 2>&1 & # q4 resume, q5
    nohup .../scratchpad/slot.sh /Applications/VibeCAD.app/Contents/Resources/bin/python .../scratchpad/fl1_axial.py > out/fl1_axial.log 2>&1 &
    nohup .../scratchpad/slot.sh .../scratchpad/queue_fl1_v2.sh > out/fl1_queue3.log 2>&1 &     # q1v2,q2v2,q7,q8,q9
    # inside them:
    cd <shadow HEAD tree>/engine && PYV -c "import test_finish; test_finish.test_floor_dip_split_finish_and_rest()"   # must fail on main
    cd /Users/James/ai-sandbox/stevecam-fl1 && PYV -c "import engine.test_finish as t; t.test_floor_dip_split_finish_and_rest()"
    PYH .../scratchpad/fl1_zrough.py
    PYV .../scratchpad/fl1_judge.py before|after          # engine.cli finish/post + probe_clcheck + verify.zmap chain
    PYV scripts/check_fixtures.py; PYV engine/test_engine.py; PYV engine/test_finish.py
    PYH -m pytest verify connector engine/test_post.py -q

Not committed (per task). opencode.json untouched by me (pre-existing local modification).
`.../scratchpad` = `/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad`,
PYV = `/Applications/VibeCAD.app/Contents/Resources/bin/python`, PYH = `/opt/homebrew/bin/python3`.
