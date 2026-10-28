#!/usr/bin/env python3
"""RS-SPEED red tests (run on the UNCHANGED code first).

(a) test_rsspeed_matches_reference: replay_stock's output must stay
    BIT-IDENTICAL (np.array_equal, dtype/shape, x0/y0/cell, saved .npy and
    sidecar .json) to today's implementation, kept here verbatim as
    _replay_stock_reference (this reference is NEVER edited).
(b) test_rsspeed_timing: on a seeded synthetic program sized so today's
    code takes ~20-40 s on the M4, the new replay_stock must be >= 4x
    faster than _replay_stock_reference (both measured in the test).

Run (small-test lane, VibeCAD python):
    <lane> /Applications/VibeCAD.app/Contents/Resources/bin/python -c \
        "import sys; sys.path.insert(0,'.'); import engine.test_rsspeed as t; t.<name>()"
"""
import math
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from engine.entry_depth import FINE, replay_stock, resample_fine, parse_nc  # noqa: E402

SCRATCH = os.path.join(ROOT, "scratch")


def _replay_stock_reference(moves, dia, corner, out_path, box=None,
                            top_z=None, init=None, fine=FINE):
    """VERBATIM copy of replay_stock @ d6f435f (engine/entry_depth.py:334).
    NEVER edit this function - it is the bit-identity reference."""
    import json, os, time
    t0 = time.time()
    R = float(dia) / 2.0
    cr = min(float(corner), R) if corner else 0.0
    if init is not None:
        A0, x0, y0, cell = init
        # same pitch: resample_fine would max-pool the touching neighbour
        F = A0 if abs(float(cell) - fine) < 1e-12 \
            else resample_fine(A0, x0, y0, cell, fine)
    else:
        xmn, xmx, ymn, ymx = (float(v) for v in box[:4])
        x0, y0 = xmn - R, ymn - R
        cx = x0 + (np.arange(int(math.ceil((xmx - xmn + 2 * R) / fine))) + .5) * fine
        cy = y0 + (np.arange(int(math.ceil((ymx - ymn + 2 * R) / fine))) + .5) * fine
        F = np.where(((cx >= xmn - 1e-9) & (cx <= xmx + 1e-9))[None, :]
                     & ((cy >= ymn - 1e-9) & (cy <= ymx + 1e-9))[:, None],
                     float(top_z), -np.inf)
    kR = int(math.ceil(R / fine))
    pad, a0 = kR + 1, R - cr
    L = np.pad(F, pad, constant_values=-np.inf)
    pos = None
    for mv in moves:
        cur = tuple(p if mv.get(k) is None else mv[k]
                    for k, p in zip("xyz", pos or (0.0, 0.0, 0.0)))
        if pos is not None and mv["g"] == 1:
            d = np.subtract(cur, pos)
            n = 1 if abs(d[0]) <= 1e-9 and abs(d[1]) <= 1e-9 else max(
                2, int(math.ceil(float(np.linalg.norm(d)) / (fine / 4.0))))
            for t in np.linspace(0.0, 1.0, n + 1):
                sx, sy = pos[0] + d[0] * t, pos[1] + d[1] * t
                sz = min(pos[2], cur[2]) if n == 1 else pos[2] + d[2] * t
                j = int(math.floor((sy - y0) / fine)) + pad
                i = int(math.floor((sx - x0) / fine)) + pad
                j0, j1 = max(0, j - kR), min(L.shape[0], j + kR + 1)
                i0, i1 = max(0, i - kR), min(L.shape[1], i + kR + 1)
                if j0 >= j1 or i0 >= i1: continue
                gx = x0 + (np.arange(i0, i1) - pad + 0.5) * fine - sx
                gy = y0 + (np.arange(j0, j1) - pad + 0.5) * fine - sy
                dd = np.hypot(gx[None, :], gy[:, None])
                dz = (cr - np.sqrt(np.maximum(
                    cr * cr - np.maximum(dd - a0, 0.0) ** 2, 0.0))
                    if cr else 0.0)
                w = L[j0:j1, i0:i1]
                np.minimum(w, np.where(dd <= R + 1e-9, sz + dz, np.inf), out=w)
        pos = cur
    A = L[pad:-pad, pad:-pad]
    np.save(out_path, A)
    with open(os.path.splitext(out_path)[0] + ".json", "w") as fh:
        json.dump({"x0": x0, "y0": y0, "cell": fine}, fh)
    print("replay_stock: %d moves -> %s in %.1f s"
          % (len(moves), out_path, time.time() - t0), flush=True)
    return A, x0, y0, fine


BOX = (-40.0, 40.0, -30.0, 30.0)
TOP_Z = 15.0


