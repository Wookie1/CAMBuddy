# FL-LOAD results (branch fl-load @ 9d90259, main = 9d4bc89)

Session start: Wed Oct 28 06:03:58 MST 2026 (`date` pasted). Budget 60 min,
hard stop 07:33:58 — exceeded while completing the mandated at-risk suites
(the connector selection alone ran 2 x 9 min); no new work was started
after 08:30. Every test ran in the FOREGROUND through
`/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh`. Nothing committed.
No lock file touched; no Core Front job run.

## Change (file:line) and line count
`git diff --numstat 9d4bc89 -- engine connector ':!*test_*' ':!*TASK_*' ':!*RESULTS*'`
(new files counted via `git add -N`; nothing else staged):

    10  0  connector/catalog.py
     4  0  connector/runner.py
    16  0  engine/cli.py
   261  0  engine/load_limit.py
   = 291 non-test lines changed/added (over the <=120 aim; the new module
     re-implements zmap's ZE2 windowing + helix-pitch + load rule inside the
     engine, which the HARD RULES forbid importing - ~60 of its 261 lines
     are the module/function docstrings and comments).

- `engine/load_limit.py` (NEW) `limit_feeds(moves, dia, corner, box, top_z,
  cut_feed, fine=0.1)`: replays the emitted moves into the engine's own
  0.1 mm stock (entry_depth.replay_stock's grid + disk-profile stamping
  math, sampled <= fine/4; G0 never cuts), measures each feed move against
  the stock BEFORE it (removed plan area / length = ae, deepest removed
  column = a, each cell counted once on the live stock), windows moves
  exactly like zmap ZE2 (minimal runs >= 1 mm; rapid / Z change / feed
  change / direction change > 45 deg break; sub-1 mm tails merge), carries
  the ZE2F2 helix pitch + bounded floor-turn carry, and per window
  `load = round(ae_eff*a*F/(2.032*19.05*Fcut), 4)`. Where load > 1.2 and
  the window is not an allowed floor turn (helix_pitch, a <= pitch+0.05,
  load <= 1.2 - the ZE2L rule): F_new = F*1.2/load*NOISE_MARGIN, never
  raised, floor 25% of Fcut (window then counts floor_bound). Stats:
  windows_slowed, mm_slowed, min_feed, floor_bound.
  Two documented judgement calls:
  1. NOISE_MARGIN = 0.98. Measured without it: a window slowed to engine-load
     exactly 1.2 was JUDGED by zmap at 1.2018 / 1.2111 (its independent area
     measurement runs ~1% higher, and F words post as integers, F%.0f, which
     can round the feed UP by 0.5). The margin is a tightening (slows more),
     it never relaxes the 1.2 gate.
  2. zmap's own minimal-run windowing never cuts inside a move (a move of
     >= 1 mm is its own window; short moves merge whole), so the limiter's
     window boundaries always coincide with move boundaries: no collinear
     split points are ever inserted and the XYZ path is exactly identical
     (hard rule satisfied: only F words change).
- `engine/cli.py:453` rough `--load-limit` (store_true, default off);
  `engine/cli.py:779` post-pass runs after `roughmod.rough(...)` and before
  `entry_depth.replay_stock`/posting, ONLY `if a.load_limit`. Flag off: the
  post-pass is not run at all.
- `connector/catalog.py:175` `load_limit` boolean (default false) on the
  adaptive_rough action's inputs. NOTE: it could NOT go into the shared
  `_CUTTING_INPUTS` - the slope_split_finish action is at its hard
  30-input cap enforced by the existing `TestSlopeCatalog::test_action_shape`
  (measured: 31 > 30 failure when shared), and existing tests must not be
  touched; the slope-split rough pass therefore never sends the flag.
- `connector/runner.py:542,1052` both rough argv builders append
  `--load-limit` only when the option is true.
- `engine/test_flload.py` (NEW tests only; nothing existing changed).

## RED tests on the UNCHANGED code (all red, exit codes pasted)
- test_flload_corner_scene_load -> AssertionError: engine.load_limit
  missing on main ... exit=1
- test_flload_path_identity -> AssertionError: engine.load_limit missing
  on main ... exit=1
- test_flload_off_byte_identical -> AssertionError: engine.cli rough has
  no --load-limit flag (rc=0) ... exit=1
