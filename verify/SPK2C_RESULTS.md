# SP-K2C results — fast zcut.c per-move loop (cell culling, same verdicts)

Task: make verify/zkern/zcut.c's per-move loop fast while keeping verdicts
identical (stock bit-identical; ints/flags/lists/gates identical; floats
within rel/abs 1e-9). Session Thu 2026-10-29, hard 2 h cap (~18:00 start).
All commands run in the FOREGROUND through the small-test lane
`/Users/James/ai-sandbox/stevecam-ops/slot_m4.sh`. No Core Front job run.
Full suite NOT run (supervisor); targeted only: test_sp_k2c.py (new),
test_sp_k2b.py, test_sp_k2.py, test_zmap.py (both paths).
Changed file: verify/zkern/zcut.c ONLY (+ Python untouched, no existing
test edited; engine/ckern/stamp.c was read via `git show abb72b2:...` as
the brief's reference — the approach below is written from scratch).

## What was built (verify/zkern/zcut.c only; signatures unchanged)

(a) Squared-radius classification per cell: s = gx*gx + gy*gy compared
    against EACH radius the block uses — tool R+1e-9, engagement
    R+0.75*cell (when cutting), shank Rs+0.75*cell, holder Rh, plus the
    bull inner radius a = R - corner — with a RELATIVE margin MARG=1e-9
    on the squared radius: s < t*t*(1-1e-9) certainly inside;
    s > t*t*(1+1e-9) certainly outside (skipped for that mask); the
    boundary band computes d = hypot(gx,gy) and the exact old expression.
    Margin soundness: fl(gx*gx + fl(gy*gy)) and hypot(gx,gy)^2 differ
    from the exact gx^2+gy^2 by a few ulp (~1e-15 relative), so neither
    certainly-side can disagree with `hypot <= t`. Certainly-inside
    cells skip hypot unless the surface needs dd = hypot^2: flat never,
    bull only in the torus band a < d (a precomputed v0 = sz + (corner -
    sqrt(cc)) is bit-identical to the old chain at t = +0.0 since
    sqrt(fl(c*c)) == c), ball everywhere inside its mask (dd > 0 into
    the sqrt, as the brief anticipated). The engagement mask never needs
    hypot outside the band: emax/proj use only win, gx, gy.

(b) Per window row, conservative column bounds per mask
    (col_bounds(): all cells with s <= t_out obey
    |gx| <= sqrt(t_out - gy*gy), range widened +/-1 cell so rounding of
    the bound, of the linear grid model and of floor/ceil cannot drop a
    possibly-inside column). The cut loop uses the engagement bounds
    when cutting (superset of the tool mask) and the tool bounds for
    rapids; shank and holder scans get their own bounds. Row ends
    outside the bounds only take the +inf/NaN marker check, FUSED into
    the early-out row scan (which also became a branch-free
    NaN-ignoring max + separate NaN flag, same semantics as np.max).

(c) Cannot-cut skip — table below.

Exactness kept everywhere:
 - cells certainly OUTSIDE the tool mask: Python's cut = win - (+inf) is
   exactly +0.0 into removed and a dmax no-op for every finite/-inf win;
   only win = +inf or NaN matters (both poison removed AND dmax to NaN):
   one marker (!(win < INFINITY)) per skipped cell reproduces that.
 - removed stays BIT-identical to the K2B kernel: only provably +0.0
   summands are dropped; surviving ones keep row-major order.
 - fwd_bin division: exact power of two (FWD_BIN_MM = 0.25) -> multiply
   by 1/fwd_bin (provably bit-identical IEEE scaling, subnormals/inf/NaN
   included); otherwise the old division.
 - stock update scans only the column bounds; scratch bytes are written
   for every in-bounds cell each sample (no staleness); nocut cells are
   provable no-ops for np.minimum and never enter the update scratch.
 - shank/holder vtop scans: outside-mask cells contribute -inf to vsh/
   vH (np.where), invisible to the max even when stock/part is NaN, so
   they are skipped with no marker; NaN-inside-mask poisoning kept;
   worst-xy argmin-tie loops untouched (they need exact dd for every
   candidate).

## Cannot-cut skip analysis (w <= sz, non-NaN; "nocut")

Key fact: v >= sz for ALL tools under round-to-nearest —
sqrt(fl(R*R)) == R and sqrt(fl(c*c)) == c, so the ball offset
R - sqrt(max(RR-dd,0)) >= 0 and the bull offset corner -
sqrt(max(cc-t*t,0)) >= 0; flat is sz + 0.0. Hence cut = fl(w - v) <= 0
exactly. Per quantity:

| quantity            | skip? | why exact                                                    |
|---------------------|-------|--------------------------------------------------------------|
| removed             | YES   | clip0(cut) = +0.0; sum never -0.0, +0.0 add is a no-op (NaN   |
|                     |       | cells fail w <= sz and take the full path)                     |
| nrem, move_area     | YES   | cut <= 0 < eps(=1e-9)                                         |
| FWD hist            | YES   | only fed when cut > eps                                        |
| ZE2B vol            | YES   | needs finite cut > eps                                         |
| stock update        | YES   | w < v => np.minimum = w; w == v handled by its -0/+0 rule and |
|                     |       | equals w bit-for-bit (v >= sz >= w, v = +-0 only if w = +-0)   |
| collided (rapid)    | YES   | cut > eps false                                               |
| dmax / dmax_valid   | PART  | contributes cut <= 0: skipped ONLY once dmax >= 0 already (or |
|                     |       | NaN-poisoned); dmax is monotone so this is order-exact; while  |
|                     |       | dmax < 0 the cell computes exact v and cut (exercised by the   |
|                     |       | ball/bull edge-nocut cases where every cut < 0)                |
| ZE2B a, ext/dext    | NO    | read the PRE-MOVE snapshot `sub` (sub >= w always, stock only  |
|                     |       | falls), so w <= sz says nothing; v still computed there        |
| engagement emax/ew  | n/a   | uses win directly (win > tip cells are never w <= sz); the     |
|                     |       | mask classification (a) is the only change                     |
| shank vtop          | NO    | max(nm(stock, part)) independent of sz; only (a)/(b) apply     |
| holder vtop         | NO    | same                                                           |
| worst-xy candidates | NO    | cand needs exact dd = hypot for every cell (rare path anyway)  |

## Test runs (small-test lane, foreground; exit codes pasted)

Interpreters: tests /opt/homebrew/bin/python3 -m pytest (pytest 9.1.1,
numpy 2.4.3); scratch/driver /Applications/VibeCAD.app/Contents/
Resources/bin/python.

- 18:55 compile check (cc -O3 -ffp-contract=off -fno-fast-math
  -dynamiclib): exit=0.
- 19:00 scratch smoke (out/smoke_k2c.py: 300 random per-sample cases via
  test_sp_k2._one_sample + 4x60-move chains via test_sp_k2b._run_chain):
  per-sample fails 0/300, chain fails 0/240. exit=0
- 19:20 verify/test_sp_k2c.py (NEW, 3 tests: k2b-generator 2000 moves;
  304 constructed exact-radius moves; pinned boundary expectations):
  **3 passed exit=0** (7.2 s). Two test-harness fixes were needed
  (air_fraction float-sum tolerance for the engagement pin; stock is
  compared byte-wise, np.array_equal calls every NaN a difference).
  stats: {'moves': 304, 'cuts': 135, 'shank': 75, 'holder': 159,
  'engage': 304, 'rap': 3, 'ball_low': 25}; k2b-generator stats identical
  to SP-K2B's published run (shank 1303, holder 840, ties 80).
- 19:22 verify/test_sp_k2b.py + verify/test_sp_k2.py: **3 passed exit=0**
  (8.2 s). SP-K2B random-chain stats: {'moves': 2000, 'shank_hits': 1303,
  'holder_hits': 840, 'rapids': 60, 'tie_checked': 80, 'plunge': 170} —
  identical to the SP-K2B published run.
- 19:25 verify/test_zmap.py, C path:             132 passed / 1 failed,
  **exit=1**. verify/test_zmap.py, ZMAP_NO_CKERN=1: 132 passed / 1 failed,
  **exit=1**. The ONE failure is the pre-existing
  test_axial_real_core_front_rough_fails (FileNotFoundError: the real Core
  Front sample is not in this worktree; SP-K2B verified it fails
  identically on clean HEAD; Core Front jobs are banned this round).
  Identical on BOTH paths (10.3 s C vs 19.1 s Python wall time).

The new test's exact-radius suite covers, per radius (R+1e-9,
R+0.75*cell, Rs+0.75*cell, Rh, bull a, ball clamp R): cell centre at
r - 0.05, r - 0.001, r EXACT (+/-1 ulp of the coordinate subtraction,
i.e. inside the 1e-9 band -> exact hypot path), r + 0.001, r + 0.05;
axis-parallel AND 45-degree placements; flat/bull/ball; window on/off/
window-excluding-the-edge-cell; deep cut, 2e-6 skim, tip-exactly-at-
column-top, edge-nocut (every cut < 0 -> dmax < 0 -> nocut cells still
get exact v); cannot-cut boundary w = sz - 1e-9 / = sz / + 1e-9 /
+ 5e-7 / + 1e-6; +inf and NaN cells inside mask, on the engagement ring
and outside all masks; horizontal sweeps and grazing rapids across the
edges; plus the full SP-K2B 2,000-move generator (shank/holder hits and
exact argmin ties) re-run through the culled loop.

