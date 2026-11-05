#!/usr/bin/env python3
"""SP-K1 red/green tests for the compiled C twin of load_limit._stamp_move.

(a) test_sp_k1_sample_ts: the C sample-t helper equals
    np.linspace(0.0, 1.0, n + 1) bit for bit for n = 1..20000 and 50 random
    larger n.
(b) test_sp_k1_random_moves: 3,000 random moves (flat cr=0 and bull cr=0.127
    at R=6.35; R=3.175 flat; horizontal, ramped, vertical, zero-length and
    edge-clipped windows; crafted exact-boundary dd == R moves) on random
    stock padded with -inf: L np.array_equal (bit-wise, tobytes) after every
    move and (area, depth) exactly equal against _stamp_move_ref.
(c) test_sp_k1_limit_feeds_parity: limit_feeds on the synth_pocket flat
    rough with and without CAMBUDDY_NO_CKERN: identical output moves,
    identical stats dict, array_equal returned stock.
(d) test_sp_k1_mutations: scratch builds (temp dirs; the committed source is
    never touched) of R+1e-9 -> R-1e-9, skip-the-last-sample and
    area = count*(fine*fine) each FAIL the (b) scenario with a measured
    mismatch count; -ffp-contract=fast is built and reported for information.

_stamp_move_ref below is a verbatim copy of the pre-SP-K1 _stamp_move body.

Run (small-test lane, VibeCAD python):
    <lane> /Applications/VibeCAD.app/Contents/Resources/bin/python -c \
        "import sys; sys.path.insert(0,'.'); import engine.test_sp_k1 as t; t.<name>()"
"""
import ctypes
import hashlib
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")
sys.path.insert(0, os.path.join(ROOT, "verify"))

import numpy as np  # noqa: E402

from engine import ckern  # noqa: E402

REMOVE_EPS = 1e-9
FINE = 0.1
STEP_FILE = os.path.join(ROOT, "connector", "testdata", "synth_pocket.step")


def _stamp_move_ref(L, x0, y0, fine, R, cr, a0, kR, pad2, p, cur):
    """Verbatim copy of the pre-SP-K1 load_limit._stamp_move body."""
    dx, dy, dz = (cur[k] - p[k] for k in range(3))
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    n = 1 if length <= 0.0 else max(2, int(math.ceil(length / (fine / 4.0))))
    H, W = L.shape
    area = 0.0
    depth = 0.0
    for t in np.linspace(0.0, 1.0, n + 1):
        sx, sy, sz = p[0] + dx * t, p[1] + dy * t, p[2] + dz * t
        ci = int(math.floor((sx - x0) / fine)) + pad2
        cj = int(math.floor((sy - y0) / fine)) + pad2
        i0, i1 = max(0, ci - kR), min(W, ci + kR + 1)
        j0, j1 = max(0, cj - kR), min(H, cj + kR + 1)
        if i0 >= i1 or j0 >= j1:
            continue
        gx = x0 + ((np.arange(i0, i1) - pad2) + 0.5) * fine - sx
        gy = y0 + ((np.arange(j0, j1) - pad2) + 0.5) * fine - sy
        dd = np.hypot(gx[None, :], gy[:, None])
        m = dd <= R + 1e-9
        if cr:
            o = np.maximum(dd - a0, 0.0)
            surf = cr - np.sqrt(np.maximum(cr * cr - o * o, 0.0))
        else:
            surf = 0.0
        newv = np.where(m, sz + surf, np.inf)
        w = L[j0:j1, i0:i1]
        cut = w - newv
        nrem = int(np.count_nonzero(cut > REMOVE_EPS))
        if nrem:
            area += nrem * fine * fine
            dmax = float(np.max(cut))
            if np.isfinite(dmax) and dmax > depth:
                depth = dmax
        np.minimum(w, newv, out=w)
    return area, depth


# ---------------------------------------------------------------- (a)

def test_sp_k1_sample_ts():
    lib = ckern.get_lib()
    assert lib is not None, "engine/ckern/libstamp.dylib missing (run build.sh)"
    bad = 0
    for n in range(1, 20001):
        if not np.array_equal(ckern.sample_ts(n), np.linspace(0.0, 1.0, n + 1)):
            bad += 1
    rng = np.random.default_rng(1)
    big = [int(v) for v in rng.integers(20001, 500001, 50)]
    for n in big:
        if not np.array_equal(ckern.sample_ts(n), np.linspace(0.0, 1.0, n + 1)):
            bad += 1
    assert bad == 0, "sample_ts differs from np.linspace for %d n" % bad
    print("PASS sp_k1(a): sample_ts == np.linspace for n=1..20000 and "
          "50 random n up to %d" % max(big))


