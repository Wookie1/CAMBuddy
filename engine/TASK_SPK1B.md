TASK SP-K1B: make the C stamping kernel fast (still IDENTICAL output), and build it automatically.
Context: SP-K1 (d79a97d) moved load_limit._stamp_move to C and is bit-identical, but only ~2.5x faster. Each sample evaluates hypot on the whole (2kR+1)^2 window (129x129 at R=6.35, fine=0.1), and every move pays a ctypes call plus the Python wrapper.
Do:
(1) Speed, all inside stamp.c plus its single caller:
 (a) Per cell, compute s = gx*gx + gy*gy first. With T = R + 1e-9: if s > T*T*(1 + 1e-9), the cell is outside (newv = +inf, so it can't cut or change w); skip it. For a flat tool (cr == 0), if s < T*T*(1 - 1e-9) the cell is inside, and newv = sz + 0.0 needs no dd. For a bull tool, if s < a0*a0*(1 - 1e-9), then o = 0 exactly, so use surf0 = cr - sqrt(fmax(cr*cr - 0.0*0.0, 0.0)), computed once. Every other cell computes dd = hypot(gx, gy) and the exact old expressions.
 (b) Per window row, skip the columns that are certainly outside the circle, using the same 1e-9 margin.
 (c) Early-out per sample: if no cell in the clipped window has w > sz, the sample cannot cut or change L (newv >= sz everywhere), so skip it. Only do this if it's exactly equivalent; if you're unsure about the dmax semantics, leave it out.
 (d) Add a batch entry point that stamps ALL of a move list's G1 moves in one C call, returning per-move (area, depth) arrays. Use it from limit_feeds, so the Python per-move work does only the bookkeeping it does now (helix pitch, recs, windows) on those arrays. Program order and the live-stock semantics must stay exactly as they are now.
(2) Auto-build: engine/ckern/__init__.py compiles libstamp.dylib with the same flags as build.sh when it's missing or older than stamp.c (clang found via xcrun or PATH). The build goes to a temp file in engine/ckern/, then an atomic rename. On any failure it falls back to Python. The rough stats JSON gets "stamp_kernel": "c" or "python", and the CLI prints it.
Do NOT change any other behaviour, constant or test. Do not delete or rewrite any existing test (including test_sp_k1.py); add new tests only.
Tests (new engine/test_sp_k1b.py):
 - Rerun SP-K1's (b) generator with 10,000 moves, including bull cr = 0.127 and cr = R (ball-like), R = 3.175 and 6.35, cells exactly at distance T and at a0 (construct them), windows clipped at the edges, -inf and +inf stock cells. L must be tobytes-identical after every move, and (area, depth) ==, against _stamp_move_ref. The batch entry point must equal per-move calls.
 - limit_feeds on synth_pocket: C batch vs STEVECAM_NO_CKERN, identical moves, stats and stock.
 - Mutations (scratch, then revert): margin 1e-9 -> -1e-3 in (a); early-out testing w >= sz instead of w > sz (if implemented); batch skipping the last move. Each must fail by a measured mismatch count; report them.
 - Speed: report per-move time, C batch vs SP-K1 C vs Python, on the synth scene and on 20,000 moves sampled from a TB rough (not CF).
Results go in engine/SPK1B_RESULTS.md, written early and appended. Targeted tests only. FOREGROUND RULE. Continue from your plan, and don't stop before the tests exist and have run. Hard 2 h cap. Running any Core Front job voids the round.
