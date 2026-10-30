"""Task SP-K2B tests: zmap.simulate's WHOLE per-sample loop for one move
runs in the C kernel (verify/zkern/zcut.c zcut_move) and must reproduce the
Python per-move loop exactly.

Run with homebrew/VibeCAD pytest, C path active (ZMAP_NO_CKERN unset).
The existing verify/test_zmap.py is separately required to pass on BOTH
paths (C and ZMAP_NO_CKERN=1) - see verify/SPK2B_RESULTS.md for the runs.
"""
import math
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zmap   # noqa: E402
import zkern  # noqa: E402

KERN = zkern.load()
pytestmark = pytest.mark.skipif(KERN is None,
                                reason="C kernel not loaded (ZMAP_NO_CKERN?)")

NMOVES = int(os.environ.get("SPK2B_NMOVES", "2000"))


# ---------------------------------------------------------------------------
# comparison helpers (same bar as SP-K2: ints/flags/lists identical,
# floats within rel 1e-9 or abs 1e-9; the stock grid bit-identical)
# ---------------------------------------------------------------------------

def _close(x, y):
    if x == y:
        return True
    if isinstance(x, float) and isinstance(y, float) \
            and math.isnan(x) and math.isnan(y):
        return True
    if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
        return x == y
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))


def _diff(a, b, path="", out=None):
    if out is None:
        out = []
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out.append((path, "keys differ", sorted(set(a) ^ set(b))))
            return out
        for key in a:
            _diff(a[key], b[key], path + "/" + str(key), out)
    elif isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a2 = np.asarray(a)
        b2 = np.asarray(b)
        if a2.shape != b2.shape or not np.array_equal(a2, b2):
            out.append((path, "array differs", (a2.shape, b2.shape)))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "len", (len(a), len(b))))
            return out
        for i, (u, v) in enumerate(zip(a, b)):
            _diff(u, v, "%s/%d" % (path, i), out)
    elif isinstance(a, bool) or isinstance(b, bool) or \
            isinstance(a, str) or isinstance(b, str) or \
            a is None or b is None:
        if a != b:
            out.append((path, a, b))
    elif isinstance(a, int) and isinstance(b, int):
        if a != b:
            out.append((path, a, b))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not _close(a, b):
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def _simulate_both(moves, part, cell, x0, y0, box, kw, stock_c, stock_p,
                   start):
    """Run the same move list on the C path and the Python path; return
    (rep_c, rep_p) with fresh stock copies each time."""
    old = zmap._KERN
    rep_c = zmap.simulate(moves, part, cell, x0, y0, box,
                          stock_init=stock_c.copy(), start=start, **kw)
    zmap._KERN = None
    try:
        rep_p = zmap.simulate(moves, part, cell, x0, y0, box,
                              stock_init=stock_p.copy(), start=start, **kw)
    finally:
        zmap._KERN = old
    return rep_c, rep_p


# ---------------------------------------------------------------------------
# scenes: parts + move chains built to trigger shank hits, holder
# intrusions and EXACT argmin ties (plunges at cell corners over a plateau)
# ---------------------------------------------------------------------------

def _fmt(v):
    return ("%.6f" % v).rstrip("0").rstrip(".")


def _mk_part(nx, ny, cell, x0, y0, plateau=10.0, ridge_x=None,
             ridge_part=None):
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    cx, cy = x0 + nx * cell / 2.0, y0 + ny * cell / 2.0
    part = np.zeros((ny, nx))
    part[(np.abs(xs - cx)[None, :] <= 6.0)
         & (np.abs(ys - cy)[:, None] <= 6.0)] = plateau
    if ridge_x is not None:
        p2 = np.full((ny, nx), ridge_part if ridge_part is not None else 0.0)
        p2[:, np.abs(xs - ridge_x) <= cell] = plateau
        part = np.maximum(part, p2)
    return part