# ---------------------------------------------------------------- scenario

TOOLS = [(6.35, 0.0), (6.35, 0.127), (3.175, 0.0)]   # (R, cr)
H_IN, W_IN = 40, 45                                    # real (non-pad) cells
X0, Y0 = 12.345, 0.5


def _tool_cfg(ti):
    R, cr = TOOLS[ti]
    kR = int(math.ceil(R / FINE))
    return R, cr, R - cr, kR, kR + 1 + 2 * kR + 2      # a0, kR, pad2


def _scenario_stocks(seed=20261029):
    rng = np.random.default_rng(seed)
    stocks = {}
    for ti in range(len(TOOLS)):
        _, _, _, _, pad2 = _tool_cfg(ti)
        stocks[ti] = np.pad(rng.uniform(-5.0, 45.0, (H_IN, W_IN)),
                            pad2, constant_values=-np.inf)
    return stocks


def _pos(rng, R, mode):
    """Random tool-centre position; mode 0 interior, 1 edge-clipped window,
    2 fully outside the grid."""
    lo_x, hi_x = X0 - R, X0 + W_IN * FINE + R
    lo_y, hi_y = Y0 - R, Y0 + H_IN * FINE + R
    if mode == 0:
        x = rng.uniform(lo_x, hi_x)
        y = rng.uniform(lo_y, hi_y)
    elif mode == 1:
        x = float(rng.choice([lo_x, hi_x])) + rng.uniform(-0.05, 0.05)
        y = float(rng.choice([lo_y, hi_y])) + rng.uniform(-0.05, 0.05)
    else:
        sgn_x = float(rng.choice([-1.0, 1.0]))
        sgn_y = float(rng.choice([-1.0, 1.0]))
        x = lo_x + (sgn_x - 1.0) * (R + 1.0)
        y = lo_y + (sgn_y - 1.0) * (R + 1.0)
    return (x, y, float(rng.uniform(-6.0, 48.0)))


def _crafted(n_per=3):
    """Zero-length moves whose t=0 sample sits exactly at a cell centre in x
    and exactly R (float-exact, Sterbenz) below a cell centre in y, so
    dd == R holds bit-exactly: the inside test's +1e-9 decides these cells."""
    out = []
    for ti in range(len(TOOLS)):
        R = TOOLS[ti][0]
        qs = [27, 30, 33] if R > 4 else [12, 20, 30]
        for q in qs[:n_per]:
            for m in (10, 30):
                sx = X0 + (m + 0.5) * FINE
                sy = (Y0 + (q + 0.5) * FINE) - R
                out.append((ti, "craft", (sx, sy, 5.0), (sx, sy, 5.0), q, m))
    return out


def _scenario(n_moves=3000, seed=20261029):
    """Crafted exact-boundary moves FIRST (so their raised dd == R cells are
    still uncut when stamped), then the random moves."""
    rng = np.random.default_rng(seed)
    moves = list(_crafted())
    for k in range(n_moves):
        ti = k % len(TOOLS)
        kind = k % 5                     # 0 hz, 1 ramp, 2 vert, 3 zero, 4 hz
        mode = 0 if k % 11 else (1 if k % 3 else 2)
        p = _pos(rng, TOOLS[ti][0], mode)
        if kind == 3:
            cur = p
        elif kind == 2:
            cur = (p[0], p[1], p[2] + float(rng.choice([-1.0, 1.0]))
                   * rng.uniform(0.5, 8.0))
        elif kind == 1:
            cur = (p[0] + rng.uniform(-6, 6), p[1] + rng.uniform(-6, 6),
                   p[2] + float(rng.choice([-1.0, 1.0]))
                   * rng.uniform(0.5, 8.0))
        else:
            cur = (p[0] + rng.uniform(-6, 6), p[1] + rng.uniform(-6, 6), p[2])
        moves.append((ti, "rand", p, cur, None, None))
    return moves


def _prepare_crafted(stocks, moves):
    """Raise the crafted boundary cells so they cut, and count how many
    t=0 window cells hit dd == R exactly (the +1e-9 margin's witnesses)."""
    nbnd = 0
    for (ti, kind, p, cur, q, m) in moves:
        if kind != "craft":
            continue
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        stocks[ti][pad2 + q, pad2 + m] = 44.0
        ci = int(math.floor((p[0] - X0) / FINE)) + pad2
        cj = int(math.floor((p[1] - Y0) / FINE)) + pad2
        i0, i1 = max(0, ci - kR), min(stocks[ti].shape[1], ci + kR + 1)
        j0, j1 = max(0, cj - kR), min(stocks[ti].shape[0], cj + kR + 1)
        gxx = X0 + ((np.arange(i0, i1) - pad2) + 0.5) * FINE - p[0]
        gyy = Y0 + ((np.arange(j0, j1) - pad2) + 0.5) * FINE - p[1]
        dd = np.hypot(gxx[None, :], gyy[:, None])
        nbnd += int(np.count_nonzero(dd == R))
    return nbnd


