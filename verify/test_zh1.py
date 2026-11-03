"""Task ZH1 (entry_stock gate): a descent entry must not start its first feed
under standing stock anywhere in the run's swept footprint. Synthetic, no
FreeCAD, no engine imports. Values are known from the grid:
(a) helix started 1 mm over the stock top -> 0 entries over the bar;
(b) inj3 shape: the G0 column is pre-cleared (no rapid collision) but the
    helix's swept disk reaches standing stock 4 mm above the tip -> 1 entry,
    measured 4.0 mm (bar = max(pitch 1.0, 0.5));
(c) offset side entry: G0 down a cleared column, horizontal feed-in into the
    wall at depth -> 0 (the run is the landing disk only);
(d) serial == --jobs; (e) a ball is judged at its surface, not its tip; (f) a level traverse G0
to a helix start is an entry."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zmap  # noqa: E402

CELL = 0.5
X0 = Y0 = -25.0
N = 100
STOCK = (-25.0, 25.0, -25.0, 25.0, 0.0, 10.0)
C = X0 + (np.arange(N) + 0.5) * CELL
PART = np.full((N, N), -5.0)


def helix(cx, cy, r, z0, z1, pitch=1.0, seg=24):
    """Polyline helix from angle 0 (point (cx + r, cy)) down to z1."""
    out, n = [], int(round((z0 - z1) / pitch * seg))
    for t in range(1, n + 1):
        a = 2 * math.pi * t / seg
        out.append("G1 X%.4f Y%.4f Z%.4f F500" % (cx + r * math.cos(a),
                                                cy + r * math.sin(a),
                                                z0 - (z0 - z1) * t / n))
    return out


def run(lines, stock_init=None, jobs=None):
    moves = zmap.parse_gcode("G21 G90\n" + "\n".join(lines) + "\n")
    if jobs:
        return zmap.simulate_parallel(moves, PART, CELL, X0, Y0, STOCK, jobs,
                                      dia=6.0, stock_init=stock_init)
    return zmap.simulate(moves, PART, CELL, X0, Y0, STOCK, dia=6.0,
                         stock_init=stock_init)


def column_cleared(cx, cy, rad, z):
    st = np.full((N, N), 10.0)
    st[np.hypot(C[None, :] - cx, C[:, None] - cy) <= rad] = z
    return st


def test_helix_over_stock_passes():
    r = run(["G0 X0 Y0 Z20", "G0 X3 Y0 Z11"] + helix(0, 0, 3, 11, 8)
            + ["G1 X0 Y0 Z8 F500"])
    es = r["entry_stock"]
    assert es["entries"] == 1 and es["count"] == 0, es
    assert abs(es["max_mm"] - (-1.0)) < 1e-9, es


def test_helix_under_standing_stock_fails():
    # the G0 landing column (R = 3 about (3, 0)) is cleared to Z5; the helix
    # about (0, 0) r 3 sweeps a 6 mm disk that still stands at Z10
    lines = ["G0 X3 Y0 Z20", "G0 X3 Y0 Z6"] + helix(0, 0, 3, 6, 3)
    r = run(lines, column_cleared(3, 0, 3.5, 5.0))
    assert r["rapid_collisions"]["count"] == 0, r["rapid_collisions"]
    es = r["entry_stock"]
    assert es["count"] == 1, es
    rec = es["records"][0]
    assert abs(rec[4] - (-1.0)) < 1e-9, rec      # column: 1 mm clear
    assert abs(rec[5] - 4.0) < 1e-9, rec         # swept disk: 4 mm standing
    assert abs(rec[3] - 1.0) < 0.01, rec          # bar = measured pitch ~1.0
    assert abs(es["max_over_bar_mm"] - (4.0 - rec[3])) < 1e-3, es


def test_offset_side_entry_passes():
    st = np.full((N, N), 10.0)
    st[:, C < 0] = 5.0                            # cleared half
    r = run(["G0 X-6 Y0 Z20", "G0 X-6 Y0 Z6", "G1 X4 Y0 Z6 F500"], st)
    es = r["entry_stock"]
    assert es["entries"] == 1 and es["count"] == 0, es
    assert abs(es["records"][0][5] - (-1.0)) < 1e-9, es


def test_ball_judged_at_its_surface():
    """(e) ball / flat on the same stock: a bowl standing 0.3 mm under a
    6 mm ball's surface at the landing point (and 5 mm deep elsewhere). The
    ball reads -0.3 (pass); a flat tool reads the rise at the outermost grid cell - 0.3 over
    its tip (fail) - the rim stock a ball never touches only fails a flat."""
    d = np.hypot(C[None, :] - 0.0, C[:, None] - 0.0)
    rise = zmap.tool_dz("ball", 6.0, 3.0)(np.minimum(d, 3.0))
    st = np.where(d <= 3.0 + 1e-9, 6.0 + rise - 0.3, 5.0)
    lines = ["G0 X0 Y0 Z20", "G0 X0 Y0 Z6", "G1 X0 Y0 Z5.5 F100"]
    moves = zmap.parse_gcode("G21 G90\n" + "\n".join(lines) + "\n")
    out = {}
    for tool, corner in (("ball", 3.0), ("flat", 0.0)):
        r = zmap.simulate(moves, PART, CELL, X0, Y0, STOCK, tool=tool,
                          dia=6.0, corner=corner, stock_init=st)
        out[tool] = r["entry_stock"]
    assert out["ball"]["count"] == 0, out["ball"]
    assert abs(out["ball"]["max_mm"] - (-0.3)) < 1e-9, out["ball"]
    assert out["flat"]["count"] == 1, out["flat"]
    want = float(rise[d <= 3.0 + 1e-9].max()) - 0.3   # the grid's outermost cell
    assert abs(out["flat"]["max_mm"] - want) < 1e-4, (want, out["flat"])


def test_level_traverse_then_helix_is_judged():
    """(f) a level G0 straight to the helix start (no descent G0) is an
    entry too: the same inj3 shape reached by a traverse at Z6 fails."""
    lines = ["G0 X3 Y0 Z6"] + helix(0, 0, 3, 6, 3)
    r = run(lines, column_cleared(3, 0, 3.5, 5.0))
    es = r["entry_stock"]
    assert es["entries"] == 1 and es["count"] == 1, es
    assert abs(es["records"][0][5] - 4.0) < 1e-9, es


def test_parallel_equals_serial():
    lines = (["G0 X0 Y0 Z20", "G0 X3 Y0 Z11"] + helix(0, 0, 3, 11, 8)
             + ["G1 X0 Y0 Z8 F500", "G0 X0 Y0 Z20", "G0 X13 Y0 Z20",
                "G0 X13 Y0 Z6"]
             + helix(10, 0, 3, 6, 3) + ["G1 X10 Y0 Z3 F500"])
    st = column_cleared(13, 0, 3.5, 5.0)
    a, b = run(lines, st), run(lines, st, jobs=3)
    assert a["entry_stock"] == b["entry_stock"], (a["entry_stock"],
                                                  b["entry_stock"])
    assert a["entry_stock"]["count"] == 1


if __name__ == "__main__":
    for t in (test_helix_over_stock_passes, test_helix_under_standing_stock_fails,
              test_offset_side_entry_passes, test_ball_judged_at_its_surface,
              test_level_traverse_then_helix_is_judged, test_parallel_equals_serial):
        t()
        print("PASS", t.__name__)