def _mk_chain(rng, n, cell, x0, y0, box, tool, window_on, ridge_x=None):
    """One scene: part, optional window, and n gcode move strings + the
    starting position. Moves: plunges to low Z (shank/holder hits), rasters
    at depth, rapids, arcs, moves partly outside the grid (window clipping);
    every 25th move is a plunge at an EXACT cell corner over the plateau to
    force np.argmin ties (x0=y0=0, cell a power of two keeps these exact)."""
    nx = int(round((box[1] - box[0]) / cell))
    ny = int(round((box[3] - box[2]) / cell))
    part = _mk_part(nx, ny, cell, x0, y0, ridge_x=ridge_x)
    window = None
    if window_on:
        xs = x0 + (np.arange(nx) + 0.5) * cell
        ys = y0 + (np.arange(ny) + 0.5) * cell
        cx, cy = x0 + nx * cell / 2.0, y0 + ny * cell / 2.0
        window = ((np.abs(xs - cx)[None, :] <= 9.0)
                  & (np.abs(ys - cy)[:, None] <= 9.0))
    gx0, gx1 = x0, x0 + nx * cell
    gy0, gy1 = y0, y0 + ny * cell
    xs_c = x0 + (np.arange(nx) + 0.5) * cell
    ys_c = y0 + (np.arange(ny) + 0.5) * cell
    cxm, cym = x0 + nx * cell / 2.0, y0 + ny * cell / 2.0
    ipx = np.where(np.abs(xs_c - cxm) <= 6.0)[0]
    ipy = np.where(np.abs(ys_c - cym) <= 6.0)[0]
    mx_lo, mx_hi = int(ipx[0]) + 1, int(ipx[-1]) + 1
    my_lo, my_hi = int(ipy[0]) + 1, int(ipy[-1]) + 1
    moves = []
    cur = [float(rng.uniform(gx0 + 2, gx1 - 2)),
           float(rng.uniform(gy0 + 2, gy1 - 2)), 25.0]
    for t in range(n):
        kind = rng.random()
        if kind < 0.15:                      # rapid reposition high (air)
            tx = float(rng.uniform(gx0 - 2.0, gx1 + 2.0))
            ty = float(rng.uniform(gy0 - 2.0, gy1 + 2.0))
            line = "G0 X%s Y%s Z25." % (_fmt(tx), _fmt(ty))
        elif kind < 0.30:                    # deep oblique plunge (hits)
            tx = float(rng.uniform(gx0 + 1.0, gx1 - 1.0))
            ty = float(rng.uniform(gy0 + 1.0, gy1 - 1.0))
            tz = float(rng.uniform(-1.0, 3.0))
            line = "G1 X%s Y%s Z%s F%d." % (_fmt(tx), _fmt(ty), _fmt(tz),
                                            int(rng.choice([150, 300, 500])))
        elif kind < 0.55:                    # feed at depth (cut + air mix)
            tx = float(rng.uniform(gx0 - 1.0, gx1 + 1.0))
            ty = float(rng.uniform(gy0 - 1.0, gy1 + 1.0))
            tz = float(rng.uniform(-1.0, 9.0))
            line = "G1 X%s Y%s Z%s F%d." % (_fmt(tx), _fmt(ty), _fmt(tz),
                                            int(rng.choice([400, 800, 1500])))
        elif kind < 0.70:                    # horizontal feed at depth
            tx = float(rng.uniform(gx0, gx1))
            ty = float(rng.uniform(gy0, gy1))
            line = "G1 X%s Y%s F%d." % (_fmt(tx), _fmt(ty),
                                        int(rng.choice([600, 1200])))
        elif kind < 0.85:                    # arc (G17) at depth
            tx = float(rng.uniform(gx0 + 1.0, gx1 - 1.0))
            ty = float(rng.uniform(gy0 + 1.0, gy1 - 1.0))
            ii = float(rng.uniform(-4.0, 4.0))
            jj = float(rng.uniform(-4.0, 4.0))
            g = "G2" if rng.random() < 0.5 else "G3"
            line = "%s X%s Y%s I%s J%s F%d." % (g, _fmt(tx), _fmt(ty),
                                                _fmt(ii), _fmt(jj),
                                                int(rng.choice([600, 900])))
        else:                                # vertical-only feed (plunge)
            tz = float(rng.uniform(-1.0, 9.0))
            line = "G1 Z%s F%d." % (_fmt(tz), int(rng.choice([150, 250])))
        if t % 25 == 7:
            # rapid above an exact cell corner, then a PURE vertical plunge
            # onto it: the 4 corner cells are at bitwise-equal hypot
            # distance -> np.argmin exact tie decides worst_xy at the
            # deepest sample (largest excess); mx_lo/mx_hi keep both corner
            # cells inside the plateau (cell 0.5 is a power of two, so the
            # corner coordinates are exact in binary)
            m = int(rng.integers(mx_lo, mx_hi))
            nn = int(rng.integers(my_lo, my_hi))
            corner_x = x0 + m * cell
            corner_y = y0 + nn * cell
            line = ("G0 X%s Y%s Z25.\nG1 X%s Y%s Z0.5 F200."
                    % (_fmt(corner_x), _fmt(corner_y),
                       _fmt(corner_x), _fmt(corner_y)))
        moves.append((line, cur))
        # advance cur by parsing the mini program's last move
        mv = zmap.parse_gcode("G21 G90\n" + line + "\n")[-1]
        cur = [mv["x"] if mv["x"] is not None else cur[0],
               mv["y"] if mv["y"] is not None else cur[1],
               mv["z"] if mv["z"] is not None else cur[2]]
    return part, window, moves