_SCENARIO = None
_REF = None          # list of (area, depth, md5(L_after)) per move
_NBOUND = None


def _ref_records(moves, stocks):
    """Run the reference once, evolving per-tool stock; cache records."""
    global _REF
    state = {ti: stocks[ti].copy() for ti in stocks}
    recs = []
    for (ti, kind, p, cur, q, m) in moves:
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        a, d = _stamp_move_ref(state[ti], X0, Y0, FINE, R, cr, a0, kR,
                               pad2, p, cur)
        recs.append((a, d, hashlib.md5(state[ti].tobytes()).hexdigest()))
    _REF = recs
    return recs


def _run_with_lib(lib, moves, stocks, stamp):
    """Run the scenario with a C twin (ctypes bound to `lib`); compare each
    move against the cached ref records. Returns the mismatch count."""
    assert _REF is not None, "run _ref_records first"
    state = {ti: stocks[ti].copy() for ti in stocks}
    area = ctypes.c_double(0.0)
    depth = ctypes.c_double(0.0)
    bad = 0
    for k, (ti, kind, p, cur, q, m) in enumerate(moves):
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        pp = (ctypes.c_double * 3)(p[0], p[1], p[2])
        cc = (ctypes.c_double * 3)(cur[0], cur[1], cur[2])
        L = state[ti]
        rc = stamp(L.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                   L.shape[0], L.shape[1], X0, Y0, FINE, R, cr, a0, kR,
                   pad2, pp, cc, REMOVE_EPS, ctypes.byref(area),
                   ctypes.byref(depth))
        assert rc == 0, "stamp_move rc=%d" % rc
        a_r, d_r, h_r = _REF[k]
        if (a_r, d_r) != (area.value, depth.value) or \
                hashlib.md5(L.tobytes()).hexdigest() != h_r:
            bad += 1
    return bad


# ---------------------------------------------------------------- (b)

def test_sp_k1_random_moves():
    global _SCENARIO, _NBOUND
    lib = ckern.get_lib()
    assert lib is not None, "engine/ckern/libstamp.dylib missing (run build.sh)"
    moves = _scenario()
    stocks = _scenario_stocks()
    _NBOUND = _prepare_crafted(stocks, moves)
    assert _NBOUND > 0, "no exact dd==R boundary cells were built"
    recs = _ref_records(moves, stocks)
    _SCENARIO = (moves, stocks)
    state = {ti: stocks[ti].copy() for ti in stocks}
    bad = 0
    for (ti, kind, p, cur, q, m) in moves:
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        A = state[ti].copy()
        B = state[ti]
        a_c, d_c = ckern.stamp_move(A, X0, Y0, FINE, R, cr, a0, kR, pad2,
                                    p, cur, REMOVE_EPS)
        a_r, d_r = _stamp_move_ref(B, X0, Y0, FINE, R, cr, a0, kR, pad2,
                                   p, cur)
        if not (np.array_equal(A, B) and A.tobytes() == B.tobytes()
                and (a_c, d_c) == (a_r, d_r)):
            bad += 1
        state[ti] = A
    assert _NBOUND is not None
    assert bad == 0, "%d of %d moves differ from _stamp_move_ref" % (
        bad, len(moves))
    print("PASS sp_k1(b): %d moves bit-identical vs _stamp_move_ref "
          "(%d exact dd==R boundary cells)" % (len(moves), _NBOUND))


# ---------------------------------------------------------------- (c)

STOCK = (-31.0, 31.0, -31.0, 31.0, -1.0, 12.4)
CUT_FEED = 3429.0


