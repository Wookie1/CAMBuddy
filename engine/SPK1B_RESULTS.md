# SP-K1B results (fast batched C stamping kernel + auto-build)

Started: 2026-10-29, session sp-k1b. Brief: engine/TASK_SPK1B.md @ dcf9b8f.
STATUS: COMPLETE — all new tests and all at-risk existing tests PASS. Not
committed (per round rules).

## Plan
1. stamp.c: (a) per-cell s=gx*gx+gy*gy classification (skip outside, flat/bull
   inner shortcuts), (b) per-row column skip, (c) per-sample early-out
   (no cell w > sz -> skip), (d) stamp_batch entry point (all G1 moves of a
   list in one C call, per-move (area, depth) arrays).
2. ckern/__init__.py: auto-build libstamp.dylib (xcrun/PATH clang, same flags
   as build.sh, temp file + atomic rename, Python fallback on any failure) +
   stamp_batch wrapper.
3. load_limit.limit_feeds: one batch call when the C kernel is live; Python
   path unchanged. cli.py: stats["stamp_kernel"] + print.
4. engine/test_sp_k1b.py: 10k-move parity (incl. bull cr=0.127 and cr=R,
   R=3.175/6.35, cells exactly at T and a0, edge clipping, +/-inf stock),
   batch == per-move, limit_feeds parity, mutations, speed.

## Test log (append after every run)

- [env] lane OK: numpy 1.26.4 / python 3.11.14 via slot_m4.sh. Darwin fmin
  probe: fmin(-0.0, +0.0) = -0.0 (signed zeros cannot witness a margin flip).
- [build] auto-build works: removed libstamp.dylib, `from engine import
  ckern` rebuilt it in 0.25 s (PATH clang first; raw xcrun --find clang
  lacks the SDK sysroot, so the xcrun fallback runs `xcrun clang`). exit=0.
- [smoke] 100 random moves, bull R=6.35 cr=0.127, stock with +inf cells and
  -inf pad rows: per-move C == _stamp_move_ref (0 mismatches), stamp_batch ==
  per-move C (L tobytes-identical, (area,depth) equal). exit=0.
  (First smoke FAIL was a bug in the throwaway smoke script itself: it
  compared the fully-batched L against a partially-ref-stamped L.)

- [run 1] existing at-risk test_sp_k1(a) sample_ts (new kernel active):
  PASS, exit=0.
- [run 2] NEW test_sp_k1b_random_moves: 10,108 moves (10,000 random + 108
  crafted) over 6 tools (flat / bull cr=0.127 / ball-like cr=R at R=6.35 and
  R=3.175), +inf and -inf interior stock cells, edge-clipped and fully
  outside windows; L tobytes-identical after EVERY move, (area, depth) ==
  _stamp_move_ref; stamp_batch == per-move (per-move area/depth AND final L
  per tool). Witnesses: dd==R 56, dd==T 36, dd==a0 52. PASS, exit=0.
  (RuntimeWarning "invalid value in subtract" comes from the REFERENCE's
  inf - inf on the +inf cells - expected.)
- [run 3] existing at-risk test_sp_k1(b) + test_sp_k1(d) (fast kernel,
  scratch mutation builds): PASS, exit=0. Mutation counts unchanged
  (40 / 2965 / 40; -ffp-contract=fast info 2664).

- [run 4] NEW test_sp_k1b_autobuild (subprocess): PASS, exit=0 — missing
  and stale libstamp.dylib both rebuilt by `import engine.ckern` /
  ensure_built(); a nonexistent clang leaves the old dylib untouched and
  raises nothing.
