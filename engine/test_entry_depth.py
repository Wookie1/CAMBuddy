#!/usr/bin/env python3
"""FE5 step 0 unit tests for engine/entry_depth.py (numpy only).
Run: python3 engine/test_entry_depth.py  (pytest-compatible)."""
import math
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from engine import entry_depth as ed  # noqa: E402


def test_resample_never_lower():
    rng = np.random.default_rng(7)
    A = rng.uniform(5.0, 40.0, size=(23, 31))
    A[3, 4] = np.nan  # a no-data cell (outside the part outline)
    x0, y0, cell = -11.3, -7.2, 0.5
    F = ed.resample_fine(A, x0, y0, cell, 0.1)
    ny, nx = A.shape
    assert F.shape == (int(round(ny * cell / 0.1)),
                       int(round(nx * cell / 0.1)))
    # every fine cell inside a finite source cell is >= that source value
    bad = 0
    for j in range(1, ny - 1):
        for i in range(1, nx - 1):
            if not np.isfinite(A[j, i]):
                continue
            jj = int(round((y0 + (j + 0.5) * cell - y0) / 0.1))
            ii = int(round((x0 + (i + 0.5) * cell - x0) / 0.1))
            if F[jj, ii] < A[j, i] - 1e-9:
                bad += 1
    assert bad == 0, "%d fine cells below source" % bad


def test_parse_modal():
    txt = ("%\nO1002\n(T cmt)\nG90 G94 G17 G49 G40 G80\nG21\n"
           "G53 G00 Z0.\nT20 M06\nS7500 M3\nG04 P3000\nG54\nM8\n"
           "G00 X1.0 Y2.0\nG43 Z9.0 H20\nG00\nZ5.0\n"
           "G01 Z3.0 F1270.\nX2.0 Y2.0 F3429.\nX3.0\n"
           "G00 X9.0 Y9.0\nZ5.0\nG49\nG28 G91 X0. Y0.\nG90\nM30\n%\n")
    with tempfile.NamedTemporaryFile("w", suffix=".nc", delete=False) as fh:
        fh.write(txt)
        p = fh.name
    mv = ed.parse_nc(p)
    os.unlink(p)
    got = [(m["g"], m["x"], m["y"], m["z"]) for m in mv]
    want = [(0, 1.0, 2.0, 5.0), (1, 1.0, 2.0, 3.0), (1, 2.0, 2.0, 3.0),
            (1, 3.0, 2.0, 3.0), (0, 9.0, 9.0, 3.0), (0, 9.0, 9.0, 5.0)]
    assert got == want, got


def test_plunge_depth_and_stamp():
    # flat stock top 10.0, ball R=3; plunge to z=8 -> depth 2.0
    A = np.full((40, 40), 10.0)
    live = ed.LiveStock(A, 0.0, 0.0, 0.5, 3.0)
    moves = [{"g": 0, "x": 5.0, "y": 5.0, "z": 12.0, "line": 1},
             {"g": 1, "x": 5.0, "y": 5.0, "z": 8.0, "line": 2},
             {"g": 1, "x": 8.0, "y": 5.0, "z": 8.0, "line": 3}]
    e = ed.estimate_entries(moves, live)
    assert len(e) == 1 and abs(e[0]["depth_mm"] - 2.0) < 0.01, e
    # after the pass cut at z=8, a later plunge to z=9 removes nothing
    moves2 = [{"g": 0, "x": 5.0, "y": 5.0, "z": 12.0, "line": 4},
              {"g": 1, "x": 5.0, "y": 5.0, "z": 9.0, "line": 5}]
    e2 = ed.estimate_entries(moves2, live)
    assert len(e2) == 1 and e2[0]["depth_mm"] <= 1e-9, e2


def test_terrace_and_fail_closed():
    # left half stock 10, right half machined to 6; plunge onto the step
    A = np.tile(np.where(np.arange(40) < 20, 10.0, 6.0), (40, 1))
    live = ed.LiveStock(A, 0.0, 0.0, 0.5, 3.0)
    # entry at x=10.0 (step line at x=10): the disk sees the 10.0 terrace
    d = live.disk_depth(10.0, 2.5, 8.0)
    assert abs(d - 2.0) < 0.01, d        # conservative: terrace counted
    # far outside the grid -> cannot tell -> DEEP (fail closed)
    assert math.isinf(live.disk_depth(500.0, 500.0, 8.0))


def test_g0_does_not_cut():
    A = np.full((20, 20), 10.0)
    live = ed.LiveStock(A, 0.0, 0.0, 0.5, 2.0)
    moves = [{"g": 0, "x": 2.5, "y": 2.5, "z": 10.5, "line": 1},
             {"g": 0, "x": 2.5, "y": 2.5, "z": 7.0, "line": 2},
             {"g": 0, "x": 2.5, "y": 2.5, "z": 10.5, "line": 3}]
    e = ed.estimate_entries(moves, live)
    assert e == []                          # rapids: no feed entry, no cut
    assert live.disk_depth(2.5, 2.5, 10.5) <= 0.0


