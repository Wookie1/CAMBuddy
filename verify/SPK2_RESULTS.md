# SP-K2 results — C kernel for zmap per-sample stock cut

Session start: Thu 2026-10-29, hard 2 h cap. All test commands run through
`/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh` (small-test lane), foreground only.

## Plan
1. Environment probe (cc, pytest, numpy) via lane. [running]
2. Write verify/zkern/zcut.c + verify/zkern/__init__.py (own ctypes loader, auto-build,
   -O3 -ffp-contract=off -fno-fast-math).
3. Wire simulate() to the C path (guarded by lib loaded + ZMAP_NO_CKERN unset);
   report JSON gets "zcut_kernel": "c"|"python".
4. New verify/test_sp_k2.py: 5,000 random-sample equivalence vs *_ref copy of the
   Python block; full test_zmap.py on C path and with ZMAP_NO_CKERN=1;
   judge-fault gate-count equality on both paths.
5. Scratch mutations of the C (mask R+1e-9 -> R-1e-3; skip stock update; off-by-one
   window) — each must fail a test by a measured count.

## Log

- (init) file created before any code. `git diff --numstat` at start: 26 4 opencode.json
  (pre-existing, not mine).

- kernel + loader written; wired into simulate/parallel/CLI report
  ("zcut_kernel"). Smoke via lane (`/opt/homebrew/bin/python3`):
  gcode w/ flat+bull+ball, engage_max=5.0, C path vs ZMAP_NO_CKERN=1 path:
  exit=0 both; stock grids tobytes-identical (True/True/True); full report
  dicts (incl _ae2/_zb raw) compared key-by-key: 0 mismatches.
- `git diff --numstat`: (below)

- verify/test_sp_k2.py written. Two real kernel bugs found by the 5k-sample
  test and FIXED in zcut.c:
  1. FWD hist bin: numpy astype(int64) saturates +inf -> INT64_MAX -> bin 99;
     C cast of +inf is UB. Now saturates explicitly.
  2. ZE2B pre-snapshot indexing: prow was row-offset but indexed with the
     global column (missing -pre_ilo) -> wrong/OOB reads when pre_ilo > 0.
  Note: zb_dext uses CPython math.hypot (correctly rounded) vs libm hypot in
  C: differs by <=2 ulp, judged at the 1e-9 bar (numpy hypot == libm, so the
  stock grid stays bit-identical).
- test_c_kernel_matches_python_block_5000_samples (5,000 samples): PASS exit=0

- test_sp_k2.py::test_fault_programs_identical_on_both_paths: PASS exit=0.
  gate counts (c, python) identical:
    gouge    rc(1,1) gouges(720,720) axial(1,1) rapids(0,0)
    slot     rc(1,1) gouges(720,720) axial(1,1) eng(2,2)
    plunge   rc(1,1) gouges(352,352) axial(1,1)
    ball_slot rc(1,1) ze2b_full(1,1) ze2b_over(2,2) eng(2,2) axial(1,1)
  (full report JSONs compared key-by-key: 0 fields outside the bar)
- test_zmap.py, C path:      132 passed, 1 FAILED (exit=1)
- test_zmap.py, NO_CKERN=1:  132 passed, 1 FAILED (exit=1)
  The one failure is test_axial_real_core_front_rough_fails (FileNotFound-
  Error: the real Core Front sample is not in this worktree). VERIFIED
  PRE-EXISTING: fails identically on clean HEAD (git stash, exit=1) and is
  a Core Front file we must not run here. Both paths fail identically.
- test_zmap.py edit (1 line, helper only): _assert_pinned_plus_zg1 now also
  allows the brief-mandated "zcut_kernel" key in its extra-key set; every
  pinned b1688b8 value is still byte-compared. Without it the brief's two
  mandates (add the key; suite passes) are unsatisfiable. No test deleted,
  renamed or weakened otherwise.

- test_sp_k2.py full: 2 passed, exit=0 (5,000-sample equivalence + fault
  programs). `git diff --numstat`: 26 4 opencode.json (pre-existing),
  3 1 verify/test_zmap.py (helper key-set), 77 0 verify/zmap.py.

- Speed (foreground, lane): 20-pass ball raster (cell 0.25, 400x400):
  C 0.38 s vs Python 1.47 s (3.9x); ball slot 400^2 cell 0.05:
  C 0.27 s vs Python 0.47 s. Remaining Python time is the parts the brief
  keeps in Python (sampling, bookkeeping, reporting).

## Mutation runs

### M1: mask radius R + 1e-9 -> R - 1e-3 (zcut.c `Rm`)
- test_sp_k2.py: 2 failed, exit=1
  * 5,000-sample equivalence: FAILED "2322/5000 samples mismatched"
  * fault-programs identical: FAILED (engagement/ze2b floats outside bar)
