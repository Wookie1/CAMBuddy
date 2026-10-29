# SP-K1 results (compiled C kernel for load_limit._stamp_move)

Started: 2026-10-29, session sp-k1. Brief: engine/TASK_SPK1.md @ 7fe4629.
STATUS: COMPLETE — all new tests and the at-risk existing tests PASS. Not committed (per round rules).

## What was built
- engine/ckern/stamp.c — exported `int stamp_move(...)` (exact signature from
  the brief) reproducing `_stamp_move` operation-for-operation, plus the
  exported sample-t helper `void sample_ts(long n, double *out)`
  (step = 1.0/n, t_i = i*step + 0.0, last = 1.0 — verified equal to
  numpy 1.26 `np.linspace(0.0, 1.0, n+1)`, which has no midpoint correction).
  dmax mirrors np.max incl. NaN propagation; `R + 1e-9` and `cr*cr` each
  computed once; area += (count*fine)*fine; w = fmin(w, newv) in place.
- engine/ckern/build.sh — `clang -O3 -ffp-contract=off -fno-fast-math -shared
  -o engine/ckern/libstamp.dylib engine/ckern/stamp.c` (Apple clang 21, arm64).
- engine/ckern/__init__.py — ctypes loader; `get_lib()` returns None when the
  .dylib is missing; `stamp_move()` asserts L is float64 C-contiguous.
- engine/load_limit.py — `_stamp_move` dispatches to the C twin when the
  library loaded and STEVECAM_NO_CKERN is unset; otherwise the existing Python
  body runs unchanged. Prints the chosen path once
  ("load_limit._stamp_move: compiled C (ckern) kernel" / "... Python kernel").
- .gitignore += engine/ckern/libstamp.dylib (built artifact; source+script only are committable).
- engine/test_sp_k1.py — keeps a verbatim copy of the old body as
  `_stamp_move_ref`; tests (a)-(d). No existing test or function was modified.

## Test results (all via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh, foreground)

- [run 1] test_sp_k1(a) sample_ts vs np.linspace (n=1..20000 + 50 random up to 490754): PASS, exit=0.
- [run 2] test_sp_k1(b) 3018 moves (3000 random: flat cr=0 and bull cr=0.127 at
  R=6.35, R=3.175 flat; horizontal/ramped/vertical/zero-length; windows clipped
  at grid edges and fully outside; + 18 crafted exact-boundary moves) on random
  stock with -inf padding, C vs _stamp_move_ref: PASS (0 mismatches; L
  np.array_equal + tobytes-identical after every move, (area, depth) ==;
  22 exact dd==R boundary cells), exit=0.
- [run 3] test_sp_k1(c) limit_feeds on the synth_pocket flat rough (flat:6.0,
  stock -31..31/-1..12.4, same params as test_sp_p1a), C vs STEVECAM_NO_CKERN=1:
  PASS — 15805 output moves identical, stats dict identical
  {windows_slowed 0, mm_slowed 0, min_feed 1270.0, floor_bound 0}, returned
  stock array_equal, origin/cell equal, exit=0.
- [run 4] test_sp_k1(d) first attempt: FAIL exit=1 — mutation R-1e-9 not caught
  (0 mismatches). Cause: crafted dd==R moves were interleaved, so earlier random
  moves had lowered the raised boundary cells below the crafted stamp z and the
  inside-test margin was indistinguishable. Fix: crafted moves run FIRST on the
  pristine raised stock (_scenario reorder); test (b) re-verified.
- [run 5] test_sp_k1(b) re-run: PASS (0/3018) + test_sp_k1(d): PASS, exit=0.
  Mutation mismatch counts (of 3018 moves, scratch builds in temp dirs, the
  committed source never touched, temp dirs removed):
    R+1e-9 -> R-1e-9          40
    skip the last sample      2965
    area = count*(fine*fine)  40
    -ffp-contract=fast (info) 2664  -> fast-math contraction IS caught.
- [run 6] existing at-risk engine/test_flload.py (corner_scene_load,
  path_identity, off_byte_identical, trigger_margin) with the C kernel active:
  PASS, exit=0 (flload(a) stats {windows_slowed 4, floor_bound 1}; flag-off
  bytes identical on both scenes).
- [run 7] existing at-risk engine/test_sp_p1a.py (one_replay vs forced replay):
  PASS, exit=0 — stock (680,680) byte-identical .npy/.json/.nc.
- [run 8] speed info (same lane): 60 scenario moves ref 0.615s vs C 0.243s
  (2.5x); 2000 short 0.2-1.2 mm moves ref 3.983s vs C 1.627s (2.4x).
  STEVECAM_NO_CKERN=1 prints "load_limit._stamp_move: Python kernel" and runs
  the untouched Python body.
- [run 9] FINAL consolidated run `python -m engine.test_sp_k1` (a,b,c,d in one
  process): 4 PASS lines, exit=0.

## Diff size (git diff --numstat, tracked)
    1   0   .gitignore
    22  0   engine/load_limit.py
    26  4   opencode.json   (pre-existing, not touched this round)
New (untracked): engine/SPK1_RESULTS.md, engine/test_sp_k1.py,
engine/ckern/{stamp.c, build.sh, __init__.py} (libstamp.dylib gitignored).

## Notes / caveats
- numpy 1.26 linspace was read in site-packages and confirmed: div=n,
  y=arange(n+1)*step, +=start, y[-1]=stop; no midpoint fix-up — the brief's
  formula is exact (test (a) proves it, not assumed).
- hypot/fmin/fmax/sqrt resolve to the same libm numpy calls; bit-identity is
  demonstrated by (b)/(c) rather than assumed.
- Full suites and all Core Front jobs are left to the supervisor (per brief).
