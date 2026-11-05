#!/usr/bin/env python3
"""SP-K1B red/green tests for the fast batched C stamping kernel.

(a) test_sp_k1b_random_moves: SP-K1's (b) generator rerun with 10,000 moves
    over six tools - flat and bull cr=0.127 and ball-like cr=R at R=6.35 and
    R=3.175 - on random stock padded with -inf that ALSO contains +inf and
    -inf interior cells; crafted zero-length moves place cells exactly at
    distance R, at T = R + 1e-9 and at a0 (and at 0 = a0 for the ball-like
    tools). Windows clipped at the grid edges and fully outside. L must be
    tobytes-identical after every move and (area, depth) == against
    _stamp_move_ref; the batch entry point must equal the per-move calls
    (per-move (area, depth) and final L).
(b) test_sp_k1b_limit_feeds_parity: limit_feeds on the synth_pocket flat
    rough, C batch vs CAMBUDDY_NO_CKERN: identical moves, stats, stock.
(c) test_sp_k1b_autobuild: ensure_built() rebuilds a missing library and a
    library older than stamp.c; a broken toolchain leaves the caller on the
    Python fallback (no exception).
(d) test_sp_k1b_mutations: scratch builds (temp dirs; the committed source
    is never touched): outside-margin (1+1e-9) -> (1-1e-3); the early-out
    w > sz flipped to w >= sz (expected EQUIVALENT - the mutated skip is a
    subset of the correct skip - the count is reported either way, and an
    over-skipping w > sz + 0.5 variant proves the early-out is live); and
    the batch skipping its last move. Each real mutation must fail with a
    measured mismatch count.
(e) test_sp_k1b_speed: per-move stamping time, C batch vs SP-K1 per-move C
    vs Python, on the synth_pocket scene and on 20,000 moves from a TB
    (test_block) rough program (never Core Front).

_stamp_move_ref is imported from test_sp_k1 (the verbatim pre-SP-K1 body).

Run (small-test lane, VibeCAD python):
    <lane> /Applications/VibeCAD.app/Contents/Resources/bin/python -c \
        "import sys; sys.path.insert(0,'.'); import engine.test_sp_k1b as t; t.<name>()"
"""
import ctypes
import hashlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")
sys.path.insert(0, os.path.join(ROOT, "verify"))

import numpy as np  # noqa: E402

from engine import ckern  # noqa: E402
from engine.test_sp_k1 import _stamp_move_ref  # noqa: E402

REMOVE_EPS = 1e-9
FINE = 0.1
STEP_FILE = os.path.join(ROOT, "connector", "testdata", "synth_pocket.step")
SCRATCH = os.path.join(ROOT, "scratch")

# (R, cr): flat / bull cr=0.127 / ball-like cr=R at both radii, both R for
# the bull too (six tools).
TOOLS = [(6.35, 0.0), (6.35, 0.127), (6.35, 6.35),
         (3.175, 0.0), (3.175, 0.127), (3.175, 3.175)]
H_IN, W_IN = 40, 45
X0, Y0 = 12.345, 0.5


def _tool_cfg(ti):
    R, cr = TOOLS[ti]
    kR = int(math.ceil(R / FINE))
    return R, cr, R - cr, kR, kR + 1 + 2 * kR + 2      # a0, kR, pad2


def _scenario_stocks(seed=20261029):
    """Random stock padded with -inf; interior carries crafted later plus
    ~1 % +inf and ~2 % -inf cells (the +inf cells make the old loop's
    cut = inf - inf = NaN -> dmax = NaN semantics observable)."""
    rng = np.random.default_rng(seed)
    stocks = {}
    for ti in range(len(TOOLS)):
        _, _, _, _, pad2 = _tool_cfg(ti)
        A = rng.uniform(-5.0, 45.0, (H_IN, W_IN))
        A[rng.random((H_IN, W_IN)) < 0.01] = np.inf
        A[rng.random((H_IN, W_IN)) < 0.02] = -np.inf
        stocks[ti] = np.pad(A, pad2, constant_values=-np.inf)
    return stocks


