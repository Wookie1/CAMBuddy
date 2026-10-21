# Task FE5 step 1: finish/rest entries ramp ONLY where the live stock is deep. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ (read and run it only); engine code must NOT import verify/ or zmap. Edit engine/finish.py, engine/entry_depth.py,
engine/test_entry_depth.py, engine/test_finish.py (add tests only) and the --ramp-angle-deg plumbing (engine/cli.py,
connector/catalog.py, connector/runner.py) only. Do NOT touch opencode.json. FE diff vs main UNDER ~250 lines
(entry_depth.py and tests excluded from the count; report the count with `git diff --stat main`).
Report ONLY numbers you produced this session from files under /Users/James (this worktree:
/Users/James/ai-sandbox/stevecam-fe5). Long runs: nohup + short polling; never end your turn while one runs.
ONE-JOB SLOT: this Mac allows one heavy job at a time. Start EVERY engine/zmap/test run through
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
It waits for the slot by itself; just poll the log. Never run two at once.

## Starting point
- engine/entry_depth.py (from branch fe4-wip, already copied here): parse_nc, load_heightfield, LiveStock (disk_depth,
  stamp_chord), estimate_entries. Step 0 proved it misses none of the 230 zmap entries > 0.5 mm on out/fe2_finish.nc.
- FE4's ramp code lives on branch fe4-wip: read it with `git show fe4-wip:engine/finish.py` (read-only). KEEP ONLY its
  vertex-raise ramp: along the pass from p0 (z0), r(s) = z0 + s*tan(angle), L = depth/tan(angle); emit the pass's OWN
  vertices (plus one interpolated vertex at s = L) from s = L back to s = 0 with z = max(vertex z, r(s)), then cut the
  pass forward as today. Every emitted z >= the verified path z, so no new CL lookup. Do NOT bring over FE4's other
  ramps, zig-zag or its coarse stock estimate. A run shorter than L: ramp over the whole run at
  min(depth, s_run*tan(angle)) and report how many such entries remain (do not zig-zag).
- --ramp-angle-deg default 2.0, clamp [0.5, 15], <= 0 rejected; connector field ramp_angle_deg (default 2, separate from
  the rough's angle), runner passes it to finish and rest.

## (a) Which entries the estimator scores (mirror zmap's ZB domain)
Every pass-start descent INCLUDING down-link drops, plus in-pass descents steeper than 15 deg (angle from the chord's own
XY length and dZ). In-pass descents <= 15 deg are skipped (ZB does not score them).

## (b) Stock the estimator uses: the rough's own moves at 0.1 mm, no min-ing
Build the live stock at 0.1 mm cells from the rough program's OWN emitted moves: re-mill out/interim_rough.DO_NOT_RUN.nc
engine-side with a flat cylinder sweep (T13 flat, dia 12.686) starting from the box top Z 60.96 over
X -128.651..128.651, Y -82.55..82.55 (pad the grid by the tool radius). No min() of any kind against the part, the
0.5 mm stock or anything else: the swept heightfield is the stock. Only if that is infeasible in time/memory, fall back
to max-resampling out/interim_rough_engine_stock.npy (0.5 mm, never min) and say so. Then the finish stamps its own
moves into it (ball 9.525, r 4.7625) and the rest scores against the finish-updated stock (ball 3.142, r 1.571).

## Ramp rule
Ramp an entry only where the estimator's live depth > 0.25 mm. All other entries stay exactly as today.

## Proof the estimator never under-reads (do this BEFORE judging the ramps)
Run zmap's ZB chain (out/ball_axial.py is a template; point it at THIS worktree's verify/zmap.py and the interim chain:
part out/interim_part_hf01.npy; rough out/interim_rough.DO_NOT_RUN.nc flat 12.686; then the finish T20 ball 9.525 corner
4.7625; then the rest T33 ball 3.142 corner 1.571; chain stock_init). For the UNRAMPED out/fe2_finish.nc and
out/fe2_rest.nc, dump zmap's per-entry depth (res["_axial_raw"]: line, x, y, depth_mm) and the estimator's depth for the
same lines. Under-read = zmap depth - estimator depth. REQUIRED: worst under-read <= 0.15 mm on finish AND rest, and
every zmap entry > 0.25 mm is also > 0.25 mm in the estimator. Report worst under-read, worst over-read, counts.
If it fails, stop and report; do not tune ramps around it.

## Judge and merge bar (all on the interim chain)
Generate finish and rest from out/interim_model.stl with the connector/runner.py flags (stepover 0.3, stepdown 0.3,
slope 40, floor 24.765, feeds 3429/1270, post-grid 0.001), --stock-from out/interim_rough_engine_stock.npy (or your 0.1 mm
stock if you plumb it; say which).
- ZB axial 0 on finish and rest (BALL_AXIAL_FLOOR 0.5); zmap gouges / rapid collisions / holder / over-flute /
  outside_grid 0.
- exact clcheck (engine/probe_clcheck.py) below_cl 0 on the POSTED finish and rest.
- finish cycle <= 6958 s; rest cycle <= 465.5 s (FE2 rest 405.5 s + 60).
- Entry counts: ramped / short-run / unchanged, finish and rest.
- scripts/check_fixtures.py ok; engine/test_entry_depth.py, engine/test_finish.py, engine/test_engine.py (VibeCAD python
  /Applications/VibeCAD.app/Contents/Resources/bin/python, run as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes.
Add one test in engine/test_entry_depth.py that fails if (a)'s domain drops a down-link drop or scores a shallow in-pass
descent, and one in engine/test_finish.py that fails if a ramp vertex z goes below the verified path z.
Write engine/FE5_1_RESULTS.md with every number above and the exact commands. Then stop.

## RESUME (supervisor): the proof failure's cause is known - fix it, then re-prove
Your first proof failed (worst under-read 14.5 mm finish / 2.9 mm rest). Cause: engine/entry_depth.py stamp_flat_chord
tests coverage with `perp2 <= R^2` only, inside a bounding-box window, so cells PAST the chord's ends (up to ~0.41 R on
diagonals) get stamped with the end-point Z. Fix: a cell is covered iff its true distance to the SEGMENT is <= R:
  perp2 + (clip(sp, 0, Lxy) - sp)^2 <= R^2      (the same capsule test the ball stamp already uses via d2)
Keep the lowest-tip z rule as it is. Add a unit test in engine/test_entry_depth.py: stamp ONE chord, straight (along X)
and diagonal (45 deg), on a flat 0.1 mm grid; every cell whose centre is outside the capsule (end caps included) must be
untouched, and every cell inside must be lowered. It must fail on the old code.
Then rebuild the 0.1 mm rough stock and re-run the under-read proof against zmap's chain stock exactly as before:
REQUIRED worst under-read <= 0.15 mm at every finish AND rest entry footprint, and every zmap entry > 0.25 mm also
> 0.25 mm in the estimator. If it STILL fails: report the worst 5 locations (line, x, y, zmap depth, estimator depth,
zmap stock vs your stock at the footprint) and STOP before writing any more code. Only if it passes, continue with the
ramps, judge and merge bar above.