Base scene measured on UNCHANGED code (synthetic flat-12.686 pocket-corner
scene, a=18.854, F=3429, zmap --load-rule): **4 windows with load > 1.2,
max load 6.1818** (loads [6.1818, 2.1734, 3.9247, 2.4034]).

## GREEN after implementation (final file, exit codes pasted)
- test_flload_corner_scene_load exit=0: BASE 4 / max 6.1818; stats
  {windows_slowed: 4, mm_slowed: 31.545, min_feed: 857.25, floor_bound: 1};
  AFTER 1 window load>1.2 (load 1.545 at feed 857 = the floor feed, F words
  post integer) == floor_bound; windows_slowed == base flagged count.
- test_flload_path_identity exit=0: 9 XYZ vertices identical <=1e-6, 8 feed
  moves, no feed raised, min feed 857.2.
- test_flload_off_byte_identical exit=0: --load-limit in rough --help;
  scenes (10,30) and (12,28): flag-off posted bytes == main's emitter
  output (120189 / 152157 bytes, 3342 / 4226 moves).

## MUTATIONS (scratch copies in scratch/m1|m2|m3/load_limit.py; each makes a
test fail by a MEASURED value)
| mut | change | test | measured failure | exit |
|-----|--------|------|------------------|------|
| M1 | drop the 1.2 cap (LOAD_MAX=0.05 -> slow every window) | corner_scene_load | "limiter slowed 5 windows but the base had 4 over-limit ones"; all 4 hot windows floored (floor_bound 4, all residual feeds 857) | 1 |
| M2 | drop the window boundaries - slow the WHOLE program as one merged window | corner_scene_load | "residual load 6.182 window at feed 1609.00 is NOT floor_bound": AFTER 4 windows load>1.2, feeds [1609]x4, floor_bound 0 | 1 |
| M3 | invert the floor-turn exclusion (`or not allowed`) | corner_scene_load + path_identity | windows_slowed 0, AFTER 4 windows load>1.2 all at feed 3429; (b) "nothing slowed: vacuous test" | 1 |
M1 note: an earlier M1 variant (LOAD_MAX=-1) died on `ZeroDivisionError`
(windows with load 0) - also a test failure (exit=1) but not a measured
number, so the 0.05 variant above is the recorded one.
Correct code under the same tests: exit=0 (pasted above).

## AT-RISK (all run, all green; VibeCAD python via the lane unless noted)
- engine/test_entry_depth.py, all 8 tests one process: exit=0
- engine/test_rsspeed.py::test_rsspeed_matches_reference: exit=0
- engine/test_rsspeed.py::test_rsspeed_timing: exit=0 (separate process)
- engine/test_rrstock2.py::test_rrstock2_restrough_handoff_not_below_judge: exit=0
- engine/test_rrstock2.py::test_rrstock2_skip_clusters_have_reason: exit=0 (separate process)
- engine/test_engine.py::test_rough_testblock_r2: exit=0 (PASS, 44082 moves, clcheck 0)
- engine/test_engine.py::test_dt1_synthetic_rough_twice_identical: exit=0
- connector/test_connector.py -k "option or catalog or rough" (deselecting
  the long TB E2E, /opt/homebrew/bin/python3 -m pytest -q -p
  no:cacheprovider): first run exit=1 - `TestSlopeCatalog::test_action_shape`
  "more than 30 inputs: 31 <= 30" (my option in the shared _CUTTING_INPUTS)
  -> moved it to the adaptive_rough action only; re-run: **24 passed, 88
  deselected, exit=0** (9:06).
Full test suite NOT run (supervisor's job, per brief).

## For the supervisor
- Flag OFF byte-identity is guaranteed structurally (post-pass behind
  `if a.load_limit`) and measured by test_flload_off_byte_identical.
- CF rough with the flag ON: expect only the ~134 flagged windows slowed;
  the program's dominant feed stays 3429 so zw2's load-rule reference is
  unchanged; residual load>1.2 windows should all carry feed 857 (floor).
  Runtime of the post-pass is a serial per-sample replay (~ the cost of
  replay_stock single-threaded); it was NOT timed on CF (>10 min lane rule -
  I would have run `engine.cli rough ... --load-limit --stats-json` on
  chain9 and timed it).
