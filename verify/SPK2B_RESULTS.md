# SP-K2B results — zmap's whole per-sample loop for one move in C

Task: move zmap's whole per-sample loop for one move into C (speed; same
verdicts). Session start Thu 2026-10-29, hard 2 h cap. All test commands
run in the FOREGROUND through the small-test lane
`/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh`. No Core Front job run.

## What was built

- **verify/zkern/zcut.c** — added `zcut_move()`: ONE call per move running,
  per sample in the current Python order, the near-mask precheck (with its
  air_length rule), the shank block, the holder block and the SP-K2 cut
  block (`zcut_sample`, kept unchanged for its tests). Takes a
  `ZMoveParams` struct pointer + the move's flat (n,3) sample array.
  Accumulates every per-move value the Python per-move code reads:
  move_shank, shank_depth, shank_worst_xy, move_holder, holder_intrusion,
  holder_worst_xy, air_length, move_area, move_hist, the ZE2B accumulators,
  removed/nrem/dmax/ew/collided folding. Worst-xy reproduces np.argmin's
  tie rule exactly (first index in row-major order among equal minima,
  same `cand` expression, strict `<` scan j-outer/i-inner); NaN/±0 rules of
  np.max/np.maximum/np.where mirrored (nm/nn helpers).
  - `air_length`, `shank_depth`, `holder_intrusion` and the worst-xy pairs
    accumulate in a cross-move `ZRunState` ONE SAMPLE AT A TIME in the same
    order as the Python loop, so they are BIT-identical, not just within
    the bar (needed: test_zmap pins air_fraction byte-for-byte).
- **verify/zkern/__init__.py** — ZMoveParams/ZMoveOut/ZRunState ctypes
  mirrors + `zcut_move` argtypes in `load()`; auto-rebuild unchanged.
- **verify/zmap.py** — `simulate()` uses the per-move C path when the lib
  is loaded and ZMAP_NO_CKERN is unset: the whole `for (sx, sy, sz) in
  samples:` loop (near precheck, shank, holder, cut) is replaced by one
  `zcut_move` call per move; the Python loop is kept byte-identical under
  `else:` (used when no kernel). Sampling code (`_move_samples`) unchanged;
  samples go over as `np.asarray(samples, dtype=float)`. All per-move
  bookkeeping, reporting and the parallel combine stay in Python;
  shank/holder running accumulators and air_length are picked up from the
  run state after the move loop.
- **verify/test_sp_k2b.py** — NEW (only new tests added; no existing test
  touched).

## Test runs (small-test lane, foreground; exit codes pasted)

Interpreters: tests `/opt/homebrew/bin/python3 -m pytest` (pytest 9.1.1,
numpy 2.4.3); scratch/driver `/Applications/VibeCAD.app/Contents/
Resources/bin/python`.

1. Smoke (scratch, in-process C vs ZMAP_NO_CKERN path, flat/bull/ball,
   window on/off, shank+holder+engage_max on, arcs, rapids):
   5/5 cases stock tobytes-identical, full report diff 0 fields. exit=0
2. verify/test_sp_k2b.py::test_2000_random_moves_c_permove_equals_python
   **PASS exit=0** (6.6 s). 10 chains x 200 moves, shank AND holder ON,
   flat/bull/ball, near-mask on and off (window), moves clipped at the
   grid edges (targets outside the grid), rapids/arcs; chained move-by-
   move via stock_init so the stock is compared after EVERY move.
   stats: {'moves': 2000, 'shank_hits': 1303, 'holder_hits': 840,
   'rapids': 60, 'tie_checked': 80, 'plunge': 170}
   - per move: stock grids tobytes-identical AND the whole report dict
     compared key-by-key (ints/flags/lists identical, floats rel/abs 1e-9,
     numpy arrays array_equal): 0 mismatches.
   - exact argmin ties: every 25th move is a rapid + PURE vertical plunge
     onto an EXACT cell corner over a constant-height plateau (cell 0.5,
     power-of-two grid origins -> the 4 corner cells have bitwise-equal
     hypot distance); 80 such moves, shank AND holder worst_xy must equal
     the row-major-first corner cell [xs[i0-1], ys[j0-1]] — all matched.
3. verify/test_zmap.py, C path:            132 passed / 1 failed, exit=1
   verify/test_zmap.py, ZMAP_NO_CKERN=1:   132 passed / 1 failed, exit=1
   The ONE failure is the pre-existing
   test_axial_real_core_front_rough_fails (FileNotFoundError: the real
   Core Front sample is not in this worktree; SP-K2 verified it fails
   identically on clean HEAD, and Core Front jobs are banned this round).
   Identical on BOTH paths.
4. verify/test_sp_k2.py (SP-K2 per-sample kernel tests): PASS with the
   per-sample function kept; combined run
   test_sp_k2b.py + test_sp_k2.py: 3 passed, exit=0.