- [run 5] NEW test_sp_k1b_mutations, first attempt: FAIL exit=1 (harness
  bugs: scratch argtypes had 17/19 entries instead of 16/18; and the last
  per-tool random move happened to be zero-area, so "batch skips the last
  move" was invisible). Fix: test-file only — argtypes corrected; scenario
  gains one GUARANTEED-cutting zero-length "tail" move per tool (z=-10,
  below anything the earlier stamps can leave) so a dropped last batch move
  must show. Scenario is now 10,114 moves.
- [run 6] NEW test_sp_k1b_mutations: PASS, exit=0. Counts (of 10,114 moves
  / 6 per-tool batches; scratch builds in temp dirs, committed source never
  touched):
    outside margin (1+1e-9)->(1-1e-3)  4930   (caught)
    early-out w > sz -> w >= sz           0   (provably EQUIVALENT: the
        mutated skip {all w < sz} is a SUBSET of the correct skip
        {all w <= sz}; a w == sz cell can neither cut (newv >= sz) nor
        change L (fmin(w, newv) = w) — reported, not asserted)
    early-out w > sz -> w > sz + 0.5  10100   (caught; proves the
        early-out is live and load-bearing)
    batch skips the last move            10   (caught: 6 final-L + 4
        area/depth mismatches)
- [run 7] NEW test_sp_k1b_random_moves re-run on the 10,114-move scenario:
  PASS, exit=0 (bit-identical every move; batch == per-move; witnesses
  dd==R 56 / dd==T 36 / dd==a0 52).

- [run 8] NEW test_sp_k1b_limit_feeds_parity + existing test_sp_k1(c)
  (synth_pocket rough, 15,805 moves): PASS both, exit=0 — C batch vs
  STEVECAM_NO_CKERN identical moves/stats/stock bytes; stats
  {windows_slowed 0, mm_slowed 0, min_feed 1270.0, floor_bound 0}.
- [run 9] existing at-risk engine/test_flload.py (corner_scene_load,
  path_identity, off_byte_identical, trigger_margin) with the C batch
  active: PASS, exit=0 (flload(a) stats {windows_slowed 4, floor_bound 1};
  flag-off bytes identical on both scenes; CLI prints "stamp_kernel: c").
- [run 10] existing at-risk engine/test_sp_p1a.py (one_replay vs forced
  replay): PASS, exit=0 — stock (680,680) byte-identical .npy/.json/.nc.
- git diff --numstat (tracked): ckern/__init__.py 109/8, ckern/stamp.c
  165/39, cli.py 6/0, load_limit.py 25/3 (+ pre-existing opencode.json
  26/4, not touched this round). Untracked new: engine/test_sp_k1b.py,
  engine/SPK1B_RESULTS.md (libstamp.dylib gitignored).

- [run 11] NEW test_sp_k1b_speed, first attempt: FAIL exit=1 — the honest
  "SP-K1 C" baseline needs HEAD's stamp.c (the tree already carries the
  faster kernel); scratch-building it hit "stamp_batch symbol not found"
  (old kernel has no batch). Fix: test-file only — _spk1_scratch_lib()
  builds `git show HEAD:engine/ckern/stamp.c` and _lib_bindings(want_batch
  =False) for it. (An intermediate edit briefly corrupted the function
  boundary; corrected, file verified by re-running.)
- [run 12] NEW test_sp_k1b_speed (TB rough cached in scratch/, 73.9 s
  first-time emit via engine.cli rough on samples/test_block.step — NOT
  Core Front; slice tb[5000:25000]): PASS, exit=0. All four paths produced
  bit-identical stock:
    synth_pocket rough (flat D=6, 15,781 stamped moves), per-move:
      python 343.8 us | SP-K1 C 96.6 us (3.6x) | fast C 34.3 us (10.0x)
      | C batch 31.1 us (11.1x vs python, 3.1x vs SP-K1)
    TB rough 20k (flat D=12.686 -> 129x129 windows, 19,975 stamped moves):
      python 1168.4 us | SP-K1 C 474.5 us (2.5x, matching the brief's SP-K1
      figure) | fast C 165.1 us (7.1x) | C batch 160.7 us (7.3x vs python,
      3.0x vs SP-K1)
- [run 13] CLI end-to-end on synth_pocket with --stats-json: stats JSON
  gets "stamp_kernel": "c"; with STEVECAM_NO_CKERN=1 it prints
  "stamp_kernel: python" and the JSON says "python"; the two emitted .ngc
  files are byte-identical (cmp). PASS, exit=0.

## Code changes
- engine/ckern/stamp.c: static stamp_one() with (a) s=gx*gx+gy*gy cell
  classification (Tt/Tf/Tb margins, surf0 once), (b) per-row possibly-inside
  column range (+/-1..2 cell slack; skipped cells only take the +inf/NaN
  dmax-marker check, keeping NaN semantics bit-exact incl. fmin(NaN,inf)),
  per-cell cannot-cut skip w <= sz (finite w: cannot cut, fmin(w,newv)=w;
  NaN cells still run the full path), plus stamp_batch() (whole list, one
  call, scratch once, per-move (area,depth) arrays).