def _synth_moves(n_moves, seed=20261027):
    """Seeded pseudo-random program: G0/G1, pure plunges (missing x/y),
    zero-length moves, missing-axis modal moves, long diagonals, ramps."""
    rng = np.random.default_rng(seed)
    moves = [{"g": 0, "x": -35.0, "y": -25.0, "z": 20.0}]
    px, py, pz = -35.0, -25.0, 20.0
    for _ in range(n_moves):
        kind = rng.integers(0, 10)
        if kind == 0:                       # G0 reposition
            px, py = float(rng.uniform(*BOX[:2])), float(rng.uniform(*BOX[2:]))
            pz = 20.0
            moves.append({"g": 0, "x": px, "y": py, "z": pz})
        elif kind == 1:                     # pure plunge (missing x/y)
            pz = float(rng.uniform(2.0, 12.0))
            moves.append({"g": 1, "z": pz})
        elif kind == 2:                     # zero-length move
            moves.append({"g": 1, "x": px, "y": py, "z": pz})
        elif kind == 3:                     # missing-x modal move
            py = float(rng.uniform(*BOX[2:]))
            pz = float(rng.uniform(2.0, 12.0))
            moves.append({"g": 1, "y": py, "z": pz})
        elif kind == 4:                     # long diagonal
            px, py = float(rng.uniform(*BOX[:2])), float(rng.uniform(*BOX[2:]))
            pz = float(rng.uniform(2.0, 12.0))
            moves.append({"g": 1, "x": px, "y": py, "z": pz})
        elif kind == 5:                     # G0 with missing z (modal)
            px, py = float(rng.uniform(*BOX[:2])), float(rng.uniform(*BOX[2:]))
            moves.append({"g": 0, "x": px, "y": py})
        else:                               # ordinary short feed move
            px = float(np.clip(px + rng.uniform(-3.0, 3.0), *BOX[:2]))
            py = float(np.clip(py + rng.uniform(-3.0, 3.0), *BOX[2:]))
            pz = float(np.clip(pz + rng.uniform(-0.8, 0.4), 1.5, 14.0))
            moves.append({"g": 1, "x": px, "y": py, "z": pz})
    return moves


def _check_equal(td, name, ref_out, new_out, ref_ret, new_ret):
    A_r, x0r, y0r, cr_ = ref_ret
    A_n, x0n, y0n, cn = new_ret
    assert A_n.dtype == A_r.dtype and A_n.shape == A_r.shape, \
        "%s: dtype/shape changed %s/%s vs %s/%s" % (
            name, A_n.dtype, A_n.shape, A_r.dtype, A_r.shape)
    assert np.array_equal(A_n, A_r), \
        "%s: replay array changed (not bit-identical)" % name
    assert (x0n, y0n, cn) == (x0r, y0r, cr_), \
        "%s: sidecar changed %s vs %s" % (name, (x0n, y0n, cn), (x0r, y0r, cr_))
    F_r = np.load(os.path.join(td, ref_out))
    F_n = np.load(os.path.join(td, new_out))
    assert F_r.dtype == F_n.dtype and F_r.shape == F_n.shape
    assert np.array_equal(np.nan_to_num(F_r, neginf=-1e308),
                          np.nan_to_num(F_n, neginf=-1e308)), \
        "%s: saved .npy changed" % name
    import json
    with open(os.path.join(td, os.path.splitext(ref_out)[0] + ".json")) as fh:
        m_r = json.load(fh)
    with open(os.path.join(td, os.path.splitext(new_out)[0] + ".json")) as fh:
        m_n = json.load(fh)
    assert m_r == m_n, "%s: sidecar json changed %s vs %s" % (name, m_n, m_r)
    n_changed = int((F_r != F_n).sum()) if F_r.shape == F_n.shape else -1
    print("  %-28s equal (cells differing: %d)" % (name, n_changed))


def _run_pair(td, moves, dia, corner, tag, **kw):
    ro, no = tag + "_ref.npy", tag + "_new.npy"
    ref = _replay_stock_reference(moves, dia, corner, os.path.join(td, ro), **kw)
    new = replay_stock(moves, dia, corner, os.path.join(td, no), **kw)
    _check_equal(td, tag, ro, no, ref, new)


def _tb_rough_program():
    """Emit the test_block rough program (manifest-pinned fixtures, same
    args as engine/test_finish.py test_rrstock_rough_handoff_not_below_judge)
    once and cache it in scratch/ (generation ~1-2 min)."""
    os.makedirs(SCRATCH, exist_ok=True)
    cache = os.path.join(SCRATCH, "rsspeed_tb_rough.ngc")
    if not os.path.exists(cache):
        stock_box = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
        cmd = [sys.executable, "-m", "engine.cli", "rough",
               "--step", os.path.join(ROOT, "samples", "test_block.step"),
               "--stock", *[("%.4f" % v) for v in stock_box],
               "--tool", "flat:12.6860",
               "--out", cache, "--floor", "20.0",
               "--final-zmin", "20.381", "--leave", "0.381",
               "--stepdown", "19.05", "--optimal-load-mm", "2.03",
               "--hf", os.path.join(ROOT, "out", "test_block_hf_0.5.npy"),
               "--min-rest", "0.5"]
        t0 = time.time()
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           env=dict(os.environ, ENGINE_WORKERS="4"))
        assert r.returncode == 0, "tb rough emit failed: %s" % r.stderr[-500:]
        print("  tb rough program emitted in %.1f s" % (time.time() - t0))
    return cache