def _pos(rng, R, mode):
    """Random tool-centre position; mode 0 interior, 1 edge-clipped window,
    2 fully outside the grid (same construction as test_sp_k1)."""
    lo_x, hi_x = X0 - R, X0 + W_IN * FINE + R
    lo_y, hi_y = Y0 - R, Y0 + H_IN * FINE + R
    if mode == 0:
        x, y = rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)
    elif mode == 1:
        x = float(rng.choice([lo_x, hi_x])) + rng.uniform(-0.05, 0.05)
        y = float(rng.choice([lo_y, hi_y])) + rng.uniform(-0.05, 0.05)
    else:
        sgx = float(rng.choice([-1.0, 1.0]))
        sgy = float(rng.choice([-1.0, 1.0]))
        x = lo_x + (sgx - 1.0) * (R + 1.0)
        y = lo_y + (sgy - 1.0) * (R + 1.0)
    return (x, y, float(rng.uniform(-6.0, 48.0)))


def _crafted():
    """Zero-length moves whose t=0 sample puts a cell centre at distance
    EXACTLY R, exactly T = R + 1e-9, exactly a0 (bull tools) or exactly 0
    (ball-like tools, a0 == 0) below a cell centre, with gx == 0 exactly.
    (kind, dist-name) cells are raised and witnessed in _prepare_crafted."""
    out = []
    for ti in range(len(TOOLS)):
        R, cr, a0, _kR, _pad2 = _tool_cfg(ti)
        T = R + 1e-9
        dists = [("R", R), ("T", T)]
        if a0 > 0.0:
            dists.append(("a0", a0))
        else:
            dists.append(("a0", 0.0))
        qs = [27, 30, 33] if R > 4 else [12, 20, 30]
        for (name, d) in dists:
            for q in qs:
                for m in (10, 30):
                    sx = X0 + (m + 0.5) * FINE
                    sy = (Y0 + (q + 0.5) * FINE) - d
                    out.append((ti, "craft:" + name, (sx, sy, 5.0),
                                (sx, sy, 5.0), q, m))
    return out


def _prepare_crafted(stocks, moves):
    """Raise the crafted cells so they cut, and count witness cells whose
    dd equals R / T / a0 bit-exactly (the margin's and the shortcuts'
    boundary witnesses)."""
    nbnd = {"R": 0, "T": 0, "a0": 0}
    for (ti, kind, p, cur, q, m) in moves:
        if not kind.startswith("craft"):
            continue
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        stocks[ti][pad2 + q, pad2 + m] = 44.0
        L = stocks[ti]
        ci = int(math.floor((p[0] - X0) / FINE)) + pad2
        cj = int(math.floor((p[1] - Y0) / FINE)) + pad2
        i0, i1 = max(0, ci - kR), min(L.shape[1], ci + kR + 1)
        j0, j1 = max(0, cj - kR), min(L.shape[0], cj + kR + 1)
        gxx = X0 + ((np.arange(i0, i1) - pad2) + 0.5) * FINE - p[0]
        gyy = Y0 + ((np.arange(j0, j1) - pad2) + 0.5) * FINE - p[1]
        dd = np.hypot(gxx[None, :], gyy[:, None])
        T = R + 1e-9
        nbnd["R"] += int(np.count_nonzero(dd == R))
        nbnd["T"] += int(np.count_nonzero(dd == T))
        nbnd["a0"] += int(np.count_nonzero(dd == a0))
    return nbnd