First C-path test_zmap run FAILED test_ze2b_flat_and_bull_json_byte_identical
(air_fraction 0.3894080996884731 vs pinned 0.38940809968847595): per-move
air sums folded into air_length changed the summation ORDER. FIXED by
accumulating air_length in the kernel one seg_len at a time in sample
order; re-run byte-identical (run 3 above). No test was edited.

## Mutation runs (scratch edits to zcut.c, each reverted)

Each mutation: rebuilt automatically (loader rebuilds on newer zcut.c),
test_sp_k2b.py run once, then `cp /tmp/zcut_k2b_orig.c` revert.
"Entries" = mismatch entries asserted in the test (one move can produce
several: report diff + shank tie + holder tie).

| # | mutation (zcut.c)                     | test_sp_k2b result                     | exit |
|---|---------------------------------------|----------------------------------------|------|
| M1| holder radius `dd <= Rh` -> `Rh + 0.5` (both vtop and worst loops) | 117 mismatch entries / 2000 moves (holder_hits count, max_intrusion, worst_xy) | 1 |
| M2| argmin tie taken as LAST (`c < best` -> `c <= best`, both worst fns) | 385 mismatch entries / 2000 moves (all 80 tie moves: worst_xy at the opposite corner) | 1 |
| M3| skip the near precheck (`if (0 && p->nearm ...)`) | 335 mismatch entries / 2000 moves (air_fraction/air_length on the window chains) | 1 |
| M4| drop the shank block (`if (0 && cutting && p->shank_on)`) | 1303 mismatch entries / 2000 moves (= exactly the 1303 shank-hit moves; count 0 vs N) | 1 |

After revert: `diff` vs the saved pre-mutation zcut.c = IDENTICAL, zero
mutation markers in the file; test_sp_k2b + test_sp_k2 re-run: 3 passed,
exit=0.

## Speed (TB programs, not CF; lane, foreground)

Part: out/tb_hf_0.1.npy = verify/heightfield.py of samples/test_block.step
at cell 0.1 (1000x800, x0=y0 grid -50..50 x -40..40; built with freecadcmd,
1.1 s — not a Core Front job). Programs generated for the TB geometry
(out/genk2b.py): tb_rough.ngc (flat 12.686, 2 raster levels 25.381/20.381,
stepover 2.032, engage_max 2.4384; 307,510 samples) and
tb_finish_lite.ngc (ball 5.958, one raster level 20.381, stepover 1.0,
engage_max 2.286; 311,251 samples). Driver out/speed_k2b.py <c|k2|py>
<reps>; "SP-K2" = the pre-task verify/zmap.py from 0be26c0 (per-sample
ctypes call) against the same zcut.c; best of 3 (C) / 2 (SP-K2) / 1 (py).

| program        | C per-move            | SP-K2 per-sample      | Python                |
|----------------|-----------------------|-----------------------|-----------------------|
| tb_rough       | 23.82 s, 77.5 us/samp | 24.63 s, 80.1 us/samp | 39.05 s, 127.0 us/samp|
| tb_finish_lite |  8.83 s, 28.4 us/samp |  9.60 s, 30.8 us/samp | 28.20 s, 90.6 us/samp |

vs Python: 1.64x / 3.20x. vs SP-K2: 1.03x / 1.09x — the saved per-sample
overhead is a flat ~2.6-3.1 us (30-arg ctypes call + Python sampling-loop
bookkeeping + floors), and these TB rasters use the 12.686 mm tool on a
0.1 mm grid, so every sample pays a 131x131-cell C window (compute-
dominated). The saving scales with SAMPLE COUNT, not window size: on a
Core Front rough (~11.5 M samples) it removes ~30 s of per-sample Python/
ctypes overhead and all shank/holder/near numpy allocations. exit=0 all.

## Final verification (all after mutation revert)
- test_sp_k2b.py + test_sp_k2.py: 3 passed, exit=0
- test_zmap.py C path: 132 passed / 1 pre-existing CF-file failure, exit=1
- test_zmap.py ZMAP_NO_CKERN=1: 132 passed / same 1 failure, exit=1

## Notes / constraints honoured
- No existing test edited; no behaviour/constant changed outside the
  kernel path; verify/ imports nothing from engine/.
- No Core Front job; full pytest suite NOT run (supervisor's job) — only
  test_sp_k2b.py, test_sp_k2.py and the at-risk test_zmap.py (both paths).
- Scratch kept out of the deliverables: out/{genk2b.py, speed_k2b.py,
  spk2_zmap.py, tb_*.ngc, tb_hf_0.1.npy/json} (out/ untracked),
  /tmp/zcut_k2b_orig.c (mutation revert copy).
- zkern/libzcut.dylib is a build artifact (untracked, auto-rebuilt).

## Final `git diff --numstat`
26	4	opencode.json (pre-existing, not mine)
89	0	verify/zkern/__init__.py
275	0	verify/zkern/zcut.c
271	218	verify/zmap.py  (bulk = re-indent of the untouched Python loop
                          under else:; 27 per-sample kernel lines removed)
?? verify/SPK2B_RESULTS.md
?? verify/test_sp_k2b.py