## Mutation runs (scratch edits to zcut.c, each reverted)

Each mutation: loader auto-rebuilds (newer zcut.c), verify/test_sp_k2c.py
run once, then revert by cp /tmp/zcut_k2c_good.c. "Entries" = mismatch
entries in the 2,000-move generator test; "moves" = mismatched constructed
moves in the exact-radius test; the third test pins Python-side truth.

| #  | mutation                                        | result                                        | exit |
|----|-------------------------------------------------|-----------------------------------------------|------|
| M1 | EPMARG (engagement mask margin) 1e-9 -> -1e-3   | 25 entries/2000 moves (air_fraction, engagement max_mm); 7/304 moves (Re+0.001 phantom engagement); pinned "no engage at Re+0.001" violated | 1 |
| M2 | holder column bounds one cell too narrow (drops the outermost possibly-inside column each side) | 92 entries/2000 moves (holder count/max_intrusion/worst_xy); 25/304 moves; pinned "holder hit at Rh-0.05" violated | 1 |
| M3 | cannot-cut skip using `w < sz + 0.5`            | 3984 entries/2000 moves (stock BYTES differ from the first move on); 72/304 moves ("C path cut nothing, python cut"); pinned "helper cell cut" violated | 1 |

After revert: `diff` vs the saved pre-mutation zcut.c = IDENTICAL, zero
"MUTATION" markers in the file; combined re-run test_sp_k2c + test_sp_k2b
+ test_sp_k2: **6 passed, exit=0** (15.5 s).