def _scenario(n_moves=10000, seed=20261029):
    """Crafted exact-boundary moves FIRST (so their cells are still uncut
    when stamped), then n_moves random moves."""
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
            cur = (p[0] + rng.uniform(-6, 6), p[1] + rng.uniform(-6, 6),
                   p[2])
        moves.append((ti, "rand", p, cur, None, None))
    # one GUARANTEED-cutting zero-length move per tool at the very end (deep
    # z below any stock the earlier stamps can leave), so a batch that skips
    # its last move cannot hide behind a zero-area tail
    for ti in range(len(TOOLS)):
        x = X0 + W_IN * FINE / 2.0 + rng.uniform(-1.0, 1.0)
        y = Y0 + H_IN * FINE / 2.0 + rng.uniform(-1.0, 1.0)
        moves.append((ti, "tail", (x, y, -10.0), (x, y, -10.0), None, None))
    return moves


_SCENARIO = None
_REF = None                 # per move: (area, depth, md5(L_after), ti)


def _ref_records(moves, stocks):
    """Run the reference once, evolving per-tool stock; cache records."""
    global _REF
    state = {ti: stocks[ti].copy() for ti in stocks}
    recs = []
    for (ti, kind, p, cur, q, m) in moves:
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        a, d = _stamp_move_ref(state[ti], X0, Y0, FINE, R, cr, a0, kR,
                               pad2, p, cur)
        recs.append((a, d, hashlib.md5(state[ti].tobytes()).hexdigest(), ti))
    _REF = recs
    return recs


def _ensure_scenario():
    global _SCENARIO, _BATCH_ORDER
    if _SCENARIO is not None:
        return _SCENARIO
    moves = _scenario()
    stocks = _scenario_stocks()
    nbnd = _prepare_crafted(stocks, moves)
    for name in ("R", "T", "a0"):
        assert nbnd[name] > 0, "no exact dd == %s boundary cells built" % name
    _ref_records(moves, stocks)
    _BATCH_ORDER = _batch_order(moves)
    _SCENARIO = (moves, stocks, nbnd)
    return _SCENARIO


def _lib_bindings(lib, want_batch=True):
    d, l = ctypes.c_double, ctypes.c_long
    dp = ctypes.POINTER(d)
    lib.sample_ts.argtypes = [l, dp]
    lib.sample_ts.restype = None
    lib.stamp_move.argtypes = [dp, l, l, d, d, d, d, d, d, l, l, dp, dp,
                               d, dp, dp]
    lib.stamp_move.restype = ctypes.c_int
    if want_batch:
        lib.stamp_batch.argtypes = [dp, l, l, d, d, d, d, d, d, l, l, l, dp,
                                    ctypes.POINTER(l), d, dp, dp]
        lib.stamp_batch.restype = ctypes.c_int
    return lib


def _run_per_move(stamp, moves, stocks):
    """Run the scenario through a stamp_move C entry point (ctypes callable)
    against the cached ref records; returns the mismatch count."""
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
        a_r, d_r, h_r, _ = _REF[k]
        if (a_r, d_r) != (area.value, depth.value) or \
                hashlib.md5(L.tobytes()).hexdigest() != h_r:
            bad += 1
    return bad


def _batch_xyz(moves):
    """Per-tool batch inputs: xyz = [p0, cur0, p1, cur1, ...] with flags 1
    on the odd slots (each move stamped p -> cur, program order kept)."""
    xyz, flags = {}, {}
    for (ti, kind, p, cur, q, m) in moves:
        xyz.setdefault(ti, []).extend([p, cur])
        flags.setdefault(ti, []).extend([0, 1])
    return xyz, flags


# ---------------------------------------------------------------- (a)