- test_zmap.py (C path): 2 failed / 131 passed, exit=1
  * NEW failure vs baseline: test_vertical_wall_ball_gouge
  * (plus the pre-existing Core Front FileNotFoundError)
- (M1 fault-test detail, corrected): fails on /plunge/max_depth_mm
  2.000 (C) vs 1.989 (python) — the narrowed mask skips the deepest rim cell;
  exit code and gate COUNTS still matched.

### M2: skip the stock update (`if (0 && removed > eps)`)
- test_sp_k2.py: 2 failed, exit=1
  * 5,000-sample equivalence: FAILED "1244/5000 samples mismatched"
    (stock window bytes differ + updated flag)
  * fault-programs identical: FAILED — 157 report fields outside the bar,
    gate COUNTS changed: gouge/gouges/count 0 (C) vs 720 (python),
    slot/gouges/count 0 vs 720 (stock never lowers -> no gouge judged)
- test_zmap.py (C path): 35 failed / 98 passed, exit=1

### M3: window off-by-one (ihi = i0 + k, jhi = j0 + k instead of + k + 1)
- test_sp_k2.py: 1 failed / 1 passed, exit=1
  * 5,000-sample equivalence: FAILED "429/5000 samples mismatched"
    (dropped last window row/col: stock bytes, air/engaged, removed, dmax)
  * fault-programs identical: PASSED (gate counts insensitive here; the
    equivalence test is the measured catch)
- test_zmap.py (C path): 1 failed / 132 passed, exit=1 — the failure is only
  the pre-existing Core Front FileNotFoundError: the existing suite does NOT
  see this mutation, the SP-K2 equivalence test does (429/5000).

### Mutation summary (each caught by a test, with measured counts)
| mutation                | test_sp_k2 5k-sample | fault JSON fields | test_zmap fails |
|-------------------------|----------------------|-------------------|-----------------|
| M1 mask R-1e-3          | 2322/5000 mismatched | 2 (max_depth bar) | 1 new (vertical_wall_ball_gouge) |
| M2 skip stock update    | 1244/5000 mismatched | 157 (counts move: gouges 0 vs 720) | 35 |
| M3 window off-by-one    |  429/5000 mismatched | 0                 | 0 new           |

## Final verification (zcut.c byte-identical to the pre-mutation file,
## diff vs /tmp/zcut_orig.c = IDENTICAL, zero MUTATION markers)
- test_sp_k2.py: 2 passed, exit=0 (5,000/5,000 samples match; stock grids
  tobytes-identical; 4 fault programs: full report JSONs identical within the
  bar, gate counts and exit codes identical on C and Python paths).
- test_sp_k2.py with ZMAP_NO_CKERN=1: 2 skipped (C-kernel tests skip when
  the kernel is off), exit=0.
- test_zmap.py C path:      132 passed / 1 pre-existing failure, exit=1.
- test_zmap.py NO_CKERN=1:  132 passed / 1 pre-existing failure, exit=1.
  (the one failure = test_axial_real_core_front_rough_fails, a missing real
  Core Front sample file, fails identically on clean HEAD; not runnable in
  this round per the no-Core-Front-jobs rule.)

## Deliverables
- verify/zkern/zcut.c        NEW, independently written C kernel (one export
  zcut_sample): early-out, hypot/mask (+ window mask), flat/bull/ball tool
  surface, removed, nrem + FWD histogram, ZE2B quantities, engagement chord,
  in-place stock update; returns the scalars/flags for the Python loop.
- verify/zkern/__init__.py   NEW ctypes loader with auto-build
  (-O3 -ffp-contract=off -fno-fast-math), own code, no engine imports;
  returns None on ZMAP_NO_CKERN, compiler/build failure -> Python path.
- verify/zmap.py             +77 lines: guarded kernel branch before the
  untouched Python block; near-mask/shank/holder/per-move bookkeeping and
  reporting unchanged; report "zcut_kernel": "c"|"python" in simulate result,
  parallel combine and CLI report JSON.
- verify/test_zmap.py        +3/-1: ONLY the pinned-JSON helper now also
  allows the mandated "zcut_kernel" key (all pinned values still
  byte-compared). No test deleted or weakened.
- verify/test_sp_k2.py       NEW tests (5k-sample equivalence + fault-program
  both-path report equality).
- zkern/libzcut.dylib is a build artifact (untracked; auto-rebuilt when
  zcut.c is newer).

## Final `git diff --numstat`
26	4	opencode.json
3	1	verify/test_zmap.py
77	0	verify/zmap.py
 M opencode.json
 M verify/test_zmap.py
 M verify/zmap.py
?? verify/SPK2_RESULTS.md
?? verify/test_sp_k2.py
?? verify/zkern/