def test_sp_k1_limit_feeds_parity():
    from engine import load_limit, model
    from engine import rough as roughmod
    assert load_limit._CKERN is not None, "ckern lib not loaded"
    stl = model.step_to_stl(STEP_FILE)
    surf = model.load_surf(stl)
    moves, _ = roughmod.rough(surf, STOCK, 3.0, 3.0, leave=0.381,
                              stepdown=4.0, stepover=0.15,
                              cut_feed=CUT_FEED, ramp_feed=1270.0,
                              wl_sampling=0.1, tolerance=0.05,
                              keep_tool_down=3.0, stl_path=stl, workers=4,
                              axial_leave=0.381, final_zmin=3.381,
                              corner_r=0.0, stock_cell=0.5, stepup=1.905,
                              min_rest=0.5, min_level_area=20.0,
                              rapid_margin=1.0)
    assert len(moves) > 100, "synth rough produced too few moves"
    os.environ.pop("CAMBUDDY_NO_CKERN", None)
    out_c, stats_c, stock_c = load_limit.limit_feeds(
        moves, 6.0, 0.0, STOCK, STOCK[5], CUT_FEED, return_stock=True)
    os.environ["CAMBUDDY_NO_CKERN"] = "1"
    try:
        out_p, stats_p, stock_p = load_limit.limit_feeds(
            moves, 6.0, 0.0, STOCK, STOCK[5], CUT_FEED, return_stock=True)
    finally:
        os.environ.pop("CAMBUDDY_NO_CKERN", None)
    assert out_c == out_p, "output moves differ"
    assert stats_c == stats_p, "stats differ: %s vs %s" % (stats_c, stats_p)
    assert np.array_equal(stock_c[0], stock_p[0]), "returned stock differs"
    assert stock_c[1:] == stock_p[1:], "stock origin/cell differ"
    print("PASS sp_k1(c): limit_feeds C vs Python identical (%d moves, "
          "stats %s)" % (len(out_c), stats_c))


# ---------------------------------------------------------------- (d)

_SRC = os.path.join(HERE, "ckern", "stamp.c")
MUTATIONS = [
    ("R+1e-9 -> R-1e-9", "Rlim = R + 1e-9;", "Rlim = R - 1e-9;"),
    ("skip the last sample", "for (s = 0; s <= n; ++s)",
     "for (s = 0; s < n; ++s)"),
    ("area = count*(fine*fine)", "area += ((double)count * fine) * fine;",
     "area += (double)count * (fine * fine);"),
]


def _scratch_build(tag, old=None, new=None, flags=None):
    """Compile a scratch (optionally mutated) dylib in a temp dir; the
    committed source is never modified."""
    src = open(_SRC).read()
    if old is not None:
        assert src.count(old) == 1, "mutation anchor not unique: %r" % old
        src = src.replace(old, new)
    td = tempfile.mkdtemp(prefix="spk1_%s_" % tag)
    cpath = os.path.join(td, "stamp.c")
    dylib = os.path.join(td, "lib.so")
    with open(cpath, "w") as fh:
        fh.write(src)
    cmd = (flags or ["-O3", "-ffp-contract=off", "-fno-fast-math"])
    r = subprocess.run(["clang"] + cmd + ["-shared", "-o", dylib, cpath],
                       capture_output=True, text=True)
    assert r.returncode == 0, "scratch build failed: %s" % r.stderr[-500:]
    lib = ctypes.CDLL(dylib)
    d, l = ctypes.c_double, ctypes.c_long
    lib.stamp_move.argtypes = [ctypes.POINTER(d), l, l, d, d, d, d, d, d,
                               l, l, ctypes.POINTER(d), ctypes.POINTER(d),
                               d, ctypes.POINTER(d), ctypes.POINTER(d)]
    lib.stamp_move.restype = ctypes.c_int
    return lib, td


def test_sp_k1_mutations():
    if _SCENARIO is None:
        test_sp_k1_random_moves()
    moves, stocks = _SCENARIO
    counts = {}
    tmps = []
    try:
        for (name, old, new) in MUTATIONS:
            lib, td = _scratch_build(name.split()[0], old, new)
            tmps.append(td)
            bad = _run_with_lib(lib, moves, stocks, lib.stamp_move)
            counts[name] = bad
            assert bad > 0, "mutation %r was NOT caught (0 mismatches)" % name
        lib, td = _scratch_build("fast", flags=["-O3", "-ffp-contract=fast",
                                                "-fno-fast-math"])
        tmps.append(td)
        counts["-ffp-contract=fast (info)"] = _run_with_lib(
            lib, moves, stocks, lib.stamp_move)
    finally:
        for td in tmps:
            shutil.rmtree(td, ignore_errors=True)
    print("PASS sp_k1(d): mutation mismatch counts (of %d moves):"
          % len(moves))
    for k, v in counts.items():
        print("    %-28s %d" % (k, v))
    for name in counts:
        if "info" in name:
            continue
        assert counts[name] > 0


if __name__ == "__main__":
    test_sp_k1_sample_ts()
    test_sp_k1_random_moves()
    test_sp_k1_limit_feeds_parity()
    test_sp_k1_mutations()