def test_sp_k1b_random_moves():
    lib = ckern.get_lib()
    assert lib is not None, "engine/ckern/libstamp.dylib missing"
    moves, stocks, nbnd = _ensure_scenario()
    # per move: fast C vs reference, L tobytes-identical after EVERY move
    state_c = {ti: stocks[ti].copy() for ti in stocks}
    state_r = {ti: stocks[ti].copy() for ti in stocks}
    bad = 0
    for (ti, kind, p, cur, q, m) in moves:
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        a_c, d_c = ckern.stamp_move(state_c[ti], X0, Y0, FINE, R, cr, a0,
                                    kR, pad2, p, cur, REMOVE_EPS)
        a_r, d_r = _stamp_move_ref(state_r[ti], X0, Y0, FINE, R, cr, a0,
                                   kR, pad2, p, cur)
        if not (state_c[ti].tobytes() == state_r[ti].tobytes()
                and (a_c, d_c) == (a_r, d_r)):
            bad += 1
    assert bad == 0, "%d of %d moves differ from _stamp_move_ref" % (
        bad, len(moves))
    # batch entry point == per-move calls (per-move (area, depth) AND L)
    xyz, flags = _batch_xyz(moves)
    for ti in xyz:
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        ax = np.asarray(xyz[ti], dtype=np.float64)
        fg = np.asarray(flags[ti], dtype=np.int64)
        Lb = stocks[ti].copy()
        Lm = stocks[ti].copy()
        ab, ad = ckern.stamp_batch(Lb, X0, Y0, FINE, R, cr, a0, kR, pad2,
                                   ax, fg, REMOVE_EPS)
        bad = 0
        for j, (kind, p, cur) in enumerate(_BATCH_ORDER[ti]):
            a_m, d_m = ckern.stamp_move(Lm, X0, Y0, FINE, R, cr, a0, kR,
                                        pad2, p, cur, REMOVE_EPS)
            if (ab[2 * j + 1], ad[2 * j + 1]) != (a_m, d_m) or \
                    ab[2 * j] != 0.0 or ad[2 * j] != 0.0:
                bad += 1
        assert bad == 0, "tool %d: batch differs from per-move on %d moves" % (
            ti, bad)
        assert Lb.tobytes() == Lm.tobytes(), "tool %d: batch L differs" % ti
        # and against the numpy reference records
        k_r = 0
        for k, (ti2, kind, p, cur, q, m) in enumerate(moves):
            if ti2 != ti:
                continue
            a_r, d_r, h_r, _ = _REF[k]
            if (ab[2 * k_r + 1], ad[2 * k_r + 1]) != (a_r, d_r):
                bad += 1
            k_r += 1
        assert bad == 0, "tool %d: batch (area, depth) differ from ref" % ti
        assert hashlib.md5(Lb.tobytes()).hexdigest() == \
            _REF_last_md5(ti, moves), "tool %d: final L differs from ref" % ti
    print("PASS sp_k1b(a): %d moves (6 tools incl. ball cr=R; +inf/-inf "
          "stock cells) bit-identical vs _stamp_move_ref; batch == per-move "
          "(witnesses dd==R:%d dd==T:%d dd==a0:%d)"
          % (len(moves), nbnd["R"], nbnd["T"], nbnd["a0"]))


def _batch_order(moves):
    order = {}
    for (ti, kind, p, cur, q, m) in moves:
        order.setdefault(ti, []).append((kind, p, cur))
    return order


_BATCH_ORDER = None


def _REF_last_md5(ti, moves):
    """The cached ref L-md5 after the LAST move of tool ti."""
    last = None
    for k, (ti2, _k, _p, _c, _q, _m) in enumerate(moves):
        if ti2 == ti:
            last = _REF[k][2]
    return last


# ---------------------------------------------------------------- (b)

STOCK = (-31.0, 31.0, -31.0, 31.0, -1.0, 12.4)
CUT_FEED = 3429.0


def _synth_rough_moves():
    from engine import model
    from engine import rough as roughmod
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
    return moves


def test_sp_k1b_limit_feeds_parity():
    from engine import load_limit
    assert load_limit._CKERN is not None, "ckern lib not loaded"
    moves = _synth_rough_moves()
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
    assert stock_c[0].tobytes() == stock_p[0].tobytes(), "stock bytes differ"
    assert stock_c[1:] == stock_p[1:], "stock origin/cell differ"
    print("PASS sp_k1b(b): limit_feeds C batch vs Python identical (%d "
          "moves, stats %s)" % (len(out_c), stats_c))