def _chain_kw(tool, cell, ridge_chain=False):
    holder = [[0.0, 50.0, 4.0, 5.0]]
    kw = dict(tool=tool, dia={"flat": 6.0, "bull": 9.525, "ball": 9.525}[tool],
              corner=1.5 if tool == "bull" else 0.0,
              flute=3.0, shank_dia=8.0, holder=holder, stickout=8.0,
              engage_max=2.0)
    return kw


def _run_chain(tag, rng, n, cell, x0, y0, box, tool, window_on,
               ridge_x=None, stock0=None):
    """Run one move chain move-by-move (stock_init chained); after EVERY
    move the stock grids must be byte-identical and every report field
    within the bar. Returns stats dict."""
    part, window, moves = _mk_chain(rng, n, cell, x0, y0, box, tool,
                                    window_on, ridge_x=ridge_x)
    kw = _chain_kw(tool, cell)
    if window is not None:
        kw["window"] = window
    base = np.array(stock0 if stock0 is not None
                    else np.full(part.shape, box[5]), dtype=float)
    stock_c = base.copy()
    stock_p = base.copy()
    stats = dict(moves=0, shank_hits=0, holder_hits=0, rapids=0,
                 tie_checked=0, plunge=0)
    fails = []
    for t, (line, cur) in enumerate(moves):
        prog = zmap.parse_gcode("G21 G90\n" + line + "\n")
        rep_c, rep_p = _simulate_both(prog, part, cell, x0, y0, box, kw,
                                      stock_c, stock_p, list(cur))
        if rep_c["zcut_kernel"] != "c" or rep_p["zcut_kernel"] != "python":
            fails.append((t, "kernel flag", rep_c["zcut_kernel"],
                          rep_p["zcut_kernel"]))
        if rep_c["stock"].tobytes() != rep_p["stock"].tobytes():
            fails.append((t, line, "stock bytes differ"))
        rc = rep_c.pop("zcut_kernel")
        rp = rep_p.pop("zcut_kernel")
        bad = _diff(rep_c, rep_p, "%s/%d" % (tag, t))
        if bad:
            fails.append((t, line, bad[:6]))
        # tie case: exact corner plunge -> argmin first-index rule expected
        if line.startswith("G0 X") and line.endswith("Z0.5 F200."):
            mv = prog[0]
            i0 = int(math.floor((mv["x"] - x0) / cell))
            j0 = int(math.floor((mv["y"] - y0) / cell))
            xs = x0 + (np.arange(part.shape[1]) + 0.5) * cell
            ys = y0 + (np.arange(part.shape[0]) + 0.5) * cell
            want = [float(xs[i0 - 1]), float(ys[j0 - 1])]
            got = (rep_c["over_flute"] or {}).get("worst_xy")
            got_h = (rep_c["holder_hits"] or {}).get("worst_xy")
            if got is not None:
                if got != want:
                    fails.append((t, line, "shank tie xy %r != %r"
                                  % (got, want)))
                if got_h is not None and got_h != want:
                    fails.append((t, line, "holder tie xy %r != %r"
                                  % (got_h, want)))
                stats["tie_checked"] += 1
        if (rep_c["over_flute"] or {}).get("count", 0) > 0:
            stats["shank_hits"] += 1
        if (rep_c["holder_hits"] or {}).get("count", 0) > 0:
            stats["holder_hits"] += 1
        if rep_c["rapid_collisions"]["count"] > 0:
            stats["rapids"] += 1
        if rep_c["plunge"]["count"] > 0:
            stats["plunge"] += 1
        stats["moves"] += 1
        stock_c = rep_c["stock"]
        stock_p = rep_p["stock"]
    return fails, stats


