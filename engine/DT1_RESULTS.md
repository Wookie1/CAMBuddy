# Task DT1 results — rough NGC byte-identical run to run

Branch dt1 (= main 3e8b7b5), worktree /Users/James/ai-sandbox/stevecam-dt1. Not committed.
All numbers below produced THIS session from files under /Users James (except where explicitly
marked as the supervisor's pre-existing baseline evidence, read only via cmp).

## Change (engine/rough.py, +30/-14 = 44 lines; engine/test_engine.py +77 test lines)
Deterministic tie-breaking in every NN ordering; no behaviour change beyond exact ties:
1. New `_nn_order(phase, cand, pos)` helper (RT travel order): region ties broken by the
   LOWEST region index (`key=(dist, k)`), entry-point ties within a region by
   `(dist, x, y)` — never by candidate/phase list order. plan()'s inline NN loop now calls it
   (HR1 a2d-then-rings phase split preserved).
2. Entry selection per region (was `min(cand[k], key=dist)`): tie-break `(dist, x, y)`.
3. Helix circle start (was `min(circ[:-1], key=dist)`): tie-break `(dist, x, y)`.
No set/dict iteration reaches output: the only sets (mandatory/hoist levels) are membership
tests or already fed through `sorted()` (insert_levels, mandatory_flat_levels) — verified by
grep, no change needed there.

## Proof: test block, new code, run twice (via slot_m4.sh)
- out/dt1_tb_new_a.ngc: 35,878 moves in 42.3 s; out/dt1_tb_new_b.ngc: 35,878 moves in 41.1 s
- `cmp out/dt1_tb_new_a.ngc out/dt1_tb_new_b.ngc` -> **identical** (NEW_TB_IDENTICAL)

## Proof: test block, main code, run twice BEFORE the edit (via slot_m4.sh)
- out/dt1_tb_main_a.ngc / out/dt1_tb_main_b.ngc: 35,878 moves each
- `cmp` -> **identical** (MAIN_TB_IDENTICAL): on the test block main happens to tie identically
  (2 runs). Given byte-identical region lists, main's `min(...)` is deterministic within/between
  processes; the instability only manifests when upstream (worker/Adaptive2d) order varies or a
  tie exists — demonstrated directly below and in the supervisor's Core Front pair.

## Main is NOT stable — differing pair + tie demonstration
- Supervisor baseline (pre-existing out/dt1_main_a.ngc vs out/dt1_main_b.ngc, Core Front, NOT
  produced by me — read with cmp only): `differ: char 7509776, line 202884` (~Z 39.6 level),
  matching the task evidence (~150 G0 rapid-order lines, cuts identical).
- In-test reproduction (test_dt1_nn_order_ties_stable): with pos (0,0) and two exactly-equal
  entry candidates pa=(0,5), pb=(0,-5), main's verbatim inline loop returns the rapid target
  by **list order** ((0.0, 5.0) vs (0.0, -5.0) for the two candidate orders); `_nn_order`
  returns pb in both orders, and region ties resolve to the lowest index regardless of phase
  order. The test fails if any tie is resolved by iteration order.

## zmap gates on the new program (test block, my run: out/dt1_tb_new_zmap.json)
gouges 0 (max_depth 0.0), rapid_collisions 0, axial_plunges 0 (max_depth 0.0 mm),
outside_grid 0. cutting 14,234.1 mm, rapid 1,048.5 mm, cycle time 358.7 s,
over-engage windows (>2.438) 3,786 (max ae 12.686 — rough entries/helix, unchanged class of
windows; engage gate is the Core Front judge).

## Cut moves unchanged vs main
Sorted G1 multisets: 35,805 lines (main) vs 35,805 lines (new) -> `cmp` **same**
(G1_MULTISET_SAME). Whole-file diff main vs new is therefore rapid/entry ORDER only (ties).

## Suites (all via slot_m4.sh, real exit codes)
- scripts/check_fixtures.py: **10 ok, 0 bad**, exit 0 (5 frozen fixtures were MISSING in this
  fresh worktree — same as HR1; copied sha256-manifest-verified from
  /Users/James/ai-sandbox/stevecam-hr1/out, no engine job run)
- engine/test_engine.py (VibeCAD python): **0 failure(s)** — includes new
  test_dt1_nn_order_ties_stable and test_dt1_synthetic_rough_twice_identical
  (synthetic slab roughed twice in-process: identical move lists, 1,486,530 chars)
- engine/test_finish.py (VibeCAD python): **ALL FINISH TESTS PASSED**
- /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q:
  **218 passed**, 32 warnings, 957.45 s, exit 0

## Exact commands
    PY=/Applications/VibeCAD.app/Contents/Resources/bin/python
    TB="--step samples/test_block.step --stock -50 50 -40 40 0 38 --tool flat:12.686 \
        --floor 20 --leave 0.381 --final-zmin 20.381 --stepdown 19.05 \
        --optimal-load-mm 2.032 --hf out/test_block_hf_0.5.npy"
    nohup .../scratchpad/slot_m4.sh bash out/dt1_tb_main.sh > out/oc_dt1_tbmain.log 2>&1 &   # main x2 + cmp
    nohup .../scratchpad/slot_m4.sh bash out/dt1_verify.sh  > out/oc_dt1_verify.log  2>&1 &   # new x2, cmp, zmap, G1 multiset
    nohup .../scratchpad/slot_m4.sh bash out/dt1_rest.sh    > out/oc_dt1_rest.log    2>&1 &   # fixtures + suites
    # zmap (inside dt1_verify.sh):
    $PY verify/zmap.py out/dt1_tb_new_a.ngc --part out/test_block_hf_0.1.npy --tool flat \
      --dia 12.686 --stock -50 50 -40 40 0 38 --engage-max 2.438 \
      --ae2-dump out/dt1_tb_new_ae2.json --out-json out/dt1_tb_new_zmap.json

ENGINE_WORKERS capped at 4 by slot_m4.sh; no Core Front job was run. opencode.json shows as
modified in git status — pre-existing, not touched this session. Core Front run-twice left to
the supervisor. Then stop.