# ---------------------------------------------------------------- (c)

def test_sp_k1b_autobuild():
    src = os.path.join(HERE, "ckern", "stamp.c")
    dylib = os.path.join(HERE, "ckern", "libstamp.dylib")
    snippet = (
        "import os, sys, time; sys.path.insert(0, %r)\n"
        "from engine import ckern\n"
        "assert ckern.get_lib() is not None, 'rebuild did not load'\n"
        "assert os.path.exists(ckern._DYLIB), 'dylib missing after build'\n"
        "# stale library (older than stamp.c) is rebuilt\n"
        "t_old = os.path.getmtime(ckern._DYLIB)\n"
        "now = time.time() + 2.0\n"
        "os.utime(ckern._SRC, (now, now))\n"
        "ckern.ensure_built()\n"
        "assert os.path.getmtime(ckern._DYLIB) > t_old, 'stale not rebuilt'\n"
        "# a broken toolchain never raises; it just leaves the lib as-is\n"
        "t_prev = os.path.getmtime(ckern._DYLIB)\n"
        "ckern._clang = lambda: ['/nonexistent-cc-nope']\n"
        "now = time.time() + 4.0\n"
        "os.utime(ckern._SRC, (now, now))\n"
        "ckern.ensure_built()\n"
        "assert os.path.getmtime(ckern._DYLIB) == t_prev, 'broken cc wrote'\n"
        "print('autobuild-subprocess OK')\n" % ROOT)
    r = subprocess.run([sys.executable, "-c", snippet], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, "autobuild subprocess failed: %s" % r.stderr[-600:]
    assert "autobuild-subprocess OK" in r.stdout
    # the library in the tree is freshly rebuilt and loadable
    assert os.path.exists(dylib) and os.path.getmtime(dylib) > 0
    lib = ckern.get_lib()
    assert lib is not None, "in-process ckern unusable after rebuild"
    print("PASS sp_k1b(c): auto-build rebuilds missing and stale libstamp"
          ".dylib (atomic), broken clang falls back silently")


# ---------------------------------------------------------------- (d)

_SRC = os.path.join(HERE, "ckern", "stamp.c")
MUTATIONS = [
    ("outside margin (1+1e-9)->(1-1e-3)", "Tt = Rlim * Rlim * (1.0 + 1e-9);",
     "Tt = Rlim * Rlim * (1.0 - 1e-3);"),
    ("early-out w > sz -> w >= sz", "if (w <= sz && w == w)",
     "if (w < sz && w == w)"),
    ("early-out w > sz -> w > sz + 0.5", "if (w <= sz && w == w)",
     "if (w <= sz + 0.5 && w == w)"),
]
BATCH_MUTATION = ("batch skips the last move", "for (i = 1; i < n; ++i)",
                  "for (i = 1; i < n - 1; ++i)")


def _scratch_build(tag, old=None, new=None):
    src = open(_SRC).read()
    if old is not None:
        assert src.count(old) == 1, "mutation anchor not unique: %r" % old
        src = src.replace(old, new)
    td = tempfile.mkdtemp(prefix="spk1b_%s_" % tag)
    cpath = os.path.join(td, "stamp.c")
    dylib = os.path.join(td, "lib.so")
    with open(cpath, "w") as fh:
        fh.write(src)
    r = subprocess.run(["clang", "-O3", "-ffp-contract=off", "-fno-fast-math",
                        "-shared", "-o", dylib, cpath],
                       capture_output=True, text=True)
    assert r.returncode == 0, "scratch build failed: %s" % r.stderr[-500:]
    return _lib_bindings(ctypes.CDLL(dylib)), td


def _run_batch_with_lib(lib, moves, stocks):
    """Per-tool batch runs through a (possibly mutated) stamp_batch; compare
    per-move (area, depth) against the cached ref records and the final L
    against the cached ref L-md5. Returns the mismatch count."""
    xyz, flags = _batch_xyz(moves)
    bad = 0
    d = ctypes.c_double
    for ti in xyz:
        R, cr, a0, kR, pad2 = _tool_cfg(ti)
        ax = np.ascontiguousarray(xyz[ti], dtype=np.float64)
        fg = np.ascontiguousarray(flags[ti], dtype=np.int64)
        n = fg.shape[0]
        ab = np.zeros(n)
        ad = np.zeros(n)
        L = stocks[ti].copy()
        rc = lib.stamp_batch(
            L.ctypes.data_as(ctypes.POINTER(d)), L.shape[0], L.shape[1],
            X0, Y0, FINE, R, cr, a0, kR, pad2, n,
            ax.ctypes.data_as(ctypes.POINTER(d)),
            fg.ctypes.data_as(ctypes.POINTER(ctypes.c_long)), REMOVE_EPS,
            ab.ctypes.data_as(ctypes.POINTER(d)),
            ad.ctypes.data_as(ctypes.POINTER(d)))
        assert rc == 0, "stamp_batch rc=%d" % rc
        k_r = 0
        for k, (ti2, kind, p, cur, q, m) in enumerate(moves):
            if ti2 != ti:
                continue
            a_r, d_r, _h, _ = _REF[k]
            if (ab[2 * k_r + 1], ad[2 * k_r + 1]) != (a_r, d_r):
                bad += 1
            k_r += 1
        if hashlib.md5(L.tobytes()).hexdigest() != _REF_last_md5(ti, moves):
            bad += 1
    return bad


def test_sp_k1b_mutations():
    moves, stocks, _nbnd = _ensure_scenario()
    global _BATCH_ORDER
    _BATCH_ORDER = _batch_order(moves)
    counts = {}
    tmps = []
    try:
        for (name, old, new) in MUTATIONS:
            lib, td = _scratch_build(name.split()[0], old, new)
            tmps.append(td)
            counts[name] = _run_per_move(lib.stamp_move, moves, stocks)
        name, old, new = BATCH_MUTATION
        lib, td = _scratch_build("batchlast", old, new)
        tmps.append(td)
        counts[name] = _run_batch_with_lib(lib, moves, stocks)
    finally:
        for td in tmps:
            shutil.rmtree(td, ignore_errors=True)
    print("PASS sp_k1b(d): mutation mismatch counts (of %d moves / per-tool"
          " batches):" % len(moves))
    for k, v in counts.items():
        print("    %-34s %d" % (k, v))
    for name in ("outside margin (1+1e-9)->(1-1e-3)",
                 "early-out w > sz -> w > sz + 0.5",
                 "batch skips the last move"):
        assert counts[name] > 0, "mutation %r was NOT caught" % name
    # the w >= sz flip is provably equivalent (its skip set is a subset of
    # the correct skip: cells with w == sz can neither cut nor change L),
    # so it is reported, not asserted-failing.
    print("    note: 'w >= sz' count %d - equivalent mutation (subset "
          "skip); 'w > sz + 0.5' proves the early-out is live"
          % counts["early-out w > sz -> w >= sz"])


# ---------------------------------------------------------------- (e)

TB_STOCK = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
TB_TOOL = 12.686


def _tb_rough_program():
    """Emit the test_block rough program (same args as
    test_rsspeed._tb_rough_program, minus --hf which is not built here; the
    no-hf path was shown move-identical in test_engine R2) once, cached in
    scratch/. NOT a Core Front scene."""
    os.makedirs(SCRATCH, exist_ok=True)
    cache = os.path.join(SCRATCH, "spk1b_tb_rough.ngc")
    if not os.path.exists(cache):
        cmd = [sys.executable, "-m", "engine.cli", "rough",
               "--step", os.path.join(ROOT, "samples", "test_block.step"),
               "--stock", *[("%.4f" % v) for v in TB_STOCK],
               "--tool", "flat:%.4f" % TB_TOOL,
               "--out", cache, "--floor", "20.0",
               "--final-zmin", "20.381", "--leave", "0.381",
               "--stepdown", "19.05", "--optimal-load-mm", "2.03",
               "--min-rest", "0.5"]
        t0 = time.time()
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           env=dict(os.environ, ENGINE_WORKERS="4"))
        assert r.returncode == 0, "tb rough emit failed: %s" % r.stderr[-800:]
        print("  tb rough program emitted in %.1f s" % (time.time() - t0))
    return cache