def test_domain_pass_starts_and_steep_inpass():
    # FE5 (a) domain: every pass-start descent INCLUDING down-link drops is
    # scored; in-pass descents steeper than 15 deg are scored; in-pass
    # descents <= 15 deg must NOT be scored (ZB does not score them)
    A = np.full((40, 40), 10.0)
    live = ed.LiveStock(A, 0.0, 0.0, 0.5, 2.0)
    txt = [
        {"g": 0, "x": 2.5, "y": 5.5, "z": 12.0, "line": 1},   # air
        {"g": 1, "x": 2.5, "y": 5.5, "z": 9.0, "line": 2},    # pass-start vertical plunge -> scored
        {"g": 1, "x": 5.5, "y": 5.5, "z": 8.5, "line": 3},    # in-pass ~9.5 deg -> NOT scored
        {"g": 1, "x": 6.5, "y": 5.5, "z": 7.0, "line": 4},    # in-pass ~56 deg -> scored
        {"g": 1, "x": 8.5, "y": 5.5, "z": 7.0, "line": 5},    # horizontal -> not scored
        {"g": 1, "x": 8.5, "y": 5.5, "z": 5.0, "line": 6},    # down-link drop -> scored
        {"g": 0, "x": 12.5, "y": 5.5, "z": 12.0, "line": 7},  # rapid
        {"g": 1, "x": 14.5, "y": 5.5, "z": 11.8, "line": 8},  # shallow pass-start descent -> scored (pass start)
    ]
    e = ed.estimate_entries(txt, live)
    got = sorted(x["line"] for x in e)
    assert got == [2, 4, 6, 8], "scored lines %s (line 3 must not be scored; line 6 down-link drop must be scored)" % got
    by = {x["line"]: x for x in e}
    assert abs(by[2]["depth_mm"] - 1.0) < 0.05, by[2]
    # line 5 (horizontal at z7.0) stamps the centre top to 7.0 BEFORE the
    # drop, so the conservative depth at line 6 is 7.0-5.0 = 2.0 mm exactly
    assert abs(by[6]["depth_mm"] - 2.0) < 0.05, by[6]


def test_flat_chord_capsule_coverage():
    # FE5 RESUME: stamp_flat_chord must cover the FULL capsule (segment +
    # end caps): a cell is covered iff its TRUE distance to the SEGMENT is
    # <= R. Cells past a chord's ends (inside the bbox window, perp <= R)
    # must NOT inherit the end-point z. Fails on the old perp2-only mask.
    R, f = 5.0, 0.1
    A = np.full((400, 400), 10.0)
    for a, b in (((10.0, 10.0, 2.0), (30.0, 10.0, 2.0)),      # along X
                 ((10.0, 10.0, 2.0), (24.0, 24.0, 2.0))):       # 45 deg
        live = ed.LiveStock(A.copy(), 0.0, 0.0, f, R, fine=f)
        live.stamp_flat_chord(a, b)
        k = live.kR + 1
        L = live.L[k:-k, k:-k]
        c = (np.arange(400) + 0.5) * f
        dx = c[None, :] - a[0]
        dy = c[:, None] - a[1]
        vx, vy = b[0] - a[0], b[1] - a[1]
        Lxy = math.hypot(vx, vy)
        ux, uy = vx / Lxy, vy / Lxy
        spc = np.clip(dx * ux + dy * uy, 0.0, Lxy)
        dist = np.hypot(dx - ux * spc, dy - uy * spc)
        perp2 = (dx * uy - dy * ux) ** 2
        inside = dist <= R - 0.02
        outside = dist >= R + 0.02
        assert inside.any() and outside.any()
        # every cell inside the capsule is lowered to the chord bottom 2.0
        assert np.all(np.abs(L[inside] - 2.0) < 1e-9), \
            "%d inside cells not cut" % int((~(np.abs(L - 2.0) < 1e-9)
                                              & inside).sum())
        # every cell outside (end caps included) is untouched
        assert np.all(L[outside] == 10.0), \
            "%d cells OUTSIDE the capsule were stamped" \
            % int((L[outside] != 10.0).sum())
        # the old perp2-only bbox mask WOULD have stamped past-the-end
        # cells: this region must be non-empty for the test to bite
        past = (outside & (perp2 <= R * R)).sum()
        assert past > 0, "test must exercise past-the-end cells"


def test_with_radius_same_grid():
    # FE5 regression: with_radius() shares the padded live grid of a BIGGER
    # ball; the window indexing must keep the ORIGINAL pad - re-deriving it
    # from the smaller radius shifted every read/write by ~3.2 mm (rest
    # scored the wrong stock). A cut made by the big ball must be VISIBLE
    # to the small ball at the SAME XY, and stamps must land in place.
    R, r, f = 4.7625, 1.571, 0.1
    A = np.full((800, 800), 10.0)
    live = ed.LiveStock(A, 40.0, 40.0, f, R)
    live.stamp_chord((43.0, 43.0, 8.0), (43.0, 43.0, 5.0))  # plunge cut
    small = live.with_radius(r)
    d = small.disk_depth(43.0, 43.0, 6.0)
    assert d < 0.0, "small ball cannot see the big ball's cut at its own " \
                    "footprint (indexing shifted?): depth %.3f" % d
    # a small plunge on a FRESH grid cuts exactly there, not 3 mm away
    live2 = ed.LiveStock(A.copy(), 40.0, 40.0, f, R)
    small2 = live2.with_radius(r)
    small2.stamp_chord((43.0, 43.0, 6.0), (43.0, 43.0, 5.4))
    qk = live2.pad
    ci = int((43.0 - 40.0) / f) + qk
    cj = int((43.0 - 40.0) / f) + qk
    centre = float(live2.L[cj, ci])
    # cell centre is 0.07 mm off the axis: floor = 5.4 + r - sqrt(r^2-d^2)
    assert 5.4 <= centre < 5.405, centre
    far = float(live2.L[cj, ci + int(2.0 / f)])
    assert far > 9.99, "stamp landed off-grid: 2 mm cell %.3f" % far


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("ALL ENTRY_DEPTH TESTS PASSED")
