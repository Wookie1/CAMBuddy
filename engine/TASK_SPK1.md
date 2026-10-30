TASK SP-K1: compiled C kernel for load_limit._stamp_move (speed only, IDENTICAL output).
Context: _stamp_move is 33% of the CF rough (375,610 Python calls, ~600 s). It stamps one G1 move into the 0.1 mm live stock, sample by sample, and measures the removed (area, depth). This round moves exactly that function into C, loaded with ctypes. clang works on this Mac. Engine Python = VibeCAD 3.11 with numpy 1.26.4. Do not modify VibeCAD.
Do:
(1) engine/ckern/stamp.c: one exported function, e.g. int stamp_move(double *L, long H, long W, double x0, double y0, double fine, double R, double cr, double a0, long kR, long pad2, const double *p, const double *cur, double remove_eps, double *area, double *depth). It must reproduce _stamp_move bit for bit, with the same operations in the same order:
 - length = sqrt((dx*dx + dy*dy) + dz*dz); n exactly as in Python.
 - Sample t values identical to np.linspace(0.0, 1.0, n + 1) in numpy 1.26: step = 1.0/n, t_i = (double)i*step + 0.0, last = 1.0. Verify this by test; don't assume.
 - sx = p0 + dx*t (likewise y, z).
 - ci = floor((sx - x0)/fine) + pad2, and the same clipped window.
 - gx = (x0 + ((double)(i - pad2) + 0.5)*fine) - sx (likewise gy).
 - dd = hypot(gx, gy); inside iff dd <= R + 1e-9 (that sum computed once).
 - If cr != 0: o = fmax(dd - a0, 0.0) and surf = cr - sqrt(fmax(cr*cr - o*o, 0.0)); else surf = 0.0. newv = inside ? sz + surf : +inf.
 - cut = w - newv. Count cells with cut > remove_eps. dmax = max of cut over the WHOLE window (as np.max does). If the count > 0: area += (count*fine)*fine, and depth = dmax when isfinite(dmax) and dmax > depth. Then w = fmin(w, newv) in place.
(2) engine/ckern/build.sh: clang -O3 -ffp-contract=off -fno-fast-math -shared -o engine/ckern/libstamp.dylib engine/ckern/stamp.c. Add the .dylib to .gitignore; commit the source and the script only. engine/ckern/__init__.py loads it with ctypes and returns None if it's missing. L must be C-contiguous float64 (assert it).
(3) In load_limit._stamp_move: use the C function when the library loaded and env STEVECAM_NO_CKERN is unset; else run the existing Python body unchanged. Print once which path is used.
Do NOT change any other function, constant or test. Do not delete or rewrite any existing test; add new tests only.
Tests (new engine/test_sp_k1.py, which keeps a verbatim copy of the old _stamp_move as _stamp_move_ref):
 (a) The C sample-t helper (export one) equals np.linspace exactly for n = 1..20000 and 50 random larger n.
 (b) 3,000 random moves (flat cr=0 and bull cr=0.127 at R=6.35; R=3.175 flat; horizontal, ramped, vertical, zero-length, and windows clipped at the grid edges) on a random stock with -inf padding: L arrays np.array_equal after every move, and (area, depth) == exactly, against _stamp_move_ref.
 (c) limit_feeds on the synth_pocket flat rough with and without STEVECAM_NO_CKERN: output moves identical, stats dict identical, returned stock array_equal.
 (d) Mutations (scratch builds, then revert): R+1e-9 -> R-1e-9; skip the last sample; area summed as count*(fine*fine). Each must make (b) or (c) fail by a measured mismatch count. Report the counts. Also report, for information, whether -ffp-contract=fast is caught.
Results go in engine/SPK1_RESULTS.md, written early and appended after each run. Targeted tests only; the supervisor runs the full suites and all Core Front jobs. FOREGROUND RULE: run every test in the foreground. Continue from your plan, and don't stop before the tests exist and have run. Hard 2 h cap.