- engine/ckern/__init__.py: ensure_built() (missing/older than stamp.c ->
  clang same flags as build.sh, mkstemp in engine/ckern/ + os.replace; any
  failure = silent fallback to Python), stamp_batch() wrapper.
- engine/load_limit.py: limit_feeds resolves positions once, stamps all G1
  moves in ONE stamp_batch call when the C kernel is live; Python path and
  all bookkeeping (helix pitch, recs, windows) unchanged.
- engine/cli.py: rough stats["stamp_kernel"] = "c"/"python" + printed.

## Final consolidated run

- [run 14] `python -m engine.test_sp_k1` (a,b,c,d in one process, fast
  kernel active): PASS, exit=0.
- [run 15] `python -m engine.test_sp_k1b` (a,b,c,d,e in one process):
  PASS, exit=0 —
  (a) 10,114 moves bit-identical, batch == per-move;
  (b) limit_feeds C batch vs Python identical (15,805 moves);
  (c) auto-build missing/stale/broken-clang all correct;
  (d) mutations 4930 / 0 (equivalent, see note) / 10,100 / 10;
  (e) synth 353 -> 97 (SP-K1) -> 35 (fast) -> 31 us/move (11.3x python,
      3.1x SP-K1); TB 20k: 1272 -> 523 (SP-K1, 2.4x) -> 183 -> 179 us/move
      (7.1x python, 2.9x SP-K1), all paths bit-identical.
- Final git diff --numstat (tracked): engine/ckern/__init__.py 109/8,
  engine/ckern/stamp.c 165/39, engine/cli.py 6/0, engine/load_limit.py
  25/3 (+ pre-existing opencode.json 26/4, untouched this round).
  New untracked: engine/test_sp_k1b.py (711 lines), engine/SPK1B_RESULTS.md,
  scratch/ (TB-rough + CLI smoke caches; gitignored nowhere, left untracked,
  not committed). libstamp.dylib stays gitignored (auto-built).

## Notes / caveats
- (c) early-out is implemented PER CELL as "finite w <= sz cannot cut
  (newv >= sz everywhere) and fmin(w, newv) == w, so no newv is computed";
  a sample whose whole window is like that does no hypot, no newv and no
  write - the exact sample-level skip of the brief, and stronger. NaN stock
  cells deliberately still take the full path so fmin/fmax semantics stay
  identical to the old loop (NaN outside the circle even reproduces the old
  fmin(NaN, +inf) = +inf write via the marker).
- The "w >= sz instead of w > sz" mutation is PROVABLY equivalent: the
  mutated skip {all w < sz} is a subset of the correct skip {all w <= sz},
  and a w == sz cell can neither cut (newv >= sz) nor change L
  (fmin(w, newv) = w; Darwin fmin(-0.0, +0.0) = -0.0 probed). Measured
  count 0; reported as equivalent, and the over-skipping w > sz + 0.5
  variant (10,100 mismatches) proves the early-out itself is live.
- The +inf stock cells matter: the OLD loop's cut = inf - inf = NaN makes
  dmax = NaN (absorbing: cut > NaN is false), masking that sample's finite
  cuts from depth. The outside-cell marker (w == +inf or NaN -> dmax = NAN)
  keeps this bit-exact; the scenario includes ~1 % +inf cells and stays
  0-mismatch.
- xcrun --find clang returns a raw compiler WITHOUT the SDK sysroot (no
  math.h); the auto-build therefore prefers PATH clang (the build.sh shim)
  and falls back to `xcrun clang` (which supplies the SDK env).
- TB rough speed scene is emitted without --hf (out/*.npy heightfields are
  not built in this worktree); test_engine R2 previously showed the no-hf
  path emits identical moves. Program cached in scratch/spk1b_tb_rough.ngc.
- Full suites and all Core Front jobs are left to the supervisor (per
  brief). No existing test or function was modified or deleted;
  test_sp_k1.py is untouched (its _stamp_move_ref is imported read-only).