def test_2000_random_moves_c_permove_equals_python():
    """2,000 random moves with shank and holder ON, flat/bull/ball, near
    mask on and off, windows clipped at the grid edges: every per-move
    report field within the bar and the stock byte-identical after every
    move (stock_init chained move by move)."""
    total = NMOVES
    per = total // 10
    plan = [
        # tag, cell, x0, y0, box, tool, window_on, ridge_x
        ("flat0", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "flat", False, None),
        ("flatW", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "flat", True, None),
        ("bull0", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "bull", False, None),
        ("ballW", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "ball", True, None),
        ("ball0", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "ball", False, None),
        # exact cell-corner ties need x0=y0 and a power-of-two cell
        ("tie_flat", 0.5, 0.0, 0.0, (0.0, 18.0, 0.0, 18.0, -2.0, 10.0),
         "flat", False, None),
        ("tie_ballW", 0.5, 0.0, 0.0, (0.0, 18.0, 0.0, 18.0, -2.0, 10.0),
         "ball", True, None),
        ("tie_bull0", 0.5, 0.0, 0.0, (0.0, 18.0, 0.0, 18.0, -2.0, 10.0),
         "bull", False, None),
        # ridge chains: stock cleared to 0 away from the plateau/ridge so
        # holder hits are LOCALISED (sensitive to the envelope radius)
        ("ridge_flat", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0,
                                           10.0), "flat", False, 12.0),
        ("ridge_ballW", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0,
                                            10.0), "ball", True, 12.0),
    ]
    all_fails = []
    stats = dict(moves=0, shank_hits=0, holder_hits=0, rapids=0,
                 tie_checked=0, plunge=0)
    for ci, (tag, cell, x0, y0, box, tool, won, ridge) in enumerate(plan):
        rng = np.random.default_rng(20261029 + ci)
        if ridge is not None:
            nx = int(round((box[1] - box[0]) / cell))
            ny = int(round((box[3] - box[2]) / cell))
            part0 = _mk_part(nx, ny, cell, x0, y0, ridge_x=ridge)
            xs = x0 + (np.arange(nx) + 0.5) * cell
            ys = y0 + (np.arange(ny) + 0.5) * cell
            cx, cy = x0 + nx * cell / 2.0, y0 + ny * cell / 2.0
            keep = ((np.abs(xs - cx)[None, :] <= 6.0)
                    & (np.abs(ys - cy)[:, None] <= 6.0))
            ridge_keep = np.broadcast_to(
                (np.abs(xs - ridge)[None, :] <= cell), (ny, nx))
            stock0 = np.where(keep | ridge_keep, box[5], 0.0)
        else:
            stock0 = None
        fails, st = _run_chain(tag, rng, per, cell, x0, y0, box, tool, won,
                               ridge_x=ridge, stock0=stock0)
        all_fails.extend(fails)
        for key in stats:
            stats[key] += st[key]
    print("SP-K2B random-chain stats:", stats)
    assert not all_fails, ("%d mismatch entries in %d moves; first: %r"
                           % (len(all_fails), stats["moves"], all_fails[:3]))
    assert stats["shank_hits"] >= max(10, NMOVES // 50), \
        "chain built too few shank hits"
    assert stats["holder_hits"] >= max(10, NMOVES // 50), \
        "chain built too few holder hits"
    assert stats["tie_checked"] >= max(8, NMOVES // 250), \
        "no exact argmin ties were checked"
