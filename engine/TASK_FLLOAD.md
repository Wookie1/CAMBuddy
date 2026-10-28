# Task FL-LOAD: optional rough feed limiter (default OFF) - slow the feed only where the rough tool is overloaded. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh). If a run would exceed 10 min, don't
start it; write what you would have run into the results file. The supervisor runs the Core Front rough with the flag on and off,
judges it and times it.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT edit verify/
or opencode.json; engine code NEVER imports zmap/verify and never reads a zmap output (tests may import zmap); numpy + stdlib only,
install NOTHING. With the flag OFF every emitted program must be BYTE-IDENTICAL to main's. With the flag ON the XYZ path must be
identical (only F words change and moves are split collinearly at window boundaries).
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-fll/scratch/ - never /tmp.
RESULTS: create engine/FLLOAD_RESULTS.md EARLY and keep it current: after EVERY test run append the test, its exit code and what it
printed. Report only numbers you measured; name only tests that exist in this worktree.
CONTINUE: continue from your plan; don't stop before every red test exists and has run on the UNCHANGED code, and every test below
has run.
FRESH session, TIME BUDGET 60 min, HARD STOP 90 min (run `date` at start and check it). Worktree /Users/James/ai-sandbox/stevecam-fll,
branch fl-load at the commit carrying this brief (= main 9d4bc89 + brief). Report changed non-test line count
(`git diff --numstat 9d4bc89 -- engine connector ':!*test_*' ':!*TASK_*' ':!*RESULTS*'`); aim <= 120.
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>.
Engine test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /Applications/VibeCAD.app/Contents/Resources/bin/python -c "import sys; sys.path.insert(0,'.'); import engine.test_flload as t; t.<test_name>()"
Connector/verify test: /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- James's load rule (verify/zmap.py ~1104 _ae2_engagement_keys, ZE2L): per window, load = ae_eff * a * F / (2.032 * 19.05 * Fcut),
  Fcut = the op's cutting feed (rough default --cut-feed 3429). A window is an "allowed floor turn" (ZE2F2) when it carries a
  helix_pitch, a <= helix_pitch + 0.05 and load <= 1.2. Over-limit = load > 1.2 and not allowed. Read zmap's ae2 windowing to
  understand it; do NOT import or call it from engine code.
- Measured on the Core Front rough (chain9, = main's rough code) by zmap --load-rule: 134 flagged windows / 157.6 mm, 56 / 65.9 mm
  with load > 1.2, max load 3.03 (Z 42.354, a 18.6, ae ~6, F 3429).
- Rough moves are dicts {g, x, y, z, f, ...}; engine/cli.py rough_main (~746) calls roughmod.rough(...) then (if --stock-out)
  entry_depth.replay_stock(moves, ...) then posts. entry_depth.replay_stock replays moves into the engine's 0.1 mm stock
  (bit-identical to the RR-STOCK reference); its stamping helpers live beside it.
- Connector options live in connector/catalog.py (_CUTTING_INPUTS / options schema) and are passed to the engine CLI by
  connector/runner.py (rough command built ~1210).
## Items
1. Engine post-pass after the rough emit (new function, e.g. engine/load_limit.py limit_feeds(moves, dia, corner, box, top_z,
   cut_feed, ...)): replay the emitted moves into the engine's own 0.1 mm stock move by move (reuse entry_depth's stamping; G0
   never cuts); for each feed move measure, against the stock BEFORE that move, ae (radial engagement, removed area / length over
   ~1 mm windows) and a (axial depth removed), and load = ae*a*F/(2.032*19.05*Fcut).
2. Where load > 1.2 and the window is not an allowed floor turn (rule above): F_new = F*1.2/load on that window only, splitting
   the move collinearly at the window boundaries (XYZ identical; only split points + F). Never raise a feed (F_new <= F). Feed
   floor 25% of Fcut: if it binds, use the floor and count the window as floor_bound. Stats: windows_slowed, mm_slowed,
   min_feed, floor_bound.
3. Behind engine.cli rough --load-limit (store_true, default off) and connector option load_limit (boolean, default false,
   passed as --load-limit only when true). Flag off: the post-pass is not run at all.
RED TESTS (new file engine/test_flload.py; write first, run on the UNCHANGED code, paste numbers):
 (a) test_flload_corner_scene_load: a small synthetic scene (flat 12.686 tool, a pocket corner / ring stretch where full-depth
     side cuts give zmap --load-rule windows with load > 1.2 on base - measure and paste the count and max). With --load-limit:
     zmap --load-rule (test may import verify.zmap) reports 0 windows with load > 1.2 (beyond floor_bound ones, reported).
 (b) test_flload_path_identity: flag on, merge collinear consecutive feed moves of both programs; the XYZ polylines are
     identical within 1e-6.
 (c) test_flload_off_byte_identical: flag off -> the posted program bytes equal main's emitter output on the same scene (and
     equal the program produced without the option on a second small scene).
MUTATIONS (scratch copies, each must make a test fail by a MEASURED value; paste it): M1 drop the 1.2 cap (slow every window or
none), M2 drop the split (slow the whole move), M3 invert the floor-turn exclusion.
AT-RISK (must stay green; run ALL, paste exit codes): engine/test_entry_depth.py, engine/test_rsspeed.py both tests,
engine/test_rrstock2.py both tests (one per process), test_engine.py test_rough_testblock_r2 and test_dt1_synthetic_rough_twice_identical,
connector/test_connector.py -k "option or catalog or rough" EXCEPT the long TB E2E (the supervisor runs it).
## engine/FLLOAD_RESULTS.md: change (file:line), line count, red tests before/after with pasted numbers, mutation table with the
measured failure for each, PASTED exit codes, git diff --numstat. Then stop.
(Supervisor verifies from committed code: CF rough flag off byte-identical to main; flag on judged by zw2 with --load-rule:
windows slowed, mm slowed, min feed, floor_bound, cycle-time delta, max load after, gates clcheck/zmap/ZB 0; mutations re-run.)