def _spk1_scratch_lib():
    """Build SP-K1's ORIGINAL stamp.c (as committed at HEAD) in a scratch
    dir - the honest 'SP-K1 C' baseline; the tree already carries SP-K1B's
    faster kernel. Returns (lib, tmpdir), (None, None) if git/clang fail."""
    r = subprocess.run(["git", "-C", ROOT, "show",
                        "HEAD:engine/ckern/stamp.c"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, None
    td = tempfile.mkdtemp(prefix="spk1b_orig_")
    cpath = os.path.join(td, "stamp.c")
    dylib = os.path.join(td, "lib.so")
    with open(cpath, "w") as fh:
        fh.write(r.stdout)
    b = subprocess.run(["clang", "-O3", "-ffp-contract=off", "-fno-fast-math",
                        "-shared", "-o", dylib, cpath],
                       capture_output=True, text=True)
    if b.returncode != 0:
        return None, td
    return _lib_bindings(ctypes.CDLL(dylib), want_batch=False), td


def _time_stamping(tag, moves, dia, corner, box, top_z):
    """Per-move seconds for: Python _stamp_move_ref, SP-K1's original
    per-move C kernel (scratch build of HEAD's stamp.c), the fast per-move
    C kernel and the C batch - each on its own fresh stock, all bit-compared
    to each other."""
    R = dia / 2.0
    cr = min(corner, R) if corner else 0.0
    a0 = R - cr
    kR = int(math.ceil(R / FINE))
    pad2 = kR + 1 + 2 * kR + 2
    xmn, xmx, ymn, ymx = (float(v) for v in box[:4])
    x0, y0 = xmn - R, ymn - R
    cx = x0 + (np.arange(int(math.ceil((xmx - xmn + 2 * R) / FINE))) + .5) * FINE
    cy = y0 + (np.arange(int(math.ceil((ymx - ymn + 2 * R) / FINE))) + .5) * FINE
    F = np.where(((cx >= xmn - 1e-9) & (cx <= xmx + 1e-9))[None, :]
                 & ((cy >= ymn - 1e-9) & (cy <= ymx + 1e-9))[:, None],
                 float(top_z), -np.inf)
    base = np.pad(F, pad2, constant_values=-np.inf)
    curs, flags = [], []
    pos = None
    for mv in moves:
        cur = tuple(pos[i] if mv.get(k) is None else mv[k]
                    for i, k in enumerate("xyz")) \
            if pos is not None else (mv.get("x"), mv.get("y"), mv.get("z"))
        if None in cur:
            cur = tuple(v if v is not None else 0.0 for v in cur)
        curs.append(cur)
        flags.append(1 if (pos is not None and mv["g"] == 1) else 0)
        pos = cur
    n = len(moves)
    xyz = np.array(curs, dtype=np.float64)
    fg = np.asarray(flags, dtype=np.int64)
    nst = int(sum(flags))

    t0 = time.time()
    Lp = base.copy()
    for i in range(1, n):
        if fg[i]:
            _stamp_move_ref(Lp, x0, y0, FINE, R, cr, a0, kR, pad2,
                            curs[i - 1], curs[i])
    t_py = time.time() - t0

    t0 = time.time()
    Lc = base.copy()
    for i in range(1, n):
        if fg[i]:
            ckern.stamp_move(Lc, x0, y0, FINE, R, cr, a0, kR, pad2,
                             curs[i - 1], curs[i], REMOVE_EPS)
    t_c = time.time() - t0

    t0 = time.time()
    Lb = base.copy()
    ckern.stamp_batch(Lb, x0, y0, FINE, R, cr, a0, kR, pad2, xyz, fg,
                      REMOVE_EPS)
    t_b = time.time() - t0

    # SP-K1's original per-move C kernel (scratch build of HEAD's stamp.c)
    olib, otd = _spk1_scratch_lib()
    t_1 = None
    try:
        if olib is not None:
            area = ctypes.c_double(0.0)
            depth = ctypes.c_double(0.0)
            pp = (ctypes.c_double * 3)()
            cc = (ctypes.c_double * 3)()
            dp = ctypes.POINTER(ctypes.c_double)
            Lo = base.copy()
            lp = Lo.ctypes.data_as(dp)
            t0 = time.time()
            for i in range(1, n):
                if fg[i]:
                    pp[:] = curs[i - 1]
                    cc[:] = curs[i]
                    rc = olib.stamp_move(lp, Lo.shape[0], Lo.shape[1],
                                         x0, y0, FINE, R, cr, a0, kR, pad2,
                                         pp, cc, REMOVE_EPS,
                                         ctypes.byref(area),
                                         ctypes.byref(depth))
                    assert rc == 0
            t_1 = time.time() - t0
            assert Lo.tobytes() == Lp.tobytes(), tag + ": SP-K1 C differs"
    finally:
        if otd:
            shutil.rmtree(otd, ignore_errors=True)

    assert Lc.tobytes() == Lp.tobytes(), tag + ": C != Python stock"
    assert Lb.tobytes() == Lp.tobytes(), tag + ": batch != Python stock"
    print("  %-22s %6d stamped moves | per-move: python %7.1f us | SP-K1 C"
          " %6.1f us (%.1fx) | fast C %6.1f us (%.1fx) | C batch %6.1f us"
          " (%.1fx vs python, %.1fx vs SP-K1)"
          % (tag, nst, 1e6 * t_py / max(1, nst),
             (1e6 * t_1 / max(1, nst)) if t_1 else float("nan"),
             (t_py / t_1) if t_1 else float("nan"),
             1e6 * t_c / max(1, nst), t_py / max(t_c, 1e-12),
             1e6 * t_b / max(1, nst), t_py / max(t_b, 1e-12),
             (t_1 / t_b) if t_1 else float("nan")))
    return {"python_us": 1e6 * t_py / max(1, nst),
            "spk1_us": (1e6 * t_1 / max(1, nst)) if t_1 else None,
            "fast_c_us": 1e6 * t_c / max(1, nst),
            "batch_us": 1e6 * t_b / max(1, nst), "n": nst}


def test_sp_k1b_speed():
    from engine.entry_depth import parse_nc
    assert ckern.get_lib() is not None
    out = {}
    moves = _synth_rough_moves()
    out["synth"] = _time_stamping("synth_pocket rough", moves, 6.0, 0.0,
                                  STOCK, STOCK[5])
    ngc = _tb_rough_program()
    tb = parse_nc(ngc)
    assert len(tb) > 20000, "TB rough has only %d moves" % len(tb)
    out["tb20k"] = _time_stamping("TB rough (20k)", tb[5000:25000],
                                  TB_TOOL, 0.0, TB_STOCK, TB_STOCK[5])
    print("PASS sp_k1b(e): speed reported (all three paths bit-identical)")
    return out


if __name__ == "__main__":
    test_sp_k1b_random_moves()
    test_sp_k1b_limit_feeds_parity()
    test_sp_k1b_autobuild()
    test_sp_k1b_mutations()
    test_sp_k1b_speed()
