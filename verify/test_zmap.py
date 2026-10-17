"""Synthetic pytest suite for verify/zmap.py (no FreeCAD, no files)."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zmap  # noqa: E402

CELL = 0.5
X0 = Y0 = -25.0
N = 100  # grid covers [-25, 25] x [-25, 25]
STOCK = (-25.0, 25.0, -25.0, 25.0, 0.0, 10.0)


def centers():
    c = X0 + (np.arange(N) + 0.5) * CELL
    return c


def flat_part(band_top=5.0, top=10.0, band_halfwidth=3.0):
    """Part: a band of height band_top along X, otherwise `top`."""
    ys = centers()[:, None]
    return np.broadcast_to(np.abs(ys) <= band_halfwidth, (N, N)) * (band_top - top) + top


def block_part(hi=10.0, lo=0.0, half=15.0):
    xs = centers()[None, :]
    ys = centers()[:, None]
    return np.where((np.abs(xs) <= half) & (np.abs(ys) <= half), hi, lo)


def run(gcode, part, tool="flat", dia=6.0, corner=0.0):
    moves = zmap.parse_gcode(gcode)
    return zmap.simulate(moves, part, CELL, X0, Y0, STOCK, tool=tool,
                        dia=dia, corner=corner)


def test_flat_groove_width_and_depth():
    part = flat_part()
    res = run("""
( flat groove test )
N10 G21 G90 F500
N20 G0 X-20. Y0. Z20. ; rapid above stock
N30 G1 Z5. F100.
N40 G1 X20. F500.
""", part)
    stock = res["stock"]
    ys = centers()
    removed_cols = np.where((stock < 10.0 - 0.01).any(axis=1))[0]
    assert len(removed_cols) > 0
    width = (ys[removed_cols].max() - ys[removed_cols].min()) + CELL
    assert 5.0 <= width <= 7.0, "groove width %.2f not within one cell of 6" % width
    assert abs(stock.min() - 5.0) < 1e-6, "groove floor not at tip Z"
    assert res["gouges"]["count"] == 0
    assert res["leftover"]["max"] < 1e-6
    assert 0.0 < res["air_fraction"] < 0.5


def test_ball_profile_and_cusp():
    R = 3.0
    tip = 5.0
    part = flat_part(band_top=tip)
    ys = centers()

    # Single pass at y = 0: cross-section must match the circle.
    res = run("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. F500.
""", part, tool="ball", dia=2 * R)
    stock = res["stock"]
    i0 = int(np.argmin(np.abs(centers())))  # column nearest x = 0
    errs = []
    for yc in ys[np.abs(ys) <= R - CELL]:
        expected = tip + R - math.sqrt(R * R - yc * yc)
        errs.append(abs(stock[np.argmin(np.abs(ys - yc)), i0] - expected))
    assert max(errs) < 1e-3, "ball cross-section deviates: %g" % max(errs)
    assert res["gouges"]["count"] == 0

    # Two passes at stepover s = 3 -> cusp h = R - sqrt(R^2 - (s/2)^2).
    s = 3.0
    res2 = run("""
G21 G90 F500
G0 X-20. Y-1.5 Z20.
G1 Z5. F100.
G1 X20. Y-1.5 F500.
G0 X-20. Y-1.5 Z20.
G0 X-20. Y1.5 Z20.
G1 Z5. F100.
G1 X20. Y1.5 F500.
""", flat_part(band_top=tip, band_halfwidth=5.0), tool="ball", dia=2 * R)
    stock2 = res2["stock"]
    h = R - math.sqrt(R * R - (s / 2.0) ** 2)
    assert abs(h - 0.4019) < 1e-3
    errs2 = []
    for yc in ys[np.abs(ys) <= s / 2.0]:
        d = abs(abs(yc) - s / 2.0)
        expected = tip + R - math.sqrt(R * R - d * d)
        j = int(np.argmin(np.abs(ys - yc)))
        errs2.append(abs(stock2[j, i0] - expected))
    assert max(errs2) < 1e-3, "cusp profile deviates: %g" % max(errs2)
    # the cusp (max leftover between the two pass centers) sits at y ~ 0
    central = np.abs(ys) <= 0.3
    assert abs(stock2[central, i0].max() - (tip + R - math.sqrt(R * R - 1.25 ** 2))) < 1e-3
    assert res2["gouges"]["count"] == 0


def test_arc_groove_matches_radius():
    Rpath, Rtool = 10.0, 3.0
    xs = centers()[None, :]
    ys = centers()[:, None]
    r = np.hypot(xs, ys)
    part = np.where((r >= Rpath - Rtool) & (r <= Rpath + Rtool), 5.0, 10.0)

    res = run("""
G21 G90 F500
G0 X10. Y0. Z20.
G1 Z5. F100.
G3 X0. Y10. I-10. J0. F500.
""", part)
    stock = res["stock"]

    def dist_arc(px, py):
        rr = math.hypot(px, py)
        ang = math.atan2(py, px) % (2 * math.pi)
        if 0.0 <= ang <= math.pi / 2.0:
            return abs(rr - Rpath)
        return min(math.hypot(px - Rpath, py), math.hypot(px, py - Rpath))

    removed = stock < 10.0 - 0.01
    assert removed.any()
    # nothing removed outside the swept envelope (cell + chord margin)
    for j, i in zip(*np.where(removed)):
        d = dist_arc(centers()[i], centers()[j])
        assert d <= Rtool + 0.75, "removed cell at dist %.2f" % d
    # everything well inside the envelope is removed
    for j, i in zip(*np.where(~removed)):
        d = dist_arc(centers()[i], centers()[j])
        assert d >= Rtool - 0.75, "missed cell at dist %.2f" % d
    # radial edges of the groove land on R +/- Rtool
    rr_removed = r[removed]
    assert abs(rr_removed.min() - (Rpath - Rtool)) <= 0.75
    assert abs(rr_removed.max() - (Rpath + Rtool)) <= 0.75