## Speed (TB programs, not CF; lane, foreground)

Part: out/tb_hf_0.1.npy = verify/heightfield.py of samples/test_block.step
at cell 0.1 (1000x800, x0=y0 grid -50..50 x -40..40, rebuilt this session
with freecadcmd, exit=0 — not a Core Front job). Programs regenerated for
this session (out/genk2c.py, serpentine rasters X -48..48, Y -38..38):
tb_rough.ngc (flat 12.686, levels Z 25.381 + 20.381, stepover 2.032,
engage_max 2.4384; 301,092 samples) and tb_finish.ngc (ball 5.958, one
level Z 20.381, stepover 1.0, engage_max 2.286; 299,060 samples). Driver
out/speed_k2c.py <c|py> <prog> [reps]; K2B = the pre-task zcut.c (ccb3868,
saved copy) measured on the SAME programs; best of 2 (C) / 1 (py).

| program    | SP-K2C           | SP-K2B (same progs) | Python            | C vs K2B | C vs py |
|------------|------------------|---------------------|-------------------|----------|---------|
| tb_rough   | 17.00 s 56.5 us/s| 24.08 s 80.0 us/s   | 37.38 s 124.2 us/s| 1.42x    | 2.20x   |
| tb_finish  |  8.07 s 27.0 us/s|  8.66 s 29.0 us/s   | 24.47 s  81.8 us/s| 1.07x    | 3.03x   |

exit=0 for every run. K2B's numbers reproduce its published table (77.5 /
28.4 us/samp on the near-identical programs), so the comparison is
apples-to-apples. Where the time went: the rough window (k=65 -> 131x131
= 17,161 cells) is ~76% inside the engagement circle, so the culling
removes ~4,200 corner cells/sample outright (marker check only) and ALL
~13,000 in-disk hypots for the flat tool (surface = sz + 0.0; bull saves
hypot inside a, ball cannot since its surface needs dd = hypot^2
everywhere — hence finish improves mostly via the corner cells, the
engagement ring, the branch-free early-out scan and the power-of-two
hist multiply, not via hypot removal). Remaining cost per sample is now
dominated by the two unavoidable full-window passes (early-out max,
marker rows-ends) plus per-cut-cell hist binning; a vectorized
inside-disk fast path (flat, no window mask) is the natural next step.

## Final verification (all after mutation revert)
- test_sp_k2c.py + test_sp_k2b.py + test_sp_k2.py: 6 passed, exit=0
- test_zmap.py C path: 132 passed / 1 pre-existing CF-file failure, exit=1
- test_zmap.py ZMAP_NO_CKERN=1: 132 passed / same 1 failure, exit=1

## Notes / constraints honoured
- No existing test edited; no Python changed; verify/ imports nothing
  from engine/ (stamp.c read from git history as reference only, own
  code written in verify/).
- No Core Front job; full pytest suite NOT run (supervisor's job) — only
  test_sp_k2c.py, test_sp_k2b.py, test_sp_k2.py and the at-risk
  test_zmap.py (both paths).
- Scratch kept out of deliverables: out/{smoke_k2c.py, dbg_*.py,
  genk2c.py, speed_k2c.py, tb_*.ngc, tb_hf_0.1.npy/json} (out/ untracked),
  /tmp/zcut_k2b_orig.c (K2B baseline copy), /tmp/zcut_k2c_good.c
  (mutation revert copy).
- zkern/libzcut.dylib is a build artifact (untracked, auto-rebuilt).

## Final `git diff --numstat`
26	4	opencode.json (pre-existing, not mine)
273	60	verify/zkern/zcut.c
?? verify/SPK2C_RESULTS.md
?? verify/test_sp_k2c.py