def test_rsspeed_matches_reference():
    """(a) the new replay_stock must be bit-identical to the verbatim
    reference on synthetic + real programs. On the UNCHANGED code this
    passes trivially (both are the same code); its job is to guard the
    new implementation."""
    small = _synth_moves(300)
    with tempfile.TemporaryDirectory() as td:
        # synthetic program, box stock, flat / bull / ball, incl. a
        # ceil-sensitive radius (R/fine not integral)
        for tag, dia, corner in (("flat6", 6.0, 0.0),
                                 ("bull6", 6.0, 1.5),
                                 ("ball6", 6.0, 3.0),
                                 ("flat12.686", 12.686, 0.0),
                                 ("bull6.2", 6.2, 1.55)):
            _run_pair(td, small, dia, corner, "synth_" + tag,
                      box=BOX, top_z=TOP_Z)
        # init= same pitch (finite + -inf cells)
        rng = np.random.default_rng(7)
        A0 = np.where(rng.random((40, 50)) < 0.3, -np.inf,
                      rng.uniform(4.0, 12.0, (40, 50)))
        for tag, dia, corner in (("flat6", 6.0, 0.0), ("ball6", 6.0, 3.0)):
            _run_pair(td, small, dia, corner, "init_same_" + tag,
                      init=(A0, -12.0, -9.0, 0.1))
        # init= coarser pitch (exercises resample_fine)
        for tag, dia, corner in (("flat6", 6.0, 0.0), ("bull6", 6.0, 1.5)):
            _run_pair(td, small, dia, corner, "init_coarse_" + tag,
                      init=(A0, -12.0, -9.0, 0.5))
        # cells whose centre sits at distance EXACTLY R from the path
        # (diameter 3.05 on the 0.1 mm grid, path along the box edge
        # y = ymin, so the R + 1e-9 mask boundary is bit-critical there):
        # long move (capsule path) and short move (batch path), flat+ball
        edge_long = [{"g": 0, "x": -5.0, "y": -10.0, "z": 20.0},
                     {"g": 1, "z": 8.0},
                     {"g": 1, "x": 5.0, "y": -10.0, "z": 8.0},
                     {"g": 0, "z": 20.0}]
        edge_short = [{"g": 0, "x": -5.0, "y": -10.0, "z": 20.0},
                      {"g": 1, "z": 8.0},
                      {"g": 1, "x": -4.8, "y": -10.0, "z": 8.0},
                      {"g": 0, "z": 20.0}]
        for tag, ms, dia, corner in (("edge_long_flat", edge_long, 3.05, 0.0),
                                     ("edge_short_flat", edge_short, 3.05, 0.0),
                                     ("edge_long_ball", edge_long, 3.05, 1.525),
                                     ("edge_short_ball", edge_short, 3.05, 1.525)):
            _run_pair(td, ms, dia, corner, tag,
                      box=(-10.0, 10.0, -10.0, 10.0), top_z=10.0)
        # the test_block rough program (real emitted moves, big grid)
        ngc = _tb_rough_program()
        moves = parse_nc(ngc)
        print("  tb rough program: %d moves" % len(moves))
        _run_pair(td, moves, 12.686, 0.0, "tb_rough",
                  box=(-50.0, 50.0, -40.0, 40.0), top_z=38.0)
    print("test_rsspeed_matches_reference: PASS")


def test_rsspeed_timing():
    """(b) on the seeded synthetic program below (sized so TODAY's code
    takes ~20-40 s on the M4) the new replay_stock must be >= 4x faster
    than the reference. FAILS on the unchanged code (ratio ~1.0).
    The gated program uses the CF-rough tool (flat 12.686), the replay
    the brief's <= 120 s target is about; the ball ratio is printed."""
    moves_flat = _synth_moves(2000)   # reference ~30 s on the M4
    moves_ball = _synth_moves(1200)   # reference ~21 s on the M4
    with tempfile.TemporaryDirectory() as td:
        for tag, dia, corner, moves, gate in (
                ("flat12.686", 12.686, 0.0, moves_flat, True),
                ("ball6", 6.0, 3.0, moves_ball, False)):
            ro, no = "t_" + tag + "_ref.npy", "t_" + tag + "_new.npy"
            t0 = time.time()
            _replay_stock_reference(moves, dia, corner, os.path.join(td, ro),
                                    box=BOX, top_z=TOP_Z)
            t_ref = time.time() - t0
            t0 = time.time()
            replay_stock(moves, dia, corner, os.path.join(td, no),
                         box=BOX, top_z=TOP_Z)
            t_new = time.time() - t0
            ratio = t_ref / t_new
            print("timing %s: reference %.2f s, new %.2f s, ratio %.2fx%s"
                  % (tag, t_ref, t_new, ratio, "" if gate else " (info)"))
            if gate:
                assert ratio >= 4.0, \
                    "%s: only %.2fx faster (%.2f s -> %.2f s), need >= 4x" % (
                        tag, ratio, t_ref, t_new)
    print("test_rsspeed_timing: PASS")