def test_gouge_detection():
    part = block_part(hi=10.0, half=15.0)
    bad = run("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z8. F100.
G1 X20. Y0. F500.
""", part)
    assert bad["gouges"]["count"] > 0
    assert abs(bad["gouges"]["max_depth"] - 2.0) < 1e-6
    wx, wy = bad["gouges"]["worst_xy"]
    assert abs(wy) <= 3.0 + CELL  # groove crosses y ~ 0
    good = run("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z10. F100.
G1 X20. Y0. F500.
""", part)
    assert good["gouges"]["count"] == 0


def test_rapid_collision_and_units():
    part = block_part(hi=10.0, half=15.0)
    res = run("""
G21 G90 F500
G0 Z20.
G0 X-20. Y0. Z5.
G1 X20. Y0. F500.
""", part)
    assert res["rapid_collisions"]["count"] == 1
    # line 1 is blank (leading newline of the triple-quoted block)
    assert res["rapid_collisions"]["first_line"] == 4

    moves = zmap.parse_gcode("G20 G90\nG1 X1.0 Y0.5 Z-0.5 F100\n")
    assert len(moves) == 1
    assert abs(moves[0]["x"] - 25.4) < 1e-9
    assert abs(moves[0]["y"] - 12.7) < 1e-9
    assert abs(moves[0]["z"] + 12.7) < 1e-9


def pocket_part(floor=4.0, top=10.0, half=12.0, block=20.0):
    """Part: block of `top` (footprint |x|,|y| <= block) with a pocket of
    `floor` in the middle; outside the footprint = 0 (no part)."""
    xs = centers()[None, :]
    ys = centers()[:, None]
    in_block = (np.abs(xs) <= block) & (np.abs(ys) <= block)
    in_pocket = (np.abs(xs) <= half) & (np.abs(ys) <= half)
    return np.where(in_pocket, floor, np.where(in_block, top, 0.0))


def test_stock_chain_simulate_equivalence():
    """Chaining stage1 -> stock_init(stage1) -> stage2 must equal one sim."""
    part = pocket_part()
    stage1 = """
G21 G90 F500
G0 X-8. Y0. Z20.
G1 Z6. F100.
G1 X8. F500.
"""
    stage2 = """
G21 G90 F500
G0 X-4. Y0. Z20.
G1 Z4.5 F100.
G1 X4. F500.
"""
    combined = run(stage1 + stage2, part)
    s1 = run(stage1, part)
    chained = zmap.simulate(zmap.parse_gcode(stage2), part, CELL, X0, Y0,
                           STOCK, stock_init=s1["stock"])
    assert np.array_equal(combined["stock"], chained["stock"])
    # the saved state really was applied: alone, stage2 leaves the outer band
    # at stock top; chained it sits at stage1's depth
    alone = run(stage2, part)
    assert not np.array_equal(alone["stock"], chained["stock"])

    # a gouge made in stage 1 persists into the chained stage-2 report
    s1_gouge = run(stage1.replace("Z6.", "Z3.5."), part)
    assert s1_gouge["gouges"]["count"] > 0
    assert abs(s1_gouge["gouges"]["max_depth"] - 0.5) < 1e-6
    s2_after = zmap.simulate(zmap.parse_gcode(stage2), part, CELL, X0, Y0,
                             STOCK, stock_init=s1_gouge["stock"])
    assert s2_after["gouges"]["count"] > 0


def test_stock_chain_cli(tmp_path):
    """--stock-out / --stock-in round trip through the CLI."""
    import json
    part = pocket_part()
    hf = tmp_path / "part.npy"
    np.save(hf, part)
    with open(str(hf).replace(".npy", ".json"), "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0}, f)
    g1 = tmp_path / "s1.ngc"
    g2 = tmp_path / "s2.ngc"
    g1.write_text("""
G21 G90 F500
G0 X-8. Y0. Z20.
G1 Z6. F100.
G1 X8. F500.
""")
    g2.write_text("""
G21 G90 F500
G0 X-4. Y0. Z20.
G1 Z4.5 F100.
G1 X4. F500.
""")
    out1 = tmp_path / "stock1.npy"
    out2 = tmp_path / "stock2.npy"
    j1 = tmp_path / "r1.json"
    j2 = tmp_path / "r2.json"
    stock_args = ["--stock"] + [str(v) for v in STOCK]
    assert zmap.main([str(g1), "--part", str(hf)] + stock_args
                    + ["--stock-out", str(out1), "--out-json", str(j1)]) == 0
    assert out1.exists()
    assert zmap.main([str(g2), "--part", str(hf)] + stock_args
                     + ["--stock-in", str(out1), "--stock-out", str(out2),
                        "--out-json", str(j2)]) == 0

    combined_g = tmp_path / "comb.ngc"
    combined_g.write_text(g1.read_text() + g2.read_text())
    jc = tmp_path / "rc.json"
    assert zmap.main([str(combined_g), "--part", str(hf)] + stock_args
                     + ["--out-json", str(jc)]) == 0

    chained = np.load(str(out2))
    combined_stock = zmap.simulate(zmap.parse_gcode(combined_g.read_text()),
                                  part, CELL, X0, Y0, STOCK)["stock"]
    assert np.array_equal(chained, combined_stock)

    # --stock can be omitted when --stock-in provides the state
    j3 = tmp_path / "r3.json"
    assert zmap.main([str(g2), "--part", str(hf), "--stock-in", str(out1),
                      "--out-json", str(j3)]) == 0
    with open(str(j3)) as f:
        rep = json.load(f)
    assert rep["stock_in"] == str(out1)
