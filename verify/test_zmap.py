"""Synthetic pytest suite for verify/zmap.py (no FreeCAD, no files)."""
import json
import math
import os
import sys

import numpy as np
import pytest

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
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    g1 = tmp_path / "s1.ngc"
    g2 = tmp_path / "s2.ngc"
    g1.write_text("""
G21 G90 F500
G0 X-22. Y0. Z20.
G1 Z10. F100.
G1 X-4. Y0. Z6. F100.
G1 X8. F500.
""")
    g2.write_text("""
G21 G90 F500
G0 X-22. Y0. Z20.
G1 Z10. F100.
G1 X0. Y0. Z4.5 F100.
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


# ---------------------------------------------------------------------------
# Plane-aware arcs (G17/G18/G19, I/J/K) and cutter compensation reporting
# ---------------------------------------------------------------------------

def test_parse_g18_arc_with_k():
    moves = zmap.parse_gcode(
        "G21 G90\nG18 G02 X10. Z5. I2. K-3. F100\nG17\n")
    assert len(moves) == 1
    mv = moves[0]
    assert mv["motion"] == "G2"
    assert mv["plane"] == 18
    assert abs(mv["i"] - 2.0) < 1e-12
    assert abs(mv["k"] + 3.0) < 1e-12
    assert abs(mv["j"]) < 1e-12


def test_g18_arc_interpolated_in_xz_plane():
    """A G18 XZ arc bulges 5 mm below its chord; chord-only (or XY-arc)
    handling would miss the gouge entirely (chord stays at part top)."""
    # footprint filter needs relief: block of top=10 over lo=0
    part = block_part(hi=10.0, lo=0.0, half=15.0)
    res = run("""
G21 G90 F500
G0 X-5. Y0. Z10.
G18 G02 X5. Z10. I5. K0. F100.
G17
""", part, tool="flat", dia=6.0)
    assert res["gouges"]["count"] > 0
    assert abs(res["gouges"]["max_depth"] - 5.0) < 0.2
    wx, wy = res["gouges"]["worst_xy"]
    assert math.hypot(wx, wy) <= 3.0 + CELL  # dip at (x=0, y=0)
    # the arc must not sweep an XY circle: removal stays near y = 0
    removed = np.isfinite(res["stock"]) & (res["stock"] < 10.0 - 0.02)
    ys = centers()[np.where(removed.any(axis=1))[0]]
    assert ys.max() - ys.min() <= 6.0 + 2 * CELL


def test_g19_arc_interpolated_in_yz_plane():
    """G19 YZ arc (J/K): moves Y and Z, X stays put; dips 5 mm below top."""
    part = block_part(hi=10.0, lo=0.0, half=15.0)
    res = run("""
G21 G90 F500
G0 X0. Y-5. Z10.
G19 G03 Y5. Z10. J5. K0. F100.
G17
""", part, tool="flat", dia=6.0)
    assert res["gouges"]["count"] > 0
    assert abs(res["gouges"]["max_depth"] - 5.0) < 0.2
    wx, wy = res["gouges"]["worst_xy"]
    assert math.hypot(wx, wy) <= 3.0 + CELL  # dip at (x=0, y=0)
    removed = np.isfinite(res["stock"]) & (res["stock"] < 10.0 - 0.02)
    xs = centers()[np.where(removed.any(axis=0))[0]]
    assert xs.max() - xs.min() <= 6.0 + 2 * CELL  # stays near x = 0


def test_parallel_rapid_collisions_exact():
    """--jobs chunking must report the SAME rapid collisions as serial.

    Regression for the rapid-dive artifact: a rapid descending into material
    already removed by an earlier chunk used to be a false collision (chunks
    started from fresh stock). Now chunks re-run with the prefix stock of all
    earlier chunks (two-pass), so false positives are gone and real collisions
    are still caught.
    """
    part = pocket_part(floor=4.0, top=10.0, half=12.0, block=20.0)
    gcode = """
G21 G90 F500
G0 X-8. Y0. Z20.
G1 Z6. F100.
G1 X8. F500.
G0 Z20.
G0 X0. Y0.
G0 Z7.
G0 Z20.
G0 X0. Y18.
G0 Z5.
"""
    moves = zmap.parse_gcode(gcode)
    seq = zmap.simulate(moves, part, CELL, X0, Y0, STOCK, tool="flat",
                        dia=6.0)
    # serial truth: the Z7 rapid over the cut groove is air; the Z5 rapid at
    # (0,18) descends 5 mm into uncut block top -> exactly one collision
    assert seq["rapid_collisions"]["count"] == 1
    for jobs in (2, 4, 7):
        par = zmap.simulate_parallel(moves, part, CELL, X0, Y0, STOCK, jobs,
                                    tool="flat", dia=6.0)
        assert par["rapid_collisions"]["count"] == 1, \
            "jobs=%d: %d collisions != serial 1" % (
                jobs, par["rapid_collisions"]["count"])
        assert par["rapid_collisions"]["first_line"] == \
            seq["rapid_collisions"]["first_line"]
        assert np.array_equal(par["stock"], seq["stock"])


def test_parallel_rapid_collisions_stock_init_chain():
    """Prefix-stock fix must also hold when the parallel sim continues from a
    saved stock state (--stock-in)."""
    part = pocket_part(floor=4.0, top=10.0, half=12.0, block=20.0)
    stage1 = """
G21 G90 F500
G0 X-8. Y0. Z20.
G1 Z6. F100.
G1 X8. F500.
"""
    stage2 = """
G21 G90 F500
G0 Z20.
G0 X0. Y0.
G0 Z7.
G0 Z20.
G0 X0. Y18.
G0 Z5.
"""
    s1 = zmap.simulate(zmap.parse_gcode(stage1), part, CELL, X0, Y0, STOCK,
                       tool="flat", dia=6.0)
    moves = zmap.parse_gcode(stage2)
    seq = zmap.simulate(moves, part, CELL, X0, Y0, STOCK, tool="flat",
                       dia=6.0, stock_init=s1["stock"])
    assert seq["rapid_collisions"]["count"] == 1  # only the (0,18) Z5 rapid
    par = zmap.simulate_parallel(moves, part, CELL, X0, Y0, STOCK, 3,
                                tool="flat", dia=6.0, stock_init=s1["stock"])
    assert par["rapid_collisions"]["count"] == 1
    assert np.array_equal(par["stock"], seq["stock"])


def test_leading_xy_rapid_z_unknown_matches_serial():
    """A leading XY-only rapid before the first Z word = Z unknown, above
    stock -- NOT machine 0.

    Regression for the posted op-header shape (G00 X.. Y.. then G43 Z.. H..):
    resolving the leading rapid's Z to 0 made chunked (--jobs>1) sims register a
    phantom dive through the stock that serial (which starts from the first real
    Z) does not see. resolve_moves now defaults unknown leading Z to the first
    explicit Z, so jobs must agree with serial exactly.
    """
    part = block_part(hi=10.0, half=15.0)
    gcode = """
G21 G90
G53 G00 Z0.
T3 M06
S7500 M03
G04 P3000
G54
M08
G00 X-20. Y0.
G43 Z20. H03
G00 Z15.
G01 Z5. F100.
G01 X20. F500.
"""
    moves = zmap.parse_gcode(gcode)
    seq = zmap.simulate(moves, part, CELL, X0, Y0, STOCK, tool="flat",
                       dia=6.0)
    # the XY rapid precedes any Z word: it is NOT a dive to Z0 inside the
    # stock, and the rapids that follow stay above the 10 mm stock top
    assert seq["rapid_collisions"]["count"] == 0
    for jobs in (2, 4):
        par = zmap.simulate_parallel(moves, part, CELL, X0, Y0, STOCK, jobs,
                                     tool="flat", dia=6.0)
        assert par["rapid_collisions"]["count"] == \
            seq["rapid_collisions"]["count"], \
            "jobs=%d: %d rapid collisions != serial %d (phantom dive)" % (
                jobs, par["rapid_collisions"]["count"],
                seq["rapid_collisions"]["count"])
        assert np.array_equal(par["stock"], seq["stock"])
        assert par["gouges"]["count"] == seq["gouges"]["count"]


def test_over_flute_flag_and_zband_lengths():
    """--flute: cutting moves whose tip is deeper than flute below the local
    stock surface (at that XY) are counted with the first line; default off.
    cutting_length_by_zband splits cutting length into 5 mm tip-Z bands."""
    part = np.full((N, N), 0.0)  # no part: isolates the flute/band metrics
    sb = (-25.0, 25.0, -25.0, 25.0, 0.0, 40.0)
    gcode = """
G21 G90 F500
G0 X-10. Y0. Z50.
G1 Z10. F100.
G1 X10. F500.
G0 Z50.
G1 X-10. Y5. Z8. F100.
G1 X10. Y5. F500.
"""
    moves = zmap.parse_gcode(gcode)
    res = zmap.simulate(moves, part, CELL, X0, Y0, sb, tool="flat", dia=6.0,
                       flute=25.0)
    # line 4 plunge 50->10 into surface 40 (depth 30 > 25), line 5 traverse
    # at Z10 through still-40 material (30), the diagonal plunge ending at
    # Z8 and the y=5 traverse at Z8 (32): all over-flute = 4 moves
    assert res["plunge_over_flute"]["count"] == 4
    assert res["plunge_over_flute"]["first_line"] == 4
    assert res["plunge_over_flute"]["flute_mm"] == 25.0
    off = zmap.simulate(moves, part, CELL, X0, Y0, sb, tool="flat", dia=6.0)
    assert off["over_flute"] is None
    assert off["plunge_over_flute"] is None
    # a floor cut riding its own groove is NOT over-flute: the y=0 strip was
    # cut to Z10 above, so a Z9 re-pass there sees surface 10 (depth 1)
    res2 = zmap.simulate(zmap.parse_gcode(gcode + """
G0 Z50.
G1 X-10. Y0. Z9. F100.
G1 X10. Y0. F500.
"""), part, CELL, X0, Y0, sb, tool="flat", dia=6.0, flute=25.0)
    assert res2["plunge_over_flute"]["count"] == 4  # no new flags: depth 1 < 25

    zb = res["cutting_length_by_zband"]
    assert abs(sum(zb.values()) - res["cutting_length_mm"]) < 0.5
    assert zb.get("30-35", 0.0) >= 39.0  # the 40 mm plunge, mid-Z 30
    assert zb.get("10-15", 0.0) >= 19.0  # traverse at Z10
    assert zb.get("5-10", 0.0) >= 19.0   # traverse at Z8

    par = zmap.simulate_parallel(moves, part, CELL, X0, Y0, sb, 2,
                                tool="flat", dia=6.0, flute=25.0)
    assert par["plunge_over_flute"]["count"] == 4
    assert par["plunge_over_flute"]["first_line"] == 4
    assert abs(sum(par["cutting_length_by_zband"].values())
               - sum(zb.values())) < 0.5


def test_shank_over_flute_wall():
    """--flute + default shank dia: a ball riding tangent to a deep wall has
    its SHANK (z > tip + F within S/2 of the centre) rub the wall. over_flute
    reports cutting moves with such a hit, the max excess above the flute top
    and where; the plunge counter stays separate as plunge_over_flute."""
    cell, n, x0 = 0.1, 100, -5.0

    def run_shank(xc, top, shank=None, dia=6.0, jobs=None):
        xs = (x0 + (np.arange(n) + 0.5) * cell)[None, :]
        part = np.broadcast_to(np.where(xs >= 0.0, top, 0.0), (n, n)).copy()
        sb = (-5.0, 5.0, -5.0, 5.0, 0.0, float(top))
        gcode = ("G21 G90 F500\n"
                "G0 X%.1f Y-3. Z%.1f\n" % (xc, top + 8.0) +
                "G1 Z0. F100.\n" +
                "G1 X%.1f Y3. F500.\n" % (xc,))
        moves = zmap.parse_gcode(gcode)
        if jobs:
            return zmap.simulate_parallel(moves, part, cell, x0, -5.0, sb,
                                         jobs, tool="ball", dia=dia,
                                         flute=15.0, shank_dia=shank)
        return zmap.simulate(moves, part, cell, x0, -5.0, sb, tool="ball",
                            dia=dia, flute=15.0, shank_dia=shank)

    # (a) ball R3 exactly tangent to a 22 mm wall: flute top at Z15, wall
    #     reaches 22 -> shank rubs with ~7 mm excess on plunge and traverse
    res = run_shank(-3.0, 22.0)
    assert res["over_flute"]["count"] == 2
    assert abs(res["over_flute"]["max_depth"] - 7.0) < 0.2
    wx, wy = res["over_flute"]["worst_xy"]
    assert -0.1 <= wx <= 0.2 and abs(wy) <= 3.5  # worst cell is at the wall
    assert res["over_flute"]["first_line"] == 3   # the plunge move
    # old centre-based counter kept separately
    assert res["plunge_over_flute"]["count"] >= 1
    assert res["plunge_over_flute"]["flute_mm"] == 15.0

    # (b) same tangent path, wall only 10 mm high (< tip + F): no shank hit
    res_b = run_shank(-3.0, 10.0)
    assert res_b["over_flute"]["count"] == 0
    assert res_b["over_flute"]["max_depth"] == 0.0
    assert res_b["over_flute"]["worst_xy"] is None

    # (c) far from the wall: nothing within S/2 above the flute top
    res_c = run_shank(-10.0, 22.0)
    assert res_c["over_flute"]["count"] == 0

    # (d) necked shank S=2 < D=6: radius 1 can no longer reach the wall
    res_d = run_shank(-3.0, 22.0, shank=2.0)
    assert res_d["over_flute"]["count"] < res["over_flute"]["count"]

    # parallel combines count, depth and worst xy identically
    par = run_shank(-3.0, 22.0, jobs=2)
    assert par["over_flute"]["count"] == res["over_flute"]["count"]
    assert abs(par["over_flute"]["max_depth"]
               - res["over_flute"]["max_depth"]) < 1e-9
    assert par["over_flute"]["worst_xy"] == res["over_flute"]["worst_xy"]
    assert par["over_flute"]["first_line"] == res["over_flute"]["first_line"]


def test_cutter_comp_reporting():
    """G41/G42 moves are counted and reported; G40 line is not comp-active."""
    part = np.full((N, N), 10.0)
    res = run("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z12. F100.
G1 G41 X-10. Y-5. D03
G1 X10. Y-5.
G1 X10. Y5.
G1 G40 X-10. Y5.
G0 Z20.
""", part)
    cc = res["cutter_comp"]
    assert cc["active_moves"] == 3  # activation + 2 interior, cancel excluded
    assert cc["d_registers"] == [3]
    assert cc["first_line"] < cc["last_line"]


def test_cutter_comp_radius_offset():
    """CCW circular contour R12 with a R3 tool: as-programmed the edge
    reaches R15 and cuts into the pocket wall (floor R14.5 at Z 4, block
    top 10); with registry comp R3 the path offsets inward and nothing
    gouges."""
    xs = centers()[None, :]
    ys = centers()[:, None]
    r = np.hypot(xs, ys)
    part = np.where(r <= 14.5, 4.0, np.where(r <= 18.0, 10.0, 0.0))
    gcode = """
G21 G90 F500
G0 X6. Y0. Z20.
G1 Z4. F100.
G1 G41 X12. Y0. D01
G3 X12. Y0. I-12. J0. F500.
G1 G40 X6. Y0.
"""
    plain = run(gcode, part, tool="flat", dia=6.0)
    assert plain["gouges"]["count"] > 0  # wear model cuts the wall

    gcode = """
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z4. F100.
G1 G41 X6. Y-6. D01
G3 X12. Y0. I0. J6. F500.
G3 X12. Y0. I-12. J0.
G3 X6. Y6. I-6. J0.
G1 G40 X0. Y0.
"""
    moves = zmap.apply_cutter_comp(zmap.resolve_moves(zmap.parse_gcode(gcode)),
                                   3.0)
    # G41 left of a CCW loop offsets inward: contour R12 -> arc R9, and the
    # compensated centre path stays inside R9 + lead points
    sec = [m for m in moves if m.get("comp")]
    arcs = [m["arc"] for m in sec if m.get("arc")]
    assert any(abs(a[4] - 9.0) < 1e-9 for a in arcs)
    assert all(math.hypot(m["x"], m["y"]) <= 9.0 + 1e-6 for m in sec)
    res = zmap.simulate(moves, part, CELL, X0, Y0, STOCK, tool="flat",
                       dia=6.0)
    assert res["gouges"]["count"] == 0
    # the pocket floor really got cut along the compensated path
    assert res["stock"].min() <= 4.0 + 1e-9


# ---------------------------------------------------------------------------
# Synthetic vertical wall (analytic heightfield, 0.1 mm cells)
# ---------------------------------------------------------------------------

def wall_part(cell=0.1, n=100, x0=-5.0, top=10.0, floor=0.0):
    """Analytic vertical wall: part = top for x >= 0, floor for x < 0."""
    xs = (x0 + (np.arange(n) + 0.5) * cell)[None, :]
    return np.broadcast_to(np.where(xs >= 0.0, top, floor), (n, n)).copy()


def test_vertical_wall_ball_gouge():
    """Ball tangent to a vertical wall face (tip at floor) gouges nothing;
    the same path shifted 0.05 mm into the wall is flagged with depth > 0."""
    cell, n, x0 = 0.1, 100, -5.0
    part = wall_part(cell=cell, n=n, x0=x0)
    R = 1.0
    sb = (-5.0, 5.0, -5.0, 5.0, 0.0, 10.0)

    def run_wall(xc):
        gcode = "G21 G90 F500\nG0 X%.4f Y-3. Z20.\nG1 Z0. F100.\n" \
                "G1 X%.4f Y3. F500.\n" % (xc, xc)
        moves = zmap.parse_gcode(gcode)
        return zmap.simulate(moves, part, cell, x0, -5.0, sb, tool="ball",
                            dia=2 * R)

    # (a) path exactly R from the wall face (x = -R): ball tangent -> no gouge
    res_a = run_wall(-R)
    assert res_a["gouges"]["count"] == 0, \
        "tangent ball gouged %d cells" % res_a["gouges"]["count"]

    # (b) same path 0.05 mm into the wall: flagged with positive depth
    res_b = run_wall(-R + 0.05)
    assert res_b["gouges"]["count"] > 0, "intruding ball not flagged"
    assert res_b["gouges"]["max_depth"] > 0.0


# ---------------------------------------------------------------------------
# Engagement spikes and plunge detection (TASK_V1 items 1-4)
# ---------------------------------------------------------------------------

def _run_engage(gcode, part, dia=6.0, engage_max=None, ramp_angle=3.0,
                stock=None, tool="flat", stock_init=None):
    """Run simulate with engagement tracking."""
    if stock is None:
        stock = STOCK
    moves = zmap.parse_gcode(gcode)
    return zmap.simulate(moves, part, CELL, X0, Y0, stock, tool=tool,
                         dia=dia, engage_max=engage_max,
                         ramp_angle=ramp_angle, stock_init=stock_init)


def test_engagement_full_width_slot_flagged():
    """Straight full-width slot: engagement = D (tool diameter), flagged."""
    part = block_part(hi=10.0, half=15.0)
    # Cut a straight slot at full width (single pass, no stepover)
    res = _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=5.0)
    # engagement should be ~6 mm (full tool diameter)
    assert res["engagement"] is not None
    assert res["engagement"]["count"] >= 1, "full-width slot not flagged"
    assert res["engagement"]["max_mm"] >= 5.5, \
        "engagement %.3f < 5.5 for full-width slot" % res["engagement"]["max_mm"]
    # spikes should carry line, XY, and engagement_mm
    spike = res["engagement"]["spikes"][0]
    assert "line" in spike and "x" in spike and "y" in spike
    assert "engagement_mm" in spike and spike["engagement_mm"] >= 5.0


def test_engagement_corner_spike():
    """90-degree inside corner of a constant radial-engagement path:
    spike flagged at the corner."""
    part = block_part(hi=10.0, half=15.0)
    # Light stepover path (half-width engagement ~3 mm) with a sharp corner
    res = _run_engage("""
G21 G90 F500
G0 X-10. Y-3. Z20.
G1 Z5. F100.
G1 X10. Y-3. F500.
G1 X10. Y3. F500.
G1 X-10. Y3. F500.
""", part, dia=6.0, engage_max=4.0)
    # The corner (X10, Y-3) -> (X10, Y3) has higher engagement because the
    # tool enters fresh material on the inside corner
    assert res["engagement"] is not None
    # At least the corner move should be flagged (engagement > 4 mm)
    assert res["engagement"]["count"] >= 1, \
        "corner spike not flagged: count=%d max=%.3f" % (
            res["engagement"]["count"], res["engagement"]["max_mm"])


def test_engagement_side_cut_stepover_1_5():
    """Side cut with 1.5 mm of stock under one side of the tool (rest
    already cleared): engagement reads the cut band (~1.5), not 2R."""
    part = block_part(hi=10.0, half=15.0)
    ys = centers()[:, None]
    # pre-cleared to Z5 everywhere except material at y >= 1.5 (height 10);
    # tool at Y0 R3 cuts the band y in [1.5, 3.0] -> chord ~1.5 mm
    stock_init = np.broadcast_to(
        np.where(ys >= 1.5 - 1e-9, 10.0, 5.0), (N, N)).copy()
    res = _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=2.0, stock_init=stock_init)
    eng = res["engagement"]
    assert eng is not None
    assert abs(eng["max_mm"] - 1.5) <= 0.3, \
        "side-cut engagement %.3f not within 1.5 +/- 0.3" % eng["max_mm"]
    assert eng["count"] == 0, \
        "1.5 mm side cut flagged at engage_max=2.0 (max %.3f)" % eng["max_mm"]


def test_engagement_second_pass_stepover_1_0():
    """Second parallel pass at 1.0 mm stepover over a cleared band:
    engagement reads ~1.0 mm."""
    part = block_part(hi=10.0, half=15.0)
    # pass 1: clears a band centered at Y0.2 (tool edge reaches Y3.2)
    res1 = _run_engage("""
G21 G90 F500
G0 X-20. Y0.2 Z20.
G1 Z5. F100.
G1 X20. Y0.2 F500.
""", part, dia=6.0)
    # pass 2: centerline at Y1.2 -> 1.0 mm stepover into fresh material;
    # stay inside pass 1's X range so its round end-cap sliver is not cut
    res2 = _run_engage("""
G21 G90 F500
G0 X-15. Y1.2 Z20.
G1 Z5. F100.
G1 X15. Y1.2 F500.
""", part, dia=6.0, engage_max=2.0, stock_init=res1["stock"])
    eng = res2["engagement"]
    assert eng is not None
    assert abs(eng["max_mm"] - 1.0) <= 0.3, \
        "stepover engagement %.3f not within 1.0 +/- 0.3" % eng["max_mm"]


def test_engagement_horizontal_distribution_straight_side_cut():
    """Straight 1.5 mm side cut: horizontal p50 ~1.5 +/- 0.3, entry empty."""
    part = block_part(hi=10.0, half=15.0)
    ys = centers()[:, None]
    xs = centers()[None, :]
    # fresh material (height 10) in the band y >= 1.5, but the plunge zone
    # (x < -16, fully covering the tool at the Z5 entry point) is cleared
    # to 5 so the vertical entry cuts nothing and stays out of "entry"
    stock_init = np.where((ys >= 1.5 - 1e-9) & (xs >= -16.0), 10.0, 5.0)
    res = _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=2.0, stock_init=stock_init)
    eng = res["engagement"]
    assert eng is not None
    horiz = eng["horizontal"]
    assert horiz["n"] >= 1, "straight side cut not in horizontal bucket"
    assert abs(horiz["p50"] - 1.5) <= 0.3, \
        "horizontal p50 %.3f not within 1.5 +/- 0.3" % horiz["p50"]
    for key in ("p95", "p99", "max"):
        assert horiz[key] is not None and horiz[key] >= horiz["p50"] - 1e-9
    assert eng["entry"]["n"] == 0, \
        "entry bucket not empty for a horizontal cut (n=%d)" % eng["entry"]["n"]


def test_engagement_ramp_entry_not_horizontal():
    """Descending ramp into stock: lands in 'entry', not 'horizontal'."""
    part = block_part(hi=10.0, half=15.0)
    # ramp from Z12 down to Z8 across the block (top at 10): engages stock
    # while descending -> entry bucket only
    res = _run_engage("""
G21 G90 F500
G0 X-10. Y0. Z12.
G1 X10. Y0. Z8. F100
""", part, dia=6.0, engage_max=2.0)
    eng = res["engagement"]
    assert eng is not None
    assert eng["entry"]["n"] >= 1, "ramp into stock not in entry bucket"
    assert abs(eng["entry"]["max"] - 6.0) <= 0.5, \
        "ramp entry max %.3f not ~full width" % eng["entry"]["max"]
    assert eng["horizontal"]["n"] == 0, \
        "descending ramp counted as horizontal (n=%d)" % eng["horizontal"]["n"]


def test_engagement_spike_kind():
    """Spike > engage_max carries kind: horizontal for level cuts, entry
    for descending ones."""
    part = block_part(hi=10.0, half=15.0)
    res = _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=5.0)
    spikes = res["engagement"]["spikes"]
    assert len(spikes) >= 1
    assert all(s["kind"] in ("horizontal", "entry") for s in spikes)
    assert any(s["kind"] == "horizontal" for s in spikes), \
        "level full-width slot spike not kind=horizontal"


def test_plunge_helix_not_flagged():
    """Helix entry at 2 deg: NOT flagged as a plunge (below ramp_angle=3)."""
    part = block_part(hi=10.0, half=15.0)
    # Helical entry: descend 0.3 mm while traveling 14 mm in XY
    # angle = atan(0.3/14) = 1.2 deg < 3.0 deg -> not flagged
    # Start at Z=10.3 (above stock top 10), end at Z=10.0 (stock surface)
    # Then a lateral cut at Z=5 (no descent, not a plunge)
    res = _run_engage("""
G21 G90 F500
G0 X-7. Y0. Z15.
G1 X7. Y0. Z10.0 F200.
G0 Z15.
G1 X-7. Y0. Z10.3 F200.
G1 X7. Y0. Z10.0 F200.
G1 Z5. F100.
G1 X-7. Y0. F500.
""", part, dia=6.0, ramp_angle=3.0)
    plunge = res["plunge"]
    # The helix (line 7: Z10.3->Z10.0 over 14 mm) is 1.2 deg < 3 deg -> not flagged
    # The Z5 plunge (line 8) is vertical -> IS flagged
    # So exactly 1 plunge (the vertical one), not the helix
    assert plunge["count"] == 1, \
        "expected 1 plunge (vertical only): got %d" % plunge["count"]
    assert plunge["flags"][0]["angle_deg"] == 90.0


def test_plunge_vertical_flagged():
    """Straight vertical plunge into stock: flagged."""
    part = block_part(hi=10.0, half=15.0)
    res = _run_engage("""
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z5. F100.
G1 X10. Y0. F500.
""", part, dia=6.0)
    plunge = res["plunge"]
    assert plunge["count"] >= 1, "vertical plunge not flagged"
    flag = plunge["flags"][0]
    assert flag["angle_deg"] == 90.0, \
        "vertical plunge angle %.1f != 90" % flag["angle_deg"]
    assert flag["depth_mm"] > 0.0, "plunge depth should be positive"
    assert flag["depth_mm"] >= 4.9, \
        "plunge depth %.3f < 4.9" % flag["depth_mm"]


def test_plunge_and_engagement_in_warnings():
    """Both reports appear under 'warnings' in the CLI output."""
    import tempfile, json, os
    part = block_part(hi=10.0, half=15.0)
    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as hf:
        np.save(hf, part)
    sidecar = hf.name.replace(".npy", ".json")
    with open(sidecar, "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    gcode = tempfile.NamedTemporaryFile(suffix=".ngc", delete=False, mode="w")
    gcode.write("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z10. F100.
G1 X20. Y0. Z5. F100.
G1 X-20. Y0. F500.
""")
    gcode.close()
    out_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_json.close()
    try:
        stock_args = ["--stock"] + [str(v) for v in STOCK]
        rc = zmap.main([gcode.name, "--part", hf.name] + stock_args
                       + ["--engage-max", "4.0", "--out-json", out_json.name])
        assert rc == 0
        with open(out_json.name) as f:
            report = json.load(f)
        w = report["warnings"]
        assert "engagement" in w and "plunge" in w
        assert w["engagement"]["count"] >= 1
        assert w["plunge"]["count"] >= 1
    finally:
        for p in (hf.name, sidecar, gcode.name, out_json.name):
            if os.path.exists(p):
                os.unlink(p)


def test_cli_optimal_load_computes_engage_max():
    """CLI --optimal-load computes engage_max as 1.2x the value (roughing)."""
    import tempfile, json, os
    part = block_part(hi=10.0, half=15.0)
    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as hf:
        np.save(hf, part)
    sidecar = hf.name.replace(".npy", ".json")
    with open(sidecar, "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    gcode = tempfile.NamedTemporaryFile(suffix=".ngc", delete=False, mode="w")
    gcode.write("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z10. F100.
G1 X20. Y0. Z5. F100.
G1 X-20. Y0. F500.
""")
    gcode.close()
    out_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_json.close()
    try:
        stock_args = ["--stock"] + [str(v) for v in STOCK]
        rc = zmap.main([gcode.name, "--part", hf.name] + stock_args
                       + ["--optimal-load", "2.0", "--out-json", out_json.name])
        assert rc == 0
        with open(out_json.name) as f:
            report = json.load(f)
        eng = report["engagement"]
        # threshold should be 1.2 * 2.0 = 2.4 (roughing: warn above 1.2x)
        assert eng is not None, "engagement should not be None"
        assert eng["threshold_mm"] == 2.4,             "threshold %.3f != 2.4 (1.2 * 2.0)" % eng["threshold_mm"]
        # The full-width cut should be flagged (engagement ~6 > 2.4)
        assert eng["count"] >= 1, "full-width cut not flagged at threshold 2.4"
    finally:
        for p in (hf.name, sidecar, gcode.name, out_json.name):
            if os.path.exists(p):
                os.unlink(p)


def test_cli_optimal_load_2p032_threshold_2p4384():
    """Z6: roughing --optimal-load 2.032 derives threshold_mm 2.4384
    (1.2 x optimal load; was 1.5x = 3.048)."""
    import tempfile, json, os
    part = block_part(hi=10.0, half=15.0)
    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as hf:
        np.save(hf, part)
    sidecar = hf.name.replace(".npy", ".json")
    with open(sidecar, "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    gcode = tempfile.NamedTemporaryFile(suffix=".ngc", delete=False, mode="w")
    gcode.write("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z10. F100.
G1 X20. Y0. Z5. F100.
G1 X-20. Y0. F500.
""")
    gcode.close()
    out_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_json.close()
    try:
        stock_args = ["--stock"] + [str(v) for v in STOCK]
        rc = zmap.main([gcode.name, "--part", hf.name] + stock_args
                       + ["--optimal-load", "2.032",
                          "--out-json", out_json.name])
        assert rc == 0
        with open(out_json.name) as f:
            report = json.load(f)
        eng = report["engagement"]
        assert eng is not None
        assert abs(eng["threshold_mm"] - 2.4384) < 1e-9, \
            "threshold %r != 2.4384 (1.2 * 2.032)" % eng["threshold_mm"]
        assert abs(report["warnings"]["engagement"]["threshold_mm"]
                   - 2.4384) < 1e-9
    finally:
        for p in (hf.name, sidecar, gcode.name, out_json.name):
            if os.path.exists(p):
                os.unlink(p)


def test_cli_optimal_load_and_ramp_angle():
    """CLI --optimal-load and --ramp-angle both work together."""
    import tempfile, json, os
    part = block_part(hi=10.0, half=15.0)
    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as hf:
        np.save(hf, part)
    sidecar = hf.name.replace(".npy", ".json")
    with open(sidecar, "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    gcode = tempfile.NamedTemporaryFile(suffix=".ngc", delete=False, mode="w")
    gcode.write("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z10. F100.
G1 X20. Y0. Z5. F100.
G1 X-20. Y0. F500.
""")
    gcode.close()
    out_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_json.close()
    try:
        stock_args = ["--stock"] + [str(v) for v in STOCK]
        rc = zmap.main([gcode.name, "--part", hf.name] + stock_args
                       + ["--optimal-load", "2.0", "--ramp-angle", "5.0",
                          "--out-json", out_json.name])
        assert rc == 0
        with open(out_json.name) as f:
            report = json.load(f)
        eng = report["engagement"]
        assert eng["threshold_mm"] == 2.4,             "threshold %.3f != 2.4 (1.2 * 2.0)" % eng["threshold_mm"]
        plunge = report["plunge"]
        assert plunge["ramp_angle_deg"] == 5.0,             "ramp_angle %.1f != 5.0" % plunge["ramp_angle_deg"]
        # Both appear in warnings
        w = report["warnings"]
        assert w["engagement"]["threshold_mm"] == 2.4
        assert w["plunge"]["ramp_angle_deg"] == 5.0
    finally:
        for p in (hf.name, sidecar, gcode.name, out_json.name):
            if os.path.exists(p):
                os.unlink(p)


def test_cli_report_strict_json(tmp_path):
    """A real sample program (plunge + slot + arc + helix) must produce a
    strict-JSON report: no Infinity/NaN tokens anywhere in the file."""
    import json
    part = block_part(hi=10.0, half=15.0)
    npy = tmp_path / "part.npy"
    np.save(npy, part)
    with open(str(npy).replace(".npy", ".json"), "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    gc = tmp_path / "sample.ngc"
    gc.write_text("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z10. F100.
G1 X0. Y0. Z5. F100.
G1 X10. Y0. F500.
G2 X10. Y6. R3. F500.
G1 X-10. Y6. F500.
G0 X20. Y0. Z15.
G1 Z10. F100.
G3 X10. Y0. R5. Z6. F500.
G0 Z20.
""")
    out = tmp_path / "report.json"
    rc = zmap.main([str(gc), "--part", str(npy)]
                   + ["--stock"] + [str(v) for v in STOCK]
                   + ["--optimal-load", "2.0", "--out-json", str(out)])
    assert rc == 0
    text = out.read_text()

    def _reject(tok):
        raise AssertionError("non-strict JSON token in report: %s" % tok)

    report = json.loads(text, parse_constant=_reject)  # raises on Inf/NaN
    assert "Infinity" not in text and "NaN" not in text
    eng = report["engagement"]
    assert eng is not None and math.isfinite(eng["max_mm"])
    assert eng["max_mm"] <= 6.0 + 1e-6
    for sp in eng["spikes"]:
        assert math.isfinite(sp["engagement_mm"])
    for fl in report["plunge"]["flags"]:
        assert math.isfinite(fl["depth_mm"]) and math.isfinite(fl["angle_deg"])


# ---------------------------------------------------------------------------
# Review 2 (supervisor): engagement must be finite and bounded by D
# ---------------------------------------------------------------------------

def test_engagement_helix_finite():
    """Helix entry: engagement must be finite and <= tool diameter."""
    part = block_part(hi=10.0, half=15.0)
    res = _run_engage("""
G21 G90 F500
G0 X-15. Y0. Z20.
G1 X15. Y0. Z5. F200.
G1 X-15. Y0. F500.
""", part, dia=6.0, engage_max=5.0)
    assert res["engagement"] is not None
    assert math.isfinite(res["engagement"]["max_mm"]), \
        "helix engagement is not finite"
    assert res["engagement"]["max_mm"] <= 6.0 + 1e-6, \
        "helix engagement %.3f > D=6.0" % res["engagement"]["max_mm"]
    for sp in res["engagement"]["spikes"]:
        assert math.isfinite(sp["engagement_mm"]), \
            "spike engagement_mm is not finite"


def test_engagement_pure_plunge_finite():
    """Pure plunge (zero XY length): engagement must be finite and <= D."""
    part = block_part(hi=10.0, half=15.0)
    res = _run_engage("""
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z5. F100.
G1 X10. Y0. F500.
""", part, dia=6.0, engage_max=5.0)
    assert res["engagement"] is not None
    assert math.isfinite(res["engagement"]["max_mm"]), \
        "plunge engagement is not finite"
    assert res["engagement"]["max_mm"] <= 6.0 + 1e-6, \
        "plunge engagement %.3f > D=6.0" % res["engagement"]["max_mm"]


# ---------------------------------------------------------------------------
# Task ZE: axial depth per engaging move (wide_moves / slot / skim /
# full_width_slots / overload_feeds) - report-only, existing numbers frozen
# ---------------------------------------------------------------------------

def test_ze_full_width_slot_3mm_depth_is_slot():
    """Full-width slot cut 3 mm into a 10 mm block (tip Z7): wide move
    classified slot (axial depth ~3 > 0.5), visible in slot_horizontal,
    full_width_slots and overload_feeds."""
    part = block_part(hi=10.0, half=15.0)
    res = _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z7. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=2.0)
    eng = res["engagement"]
    wm = eng["wide_moves"]
    assert wm is not None and wm["threshold_mm"] == 2.0
    # the horizontal full-width move is a slot, not a skim
    assert wm["slot"]["count"] == 1, \
        "full-width 3 mm slot not classified slot: %r" % wm
    assert wm["skim"]["count"] == 0
    assert abs(wm["slot"]["depth_p50"] - 3.0) <= 0.1, \
        "slot axial depth %.3f not ~3 mm" % wm["slot"]["depth_p50"]
    assert abs(wm["slot"]["width_p50"] - 6.0) <= 0.3
    assert wm["slot"]["total_length_mm"] > 0.0
    assert wm["slot"]["total_time_s"] > 0.0
    # the load-relevant statistic: width over horizontal moves deeper than
    # 0.5 mm axial
    sh = eng["slot_horizontal"]
    assert sh["n"] == 1 and abs(sh["p50"] - 6.0) <= 0.3
    # full-width slot: width >= 0.9 x dia AND depth > 0.5
    fws = eng["full_width_slots"]
    assert fws["count"] == 1 and abs(fws["total_length_mm"] - 40.0) <= 0.5
    top = fws["top"][0]
    assert top["width_mm"] >= 5.4 and abs(top["depth_mm"] - 3.0) <= 0.1
    assert "line" in top and "x" in top and "y" in top
    # overload: width > 1.2 x the 2.032 load AND axial depth > 0.5
    ovl = eng["overload_feeds"]
    assert ovl["count"] == 1 and ovl["total_length_mm"] > 0.0
    assert abs(ovl["worst"][0]["depth_mm"] - 3.0) <= 0.1
    assert ovl["worst"][0]["z"] == 7.0


def test_ze_floor_pass_0p02mm_is_skim_and_in_skim_by_z():
    """Full-width pass over a floor 0.02 mm high (stock 7.02, tip Z7):
    classified skim (depth <= 0.5), and its time is counted in skim_by_z
    at that Z level (depth <= 0.05)."""
    part = block_part(hi=10.0, half=15.0)
    stock_init = np.full((N, N), 7.02)
    res = _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z7. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=2.0, stock_init=stock_init)
    eng = res["engagement"]
    wm = eng["wide_moves"]
    assert wm["skim"]["count"] == 1, \
        "0.02 mm floor pass not classified skim: %r" % wm
    assert wm["slot"]["count"] == 0
    assert abs(wm["skim"]["depth_p50"] - 0.02) <= 0.005
    assert abs(wm["skim"]["width_p50"] - 6.0) <= 0.3
    # skim_by_z: the 40 mm pass at F500 takes 4.8 s at Z7.000
    sbz = eng["skim_by_z"]
    assert "7.000" in sbz, "floor skim not counted in skim_by_z: %r" % sbz
    assert abs(sbz["7.000"] - 4.8) <= 0.2
    # not a slot, so no full-width slot / overload either
    assert eng["full_width_slots"]["count"] == 0
    assert eng["overload_feeds"]["count"] == 0
    assert eng["slot_horizontal"]["n"] == 0


def test_ze_existing_engagement_numbers_unchanged():
    """Task ZE HARD RULE: the existing engagement numbers (threshold_mm,
    count, horizontal/entry p50/p95/p99/max, spikes) are byte-identical to
    the pre-ZE values on existing fixtures - asserted by equality."""
    old = {
        "side15": {
            "threshold_mm": 2.0, "count": 0, "max_mm": 1.5,
            "horizontal": {"n": 1, "p50": 1.5, "p95": 1.5, "p99": 1.5,
                          "max": 1.5},
            "entry": {"n": 1, "p50": 1.5, "p95": 1.5, "p99": 1.5,
                     "max": 1.5},
            "spikes": [],
        },
        "fullwidth": {
            "threshold_mm": 5.0, "count": 2, "max_mm": 6.0,
            "horizontal": {"n": 1, "p50": 6.0, "p95": 6.0, "p99": 6.0,
                          "max": 6.0},
            "entry": {"n": 1, "p50": 6.0, "p95": 6.0, "p99": 6.0,
                     "max": 6.0},
            "spikes": [
                {"line": 4, "x": -20.0, "y": 0.0, "engagement_mm": 6.0,
                 "kind": "entry"},
                {"line": 5, "x": 20.0, "y": 0.0, "engagement_mm": 6.0,
                 "kind": "horizontal"},
            ],
        },
        "corner": {
            "threshold_mm": 4.0, "count": 4, "max_mm": 6.0,
            "horizontal": {"n": 3, "p50": 6.0, "p95": 6.0, "p99": 6.0,
                          "max": 6.0},
            "entry": {"n": 1, "p50": 6.0, "p95": 6.0, "p99": 6.0,
                     "max": 6.0},
            "spikes": [
                {"line": 4, "x": -10.0, "y": -3.0, "engagement_mm": 6.0,
                 "kind": "entry"},
                {"line": 5, "x": 10.0, "y": -3.0, "engagement_mm": 6.0,
                 "kind": "horizontal"},
                {"line": 6, "x": 10.0, "y": 3.0, "engagement_mm": 6.0,
                 "kind": "horizontal"},
                {"line": 7, "x": -10.0, "y": 3.0, "engagement_mm": 6.0,
                 "kind": "horizontal"},
            ],
        },
    }
    part = block_part(hi=10.0, half=15.0)
    ys = centers()[:, None]
    stock_init = np.broadcast_to(np.where(ys >= 1.5 - 1e-9, 10.0, 5.0),
                                 (N, N)).copy()
    res = {
        "side15": _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=2.0, stock_init=stock_init),
        "fullwidth": _run_engage("""
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. Y0. F500.
""", part, dia=6.0, engage_max=5.0),
        "corner": _run_engage("""
G21 G90 F500
G0 X-10. Y-3. Z20.
G1 Z5. F100.
G1 X10. Y-3. F500.
G1 X10. Y3. F500.
G1 X-10. Y3. F500.
""", part, dia=6.0, engage_max=4.0),
    }
    keys = ("threshold_mm", "count", "max_mm", "horizontal", "entry",
            "spikes")
    for name, base in old.items():
        got = {k: res[name]["engagement"][k] for k in keys}
        assert got == base, \
            "%s: existing engagement changed:\n got %r\n old %r" % (
                name, got, base)


def test_ze_parallel_merge_matches_serial():
    """--jobs merges the raw width+depth records per move, so every task ZE
    key equals the serial result exactly."""
    part = block_part(hi=10.0, half=15.0)
    gcode = """
G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z7. F100.
G1 X20. Y0. F500.
G0 Z20.
G0 X-20. Y4. Z20.
G1 Z7. F100.
G1 X20. Y4. F500.
"""
    moves = zmap.parse_gcode(gcode)
    ser = zmap.simulate(moves, part, CELL, X0, Y0, STOCK, dia=6.0,
                       engage_max=2.0)
    for jobs in (2, 4):
        par = zmap.simulate_parallel(zmap.parse_gcode(gcode), part, CELL,
                                    X0, Y0, STOCK, jobs, dia=6.0,
                                    engage_max=2.0)
        assert par["engagement"] == ser["engagement"], \
            "jobs=%d: ZE engagement keys differ from serial" % jobs


# ---------------------------------------------------------------------------
# Task ZE2: AREA-based radial engagement ae_eff = removed plan area / travel,
# windows of >= 1 mm travel (ae2 keys) - report-only, old keys frozen.
# Fixtures: flat D = 12.686, cell 0.1 mm, solid stock (top 18.6).
# ---------------------------------------------------------------------------

D_ZE2 = 12.686
CELL_F = 0.1
X0_F = Y0_F = -30.0
NF = 600  # grid covers [-30, 30] x [-30, 30]
STOCK_F = (-30.0, 30.0, -30.0, 30.0, 0.0, 18.6)


def _centers_f():
    return X0_F + (np.arange(NF) + 0.5) * CELL_F


def _run_ae2(gcode, part, stock_init=None, dia=D_ZE2):
    moves = zmap.parse_gcode(gcode)
    return zmap.simulate(moves, part, CELL_F, X0_F, Y0_F, STOCK_F,
                        tool="flat", dia=dia, engage_max=2.438,
                        stock_init=stock_init)


def _ae2_gcode(pts, entry_xy, z):
    """rapid to entry_xy above stock, plunge/feed to tip Z=z, then the G1
    feed sequence pts [(x, y), ...] at F500."""
    lines = ["G21 G90 F500",
             "G0 X%.4f Y%.4f Z20." % entry_xy,
             "G1 X%.4f Y%.4f Z%.4f F100." % (entry_xy[0], entry_xy[1], z)]
    for (x, y) in pts:
        lines.append("G1 X%.4f Y%.4f F500." % (x, y))
    return "\n".join(lines) + "\n"


def test_ze2_full_slot_short_segments_ae_eff_is_dia():
    """Full-width slot in solid stock cut in 0.1 mm segments: every ae2
    window removes the full strip D x length, so ae_eff = D within 5 %.
    (The old max-chord metric also reads ~D here - a slot front crescent IS
    full width - so this case does NOT separate the metrics.)"""
    part = np.zeros((NF, NF))
    pts = [(-20.0 + 0.1 * i, 0.0) for i in range(1, 401)]
    res = _run_ae2(_ae2_gcode(pts, (-20.0, 0.0), 13.6), part)
    wins = res["_ae2_raw"]
    assert len(wins) >= 30, "too few ae2 windows: %d" % len(wins)
    for w in wins:
        assert abs(w["ae_eff"] - D_ZE2) <= 0.05 * D_ZE2, \
            "ae_eff %.3f not within 5%% of D" % w["ae_eff"]
        assert abs(w["a"] - 5.0) <= 0.2  # 18.6 - tip 13.6
        # window closes at the first travel >= 1 mm; ten 0.1 mm floats sum to
        # just under/over 1.0, so accept 10 or 11 segments
        if w is not wins[-1]:
            assert w["n_moves"] in (10, 11)
            assert 1.0 <= w["length_mm"] <= 1.15
    # ZG2: the program's last 0.7 mm tail merges into the last kept window
    assert abs(wins[-1]["length_mm"] - 1.7) <= 1e-6, wins[-1]["length_mm"]
    assert wins[-1]["n_moves"] == 10 + 7, wins[-1]["n_moves"]
    assert abs(wins[-1]["ae_eff"] - D_ZE2) <= 0.05 * D_ZE2, wins[-1]["ae_eff"]
    eng = res["engagement"]
    assert eng["ae2"]["n"] == len(wins)
    assert abs(eng["ae2"]["p50"] - D_ZE2) <= 0.05 * D_ZE2
    # old metric for comparison: also ~D on a slot
    assert abs(eng["ae2"]["p50"] - eng["horizontal"]["p50"]) <= 0.6
    # every window is a full-width slot with axial depth 5 mm
    assert eng["full_width_slots_ae2"]["count"] == len(wins)
    assert abs(eng["full_width_slots_ae2"]["total_length_mm"] - 40.0) <= 1.5
    # ae_eff ~12.7 > 2.4384 -> all windows overload too
    assert eng["overload_feeds_ae2"]["count"] == len(wins)


def test_ze2_full_slot_5mm_segments_ae_eff_is_dia():
    """Same full slot, coarse 5 mm segments: each move is its own window and
    ae_eff = D within 5 %."""
    part = np.zeros((NF, NF))
    pts = [(-15.0 + 5.0 * i, 0.0) for i in range(1, 8)]
    res = _run_ae2(_ae2_gcode(pts, (-20.0, 0.0), 13.6), part)
    wins = res["_ae2_raw"]
    assert len(wins) == 7, "expected one window per 5 mm move: %d" % len(wins)
    for w in wins:
        assert abs(w["ae_eff"] - D_ZE2) <= 0.05 * D_ZE2, \
            "ae_eff %.3f not within 5%% of D" % w["ae_eff"]
    assert abs(res["engagement"]["ae2"]["p50"] - D_ZE2) <= 0.05 * D_ZE2


def test_ze2_curved_full_slot_ae_eff_is_dia():
    """Curved full slot: arc r = 40 mm as 0.5 mm chords (0.72 deg per chord,
    direction change << 45 deg so windows chain across chords). ae_eff = D
    within 5 %."""
    part = np.zeros((NF, NF))
    r = 40.0
    n = 80
    th0, th1 = -0.5, 0.5

    def arc_pt(t):
        a = th0 + (th1 - th0) * t
        return (r * math.sin(a), -r + r * math.cos(a))

    pts = [arc_pt(i / float(n)) for i in range(1, n + 1)]
    res = _run_ae2(_ae2_gcode(pts, arc_pt(0.0), 13.6), part)
    wins = res["_ae2_raw"]
    assert len(wins) >= 30, "too few ae2 windows: %d" % len(wins)
    for w in wins:
        assert abs(w["ae_eff"] - D_ZE2) <= 0.05 * D_ZE2, \
            "ae_eff %.3f not within 5%% of D on the arc" % w["ae_eff"]


def test_ze2_side_cut_2032_ae_eff_is_engagement():
    """Straight side cut along a wall: face at radial distance R - 2.032 from
    the path, wall 5 mm above tip Z. Removed strip is 2.03 mm deep x travel,
    so ae_eff = 2.032 +- 0.1. ZE's old max-chord metric reads the chord of
    the cells above the tip here (~2.0 mm) and agrees - this case validates
    that ae_eff measures the true radial engagement, not that the old metric
    fails it. (The case where the OLD METRIC FAILS is the slot rim skim:
    test_ze2_slot_rim_skim_old_width_reads_full_but_ae2_small.)"""
    part = np.zeros((NF, NF))
    ys = _centers_f()[:, None]
    face = D_ZE2 / 2.0 - 2.032  # 4.311 mm: tool centre path distance to wall
    stock_init = np.broadcast_to(np.where(ys <= -face + 1e-9, 18.6, 13.6), (NF, NF)).copy()
    pts = [(-20.0 + 2.0 * i, 0.0) for i in range(1, 21)]
    res = _run_ae2(_ae2_gcode(pts, (-20.0, 0.0), 13.6), part,
                   stock_init=stock_init)
    wins = res["_ae2_raw"]
    assert len(wins) >= 10
    for w in wins:
        assert abs(w["ae_eff"] - 2.032) <= 0.1, \
            "ae_eff %.3f not 2.032 +- 0.1" % w["ae_eff"]
        assert abs(w["a"] - 5.0) <= 0.2
    eng = res["engagement"]
    assert abs(eng["ae2"]["p50"] - 2.032) <= 0.1
    # no full-width slot and no overload by AREA:
    assert eng["full_width_slots_ae2"]["count"] == 0
    assert eng["overload_feeds_ae2"]["count"] == 0
    # old metric agrees here: cells above the tip span the wall strip ~2.0 mm
    # (NOT the circle chord 9.31 mm - it only reads ~D when rim cells on both
    # sides stand above the tip, see the rim-skim test)
    for w in wins:
        assert abs(w["width_mm"] - 2.0) <= 0.15, \
            "old width %.3f not the engaged strip ~2.0" % w["width_mm"]


def test_ze2_wall_skim_0p1mm_ae_eff_small_and_a_is_18():
    """0.1 mm skim of an 18 mm tall wall: face at R - 0.1 from the path,
    floor level with the tip (Z0), wall top 18 mm above the tip. Only a thin
    rim row of cells is removed -> ae_eff <= 0.2 and a = 18 +- 0.2."""
    part = np.zeros((NF, NF))
    ys = _centers_f()[:, None]
    face = D_ZE2 / 2.0 - 0.1  # 6.243
    stock_init = np.broadcast_to(np.where(ys <= -face + 1e-9, 18.0, 0.0), (NF, NF)).copy()
    pts = [(-20.0 + 0.5 * i, 0.0) for i in range(1, 81)]
    res = _run_ae2(_ae2_gcode(pts, (-20.0, 0.0), 0.0), part,
                   stock_init=stock_init)
    wins = res["_ae2_raw"]
    assert len(wins) >= 30
    for w in wins:
        assert w["ae_eff"] <= 0.2, "skim ae_eff %.3f > 0.2" % w["ae_eff"]
        assert abs(w["a"] - 18.0) <= 0.2, "skim depth a=%.3f" % w["a"]
    eng = res["engagement"]
    assert eng["full_width_slots_ae2"]["count"] == 0
    assert eng["overload_feeds_ae2"]["count"] == 0


def test_ze2_slot_rim_skim_old_width_reads_full_but_ae2_small():
    """The line-567 form: tool runs along a slot whose two walls stand 18 mm
    above the tip while the floor is level with the tip. The removed cells sit
    at radial ~6.2-6.3 on BOTH sides and span nearly the full diameter, so
    ZE's old max-chord width reads ~D (full_width_slots counts every move) -
    the OLD METRIC FAILS here. By AREA only two thin rim rows are removed:
    ae_eff ~0.2, so the ae2 keys count nothing."""
    part = np.zeros((NF, NF))
    ys = _centers_f()[:, None]
    face = D_ZE2 / 2.0 - 0.1  # walls at |y| >= 6.243, floor at tip level
    stock_init = np.broadcast_to(np.where(np.abs(ys) >= face - 1e-9, 18.0, 0.0), (NF, NF)).copy()
    pts = [(-20.0 + 0.5 * i, 0.0) for i in range(1, 81)]
    res = _run_ae2(_ae2_gcode(pts, (-20.0, 0.0), 0.0), part,
                   stock_init=stock_init)
    wins = res["_ae2_raw"]
    assert len(wins) >= 30
    for w in wins:
        assert w["ae_eff"] <= 0.3, "rim-skim ae_eff %.3f too large" % w["ae_eff"]
        assert abs(w["a"] - 18.0) <= 0.2
        # old metric: cells above the tip span both rim rows -> ~full width
        assert w["width_mm"] >= 0.9 * D_ZE2, \
            "old width %.3f should read ~full diameter" % w["width_mm"]
    eng = res["engagement"]
    # old keys call it full-width slotting (this is the ZE mis-score)
    assert eng["full_width_slots"]["count"] >= 30
    # the area form sees the truth: nothing near full width, nothing loaded
    assert eng["full_width_slots_ae2"]["count"] == 0
    assert eng["overload_feeds_ae2"]["count"] == 0
    assert eng["ae2"]["max"] <= 0.3


def test_ze2_windows_break_on_direction_z_and_rapid():
    """A window ends at a direction change > 45 deg, a Z change or a rapid;
    feeds at <= 45 deg apart keep merging. Geometry: two straight 0.5 mm
    feeds (line 5-6) -> window 1; a 90 deg turn breaks (window 2 starts at
    line 7) but within window 2 the direction turns 36.9 deg (line 8) and the
    window still merges - <= 45 deg keeps joining; lines 9-10 continue straight
    into window 3; a diagonal Z-change move breaks, the two feeds
    at Z13.5 form window 4; a rapid plus plunge break, the final two feeds
    form window 5. Steps are 0.6 mm ((0.36, 0.48) diagonals), so a single
    feed never reaches 1 mm and every window is exactly two feeds robustly
    under binary floats."""
    part = np.zeros((NF, NF))
    gcode = """
G21 G90 F500
G0 X-20. Y0. Z20.
G1 X-20. Y0. Z13.6 F100.
G1 X-19.4 Y0. F500.
G1 X-18.8 Y0. F500.
G1 X-18.8 Y0.6 F500.
G1 X-18.44 Y1.08 F500.
G1 X-18.08 Y1.56 F500.
G1 X-17.72 Y2.04 F500.
G1 X-17.12 Y2.84 Z13.5 F500.
G1 X-16.52 Y2.84 Z13.5 F500.
G1 X-15.92 Y2.84 Z13.5 F500.
G0 X-10. Y0. Z20.
G1 X-10. Y0. Z13.6 F100.
G1 X-9.4 Y0. F500.
G1 X-8.8 Y0. F500.
"""
    res = _run_ae2(gcode, part)
    wins = res["_ae2_raw"]
    assert len(wins) == 5, "expected 5 windows: %r" % wins
    assert wins[0]["n_moves"] == 2 and wins[0]["line"] == 5
    assert wins[1]["n_moves"] == 2 and wins[1]["line"] == 7   # 90 deg break,
    # 36.9 deg turn inside the window keeps merging
    assert wins[2]["n_moves"] == 2 and wins[2]["line"] == 9
    assert wins[3]["z"] == 13.5 and wins[3]["n_moves"] == 2   # Z break
    assert wins[4]["z"] == 13.6 and wins[4]["line"] == 16     # rapid break
    for w in wins:
        assert 1.1 <= w["length_mm"] <= 1.3


def test_ze2_parallel_merge_matches_serial():
    """--jobs merges the raw per-feed area records with global move indices,
    so ae2 windows and keys equal the serial result exactly."""
    part = np.zeros((NF, NF))
    ys = _centers_f()[:, None]
    stock_init = np.broadcast_to(np.where(np.abs(ys) >= 6.243 - 1e-9, 18.0, 0.0), (NF, NF)).copy()
    pts = [(-20.0 + 0.5 * i, 0.0) for i in range(1, 81)]
    gcode = _ae2_gcode(pts, (-20.0, 0.0), 0.0)
    ser = zmap.simulate(zmap.parse_gcode(gcode), part, CELL_F, X0_F, Y0_F,
                       STOCK_F, tool="flat", dia=D_ZE2, engage_max=2.438,
                       stock_init=stock_init)
    for jobs in (2, 4):
        par = zmap.simulate_parallel(zmap.parse_gcode(gcode), part, CELL_F,
                                    X0_F, Y0_F, STOCK_F, jobs, tool="flat",
                                    dia=D_ZE2, engage_max=2.438,
                                    stock_init=stock_init)
        assert par["_ae2_raw"] == ser["_ae2_raw"], \
            "jobs=%d: ae2 windows differ from serial" % jobs
        assert par["engagement"] == ser["engagement"], \
            "jobs=%d: engagement keys differ from serial" % jobs


# ---------------------------------------------------------------------------
# Task ZG2: sub-1 mm tails are MERGED into their kept window, never dropped
# ---------------------------------------------------------------------------

def _zg2_wall_stock(width):
    """stock 18.6 under a wall whose face sits `width` mm inside the tool
    radius from the y=0 path (and solid for x >= 10, fresh material for the
    neighbour-free tail), 13.6 (tip level) elsewhere."""
    ys = _centers_f()[:, None]
    xs = _centers_f()[None, :]
    face = D_ZE2 / 2.0 - width
    return np.broadcast_to(
        np.where((ys <= -face + 1e-9) | (xs >= 10.0 - 1e-9), 18.6, 13.6),
        (NF, NF)).copy()


def test_zg2_merged_tail_pushes_window_over_spike():
    """ZG2 (a): a ~0.865 mm-wide side-cut window (2 x 0.6 = 1.2 mm, pre-merge
    ae_eff ~0.865) plus a sub-1 mm tail from a neighbour-free chain (one
    0.9 mm feed into fresh solid, area ~11 mm2) merge into ONE window whose
    ae_eff is judged over the AE_SPIKE 2.25 limit (and over the SE2 merge
    bar 2.4384). Dropping the tail again leaves 0.865 -> test fails by the
    measured ae_eff."""
    part = np.zeros((NF, NF))
    gcode = _ae2_gcode([(-19.4, 0.0), (-18.8, 0.0)], (-20.0, 0.0), 13.6)
    gcode += "G0 X20. Y20. Z20.\nG1 X20. Y20. Z13.6 F100.\n"
    gcode += "G1 X20.9 Y20. F500.\n"
    res = _run_ae2(gcode, part, stock_init=_zg2_wall_stock(0.865))
    wins = res["_ae2_raw"]
    assert len(wins) == 1, "expected 1 merged window: %r" % wins
    w = wins[0]
    print("ZG2(a) measured merged ae_eff %.3f mm (area %.3f / length %.3f, "
          "line %s)" % (w["ae_eff"], w["area_mm2"], w["length_mm"],
                        w["line"]))
    assert w["ae_eff"] > 2.25, \
        "merged ae_eff %.3f mm not judged over 2.25" % w["ae_eff"]
    assert abs(w["length_mm"] - 2.1) <= 0.05, \
        "merged window length %.3f not 1.2 + 0.9" % w["length_mm"]
    eng = res["engagement"]
    assert eng["ae2"]["n"] == 1
    assert eng["ae2"]["max"] == w["ae_eff"]
    assert eng["overload_feeds_ae2"]["count"] == 1
    assert "ae2_isolated_sub1mm" not in eng  # the tail had a neighbour


def test_zg2_merged_tail_under_limit_changes_nothing():
    """ZG2 (b): uniform ~0.865 mm side cut: with a 0.6 mm tail the window
    grows 1.2 -> 1.8 mm but ae_eff stays ~0.865 (< 2.25, unchanged vs the
    no-tail run) and the window count stays 1; nothing is flagged."""
    part = np.zeros((NF, NF))
    base = _run_ae2(_ae2_gcode([(-19.4, 0.0), (-18.8, 0.0)],
                               (-20.0, 0.0), 13.6), part,
                    stock_init=_zg2_wall_stock(0.865))
    tail = _run_ae2(_ae2_gcode([(-19.4, 0.0), (-18.8, 0.0), (-18.2, 0.0)],
                               (-20.0, 0.0), 13.6), part,
                    stock_init=_zg2_wall_stock(0.865))
    wb, wt = base["_ae2_raw"], tail["_ae2_raw"]
    print("ZG2(b) ae_eff before %.3f / after %.3f mm (len %.3f -> %.3f)"
          % (wb[0]["ae_eff"], wt[0]["ae_eff"], wb[0]["length_mm"],
             wt[0]["length_mm"]))
    assert len(wb) == len(wt) == 1, "window count changed"
    assert abs(wt[0]["length_mm"] - 1.8) <= 0.05
    assert abs(wt[0]["ae_eff"] - wb[0]["ae_eff"]) <= 0.05, \
        "ae_eff changed %.3f -> %.3f" % (wb[0]["ae_eff"], wt[0]["ae_eff"])
    assert wt[0]["ae_eff"] < 2.25
    eng = tail["engagement"]
    assert eng["ae2"]["n"] == 1
    assert eng["full_width_slots_ae2"]["count"] == 0
    assert eng["overload_feeds_ae2"]["count"] == 0


def test_zg2_isolated_sub1mm_cut_reported_not_gated():
    """ZG2 item 2: a lone 0.6 mm cut with no kept window anywhere is NOT
    judged (no ae2 window, nothing flagged) but reported in
    engagement.ae2_isolated_sub1mm (count 1, worst area/length capped D)."""
    part = np.zeros((NF, NF))
    res = _run_ae2(_ae2_gcode([(-19.4, 0.0)], (-20.0, 0.0), 13.6), part)
    assert res["_ae2_raw"] == [], "isolated cut must not become a window"
    eng = res["engagement"]
    assert eng["ae2"]["n"] == 0
    assert eng["overload_feeds_ae2"]["count"] == 0
    iso = eng["ae2_isolated_sub1mm"]
    print("ZG2(c) isolated sub-1 mm: %r" % (iso,))
    assert iso["count"] == 1
    assert 0.0 < iso["worst_ae_eff_mm"] <= D_ZE2, \
        "worst %.3f not capped at D %.3f" % (iso["worst_ae_eff_mm"], D_ZE2)


# ---------------------------------------------------------------------------
# S5: independent holder clearance check (holder frustum stack from
# tools/x7_tools.json vs max(stock, part), 1.0 mm clearance)
# ---------------------------------------------------------------------------

def holder_part():
    """Part: slot |x| < 4 (floor z=0) along Y in a plate top z=10, plus a
    tall boss x in [6, 12], |y| <= 8 up to z=20 - far enough from the slot
    centreline (6 mm > any shank radius) that only the HOLDER reaches it."""
    xs = centers()[None, :]
    ys = centers()[:, None]
    part = np.where(np.abs(xs) < 4.0, 0.0, 10.0)
    inb = (xs >= 6.0) & (xs <= 12.0) & (np.abs(ys) <= 8.0)
    return np.where(inb, 20.0, part)


HOLDER_GCODE = """
G21 G90 F500
N3 G0 X0. Y-15. Z20.
N4 G1 Z0. F100.
N5 G1 Y15. F500.
"""


def _run_holder(holder, stickout, jobs=None):
    moves = zmap.parse_gcode(HOLDER_GCODE)
    sb = (-25.0, 25.0, -25.0, 25.0, 0.0, 20.0)
    kw = dict(tool="ball", dia=6.0, holder=holder, stickout=stickout)
    if jobs:
        return zmap.simulate_parallel(moves, holder_part(), CELL, X0, Y0, sb,
                                     jobs, **kw)
    return zmap.simulate(moves, holder_part(), CELL, X0, Y0, sb, **kw)


def test_holder_resolve_from_table():
    segs, st, name = zmap.resolve_holder(tool_number=31)
    assert name == "BT30-ER20-60" and st == 18.0
    assert segs[0] == [0.0, 2.0, 15.0, 16.9]
    # explicit holder + stickout overrides; T20 (3/8 ball) carries its own
    segs2, st2, name2 = zmap.resolve_holder(tool_number=20)
    assert name2 == "BT30-ER20-60" and st2 == 46.2
    segs3, st3, _ = zmap.resolve_holder(holder="BT30-ER20-80", stickout=9.0)
    assert st3 == 9.0 and segs3[1] == [2.0, 21.946, 16.9, 16.9]
    # T13 now carries a holder (BT30-ER32-70, Steve catalogue estimate)
    segs4, st4, name4 = zmap.resolve_holder(tool_number=13)
    assert name4 == "BT30-ER32-70" and st4 == 71.6
    assert segs4 == [[0.0, 35.0, 25.0, 25.0], [35.0, 70.0, 27.0, 23.0]]
    # tool without holder data / unknown number -> off, not an error
    assert zmap.resolve_holder(tool_number=3) is None  # no holder in entry
    assert zmap.resolve_holder(tool_number=99) is None
    assert zmap.resolve_holder() is None

    class _Args:
        def __init__(self, tool_number=None, holder=None):
            self.tool_number = tool_number
            self.holder = holder
            self.tools_json = zmap.TOOLS_JSON

    # the report never skips silently: a tool number with no holder in the
    # table is reported as "holder unknown" (the connector gate fails on it)
    rep_unknown = zmap._holder_report(_Args(tool_number=99), None, None)
    assert rep_unknown["status"] == "holder unknown"
    assert "99" in rep_unknown["reason"]
    # T13 checked: dimension_source is the Steve catalogue estimate
    rep_t13 = zmap._holder_report(_Args(tool_number=13), name4, st4)
    assert rep_t13 == {"status": "checked", "name": "BT30-ER32-70",
                       "stickout_mm": 71.6, "dimension_source": "estimated"}
    # nothing requested -> "not requested"
    assert zmap._holder_report(_Args(), None, None) == \
        {"status": "not requested"}
    try:
        zmap.resolve_holder(holder="NOPE", stickout=10.0)
        assert False, "unknown holder accepted"
    except ValueError:
        pass
    try:
        zmap.resolve_holder(holder="BT30-ER20-60")
        assert False, "holder without stickout accepted"
    except ValueError:
        pass


def test_holder_hits_counted_and_cleared():
    segs, st, _name = zmap.resolve_holder(tool_number=31)  # stickout 18
    res = _run_holder(segs, st)
    hh = res["holder_hits"]
    assert hh is not None
    # plunge (Z0: nose 18 < boss top 20 within the envelope) + traverse
    assert hh["count"] == 2, hh
    assert hh["first_line"] == 4, hh  # the G1 Z0 plunge
    assert abs(hh["max_intrusion"] - 2.0) < 1e-9, hh  # 20 - (0 + 18)
    wx, wy = hh["worst_xy"]
    assert 5.9 <= wx <= 12.1 and -8.1 <= wy <= 8.1, hh  # on the boss
    # no gouges / rapids: the ball itself is clean, only the holder hits
    assert res["gouges"]["count"] == 0
    assert res["rapid_collisions"]["count"] == 0
    # longer stick-out: nose at 25 >= boss top -> nothing touches
    res_b = _run_holder(segs, 25.0)
    assert res_b["holder_hits"]["count"] == 0
    assert res_b["holder_hits"]["max_intrusion"] == 0.0
    assert res_b["holder_hits"]["worst_xy"] is None
    # off without holder geometry
    res_c = _run_holder(None, None)
    assert res_c["holder_hits"] is None
    # parallel chunking matches serial exactly
    par = _run_holder(segs, st, jobs=2)
    assert par["holder_hits"]["count"] == hh["count"]
    assert abs(par["holder_hits"]["max_intrusion"]
               - hh["max_intrusion"]) < 1e-9
    assert par["holder_hits"]["worst_xy"] == hh["worst_xy"]
    assert par["holder_hits"]["first_line"] == hh["first_line"]


def test_holder_cli_tool_number(tmp_path):
    gc = tmp_path / "p.ngc"
    gc.write_text(HOLDER_GCODE)
    npy = tmp_path / "part.npy"
    np.save(npy, holder_part())
    import json
    (tmp_path / "part.json").write_text(json.dumps(
        {"x0": X0, "y0": Y0, "cell": CELL, "tess_tol": 0.01}))
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(npy), "--tool", "ball",
                    "--dia", "6.0", "--stock", "-25", "25", "-25", "25",
                    "0", "20", "--tool-number", "31",
                    "--out-json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["holder"] == {"status": "checked", "name": "BT30-ER20-60",
                             "stickout_mm": 18.0,
                             "dimension_source": "drawing"}
    assert rep["holder_hits"]["count"] == 2
    assert abs(rep["holder_hits"]["max_intrusion"] - 2.0) < 1e-9
    # unknown tool number -> holder check off, reported as "holder unknown"
    out2 = tmp_path / "rep2.json"
    rc = zmap.main([str(gc), "--part", str(npy), "--tool", "ball",
                    "--dia", "6.0", "--stock", "-25", "25", "-25", "25",
                    "0", "20", "--tool-number", "99",
                    "--out-json", str(out2)])
    assert rc == 0
    rep2 = json.loads(out2.read_text())
    assert rep2["holder_hits"] is None
    assert rep2["holder"]["status"] == "holder unknown"


# ---------------------------------------------------------------------------
# Task Z5: zmap must never silently judge less than the whole stock/toolpath
# ---------------------------------------------------------------------------

def _z5_hf(tmp_path, tess_tol=0.01):
    """Part heightfield on the standard grid [-25, 25]^2 + sidecar."""
    import json
    npy = tmp_path / "part.npy"
    np.save(npy, block_part(hi=10.0, half=15.0))
    meta = {"cell": CELL, "x0": X0, "y0": Y0}
    if tess_tol is not None:
        meta["tess_tol"] = tess_tol
    (tmp_path / "part.json").write_text(json.dumps(meta))
    return npy


def _z5_gcode(tmp_path, body):
    gc = tmp_path / "p.ngc"
    gc.write_text("G21 G90 F500\n" + body)
    return gc


def test_z5_stock_beyond_part_grid_fails(tmp_path, capsys):
    """Supervisor case: stock box extends beyond the part grid by more than
    half a cell -> non-zero exit naming both bounds, no report, no bypass."""
    npy = _z5_hf(tmp_path)
    gc = _z5_gcode(tmp_path, "G0 X0. Y0. Z20.\nG1 Z5. F100.\n"
                              "G1 X10. Y0. F500.\n")
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(npy), "--stock",
                    "-25", "25", "-25", "26.7", "0", "10",
                    "--out-json", str(out)])
    assert rc != 0, "stock 1.7 mm beyond grid accepted silently"
    err = capsys.readouterr().err
    assert "stock box" in err and "part grid" in err
    assert "-25.000..25.000" in err and "26.700" in err
    assert not out.exists()


def test_z5_stock_within_half_cell_ok(tmp_path):
    """A stock box overhanging the grid by at most half a cell per side is
    within rounding and must pass."""
    npy = _z5_hf(tmp_path)
    gc = _z5_gcode(tmp_path, "G0 X22. Y0. Z10.\nG1 X0. Y0. Z5. F100.\n"
                             "G1 X10. Y0. F500.\n")
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(npy), "--stock",
                    "-25.25", "25.25", "-25.25", "25.25", "0", "10",
                    "--out-json", str(out)])
    assert rc == 0


def test_z5_footprint_outside_grid_fails(tmp_path, capsys):
    """A move whose footprint (XY +- R) leaves the part grid is counted as
    outside_grid and fails the run; parallel chunking agrees."""
    import json
    npy = _z5_hf(tmp_path)
    gc = _z5_gcode(tmp_path, "G0 X-20. Y0. Z20.\nG1 Z5. F100.\n"
                              "G1 X23. Y0. F500.\n")  # R3 -> x reaches 26 > 25
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(npy), "--stock",
                    "-25", "25", "-25", "25", "0", "10",
                    "--out-json", str(out)])
    assert rc != 0, "footprint 1 mm outside grid accepted silently"
    err = capsys.readouterr().err
    assert "outside the part grid" in err
    rep = json.loads(out.read_text())
    assert rep["outside_grid"]["count"] == 1
    assert rep["outside_grid"]["first_line"] == 4


def test_z5_footprint_outside_grid_parallel_matches(tmp_path):
    npy = _z5_hf(tmp_path)
    gc = _z5_gcode(tmp_path, "G0 X-20. Y0. Z20.\nG1 Z5. F100.\n"
                              "G1 X23. Y0. F500.\n")
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(npy), "--stock",
                    "-25", "25", "-25", "25", "0", "10", "--jobs", "2",
                    "--out-json", str(out)])
    assert rc != 0
    import json
    rep = json.loads(out.read_text())
    assert rep["outside_grid"]["count"] == 1
    assert rep["outside_grid"]["first_line"] == 4


def test_z5_air_rapid_outside_stock_box_counts_when_off_grid(tmp_path):
    """An in-air rapid outside the STOCK box is fine only while it stays
    inside the part grid; leaving the grid counts even in clean air."""
    import json
    part = pocket_part(floor=4.0, top=10.0, half=12.0, block=20.0)
    npy = tmp_path / "part.npy"
    np.save(npy, part)
    (tmp_path / "part.json").write_text(json.dumps(
        {"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}))
    # stock box inset 5 mm inside the grid in +X: rapids over it are air
    gc = _z5_gcode(tmp_path, "G0 X-20. Y0. Z10.\nG1 X0. Y0. Z5. F100.\n"
                              "G1 X10. Y0. F500.\n"     # cuts, all in grid
                              "G0 Z20.\n"
                              "G0 X27. Y0.\n")           # air, off grid (R3 -> 30)
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(npy), "--stock",
                    "-25", "20", "-25", "25", "0", "10",
                    "--out-json", str(out)])
    assert rc != 0, "off-grid air rapid exempted"
    rep = json.loads(out.read_text())
    assert rep["outside_grid"]["count"] == 1
    assert rep["outside_grid"]["first_line"] == 6
    # the same rapid staying inside the grid (X22: footprint to exactly 25)
    # is air outside... still inside the grid -> passes
    gc2 = _z5_gcode(tmp_path, "G0 X-20. Y0. Z10.\nG1 X0. Y0. Z5. F100.\n"
                               "G1 X10. Y0. F500.\n"
                               "G0 Z20.\n"
                               "G0 X22. Y0.\n")
    out2 = tmp_path / "rep2.json"
    rc = zmap.main([str(gc2), "--part", str(npy), "--stock",
                    "-25", "20", "-25", "25", "0", "10",
                    "--out-json", str(out2)])
    assert rc == 0
    assert json.loads(out2.read_text())["outside_grid"]["count"] == 0


def test_z5_tess_tol_gate(tmp_path, capsys):
    """tess_tol missing or > 0.02 in the part sidecar is a hard failure;
    0.01 passes."""
    gc = _z5_gcode(tmp_path, "G0 X22. Y0. Z10.\nG1 X0. Y0. Z5. F100.\n"
                             "G1 X10. Y0. F500.\n")
    stock = ["--stock", "-25", "25", "-25", "25", "0", "10"]
    rc = zmap.main([str(gc), "--part", str(_z5_hf(tmp_path, None))] + stock)
    assert rc != 0, "missing tess_tol accepted"
    assert "tess_tol" in capsys.readouterr().err
    rc = zmap.main([str(gc), "--part", str(_z5_hf(tmp_path, 0.05))] + stock)
    assert rc != 0, "tess_tol 0.05 accepted"
    assert "tess_tol" in capsys.readouterr().err
    rc = zmap.main([str(gc), "--part", str(_z5_hf(tmp_path, 0.01))] + stock)
    assert rc == 0


# ---------------------------------------------------------------------------
# Task Z5b: the shared heightfield builder always covers stock + tool + 5 mm
# ---------------------------------------------------------------------------

import hf_extent  # noqa: E402


def test_z5b_grid_extent_covers_stock_plus_tool_and_margin():
    """Stock-dominant case: grid bounds == stock +- (tool_r + margin),
    cell-aligned outward, and pad_mm records the per-side growth."""
    bbox = (-10.0, 8.0, -6.0, 5.0)
    stock = [-20.0, 20.0, -15.0, 15.0]
    tool_r, margin, cell = 6.35, 5.0, 0.5
    ext = hf_extent.grid_extent(bbox, stock_box=stock, tool_r=tool_r,
                                 margin=margin, cell=cell)
    grow = tool_r + margin
    gxmin, gxmax, gymin, gymax = ext["grid_bounds"]
    assert gxmin == stock[0] - grow                    # exact on cell 0.5
    assert gxmax >= stock[1] + grow and gxmax < stock[1] + grow + cell
    assert gymin == stock[2] - grow
    assert gymax >= stock[3] + grow and gymax < stock[3] + grow + cell
    assert ext["x0"] == gxmin and ext["y0"] == gymin
    assert ext["nx"] == round((gxmax - gxmin) / cell)
    assert ext["ny"] == round((gymax - gymin) / cell)
    # pad_mm: distance from the part bbox to each grid edge, >= grow
    p = ext["pad_mm"]
    assert abs(p["xmin"] - (bbox[0] - gxmin)) < 1e-9
    assert abs(p["xmax"] - (gxmax - bbox[1])) < 1e-9
    assert all(v >= grow - 1e-9 for v in p.values())


def test_z5b_grid_extent_part_dominant_and_pad_legacy():
    """Part bigger than stock+growth: grid stays on the part bbox; PAD-only
    callers keep the old behaviour (bbox grown per side)."""
    bbox = (-30.0, 30.0, -30.0, 30.0)
    stock = [-20.0, 20.0, -20.0, 20.0]
    ext = hf_extent.grid_extent(bbox, stock_box=stock, tool_r=3.0,
                                 margin=5.0, cell=0.5)
    assert ext["x0"] == -30.0 and ext["y0"] == -30.0
    assert ext["grid_bounds"] == [-30.0, 30.0, -30.0, 30.0]
    assert ext["pad_mm"] == {"xmin": 0.0, "xmax": 0.0,
                             "ymin": 0.0, "ymax": 0.0}
    # legacy PAD path (no stock box): exactly the old rasterize geometry
    ext2 = hf_extent.grid_extent(bbox, pad=8.0, cell=0.5)
    assert ext2["x0"] == -38.0 and ext2["y0"] == -38.0
    assert ext2["nx"] == int(math.ceil((76.0) / 0.5))
    assert ext2["grid_bounds"][1] == 38.0
    # no stock box, no pad: tight part bbox (old default)
    ext3 = hf_extent.grid_extent(bbox, cell=0.5)
    assert ext3["grid_bounds"] == [-30.0, 30.0, -30.0, 30.0]


def test_z5b_parse_stock_box():
    assert hf_extent.parse_stock_box("-1 2 -3 4") == [-1.0, 2.0, -3.0, 4.0]
    assert hf_extent.parse_stock_box(None) is None
    assert hf_extent.parse_stock_box("") is None
    for bad in ("-1 2 -3", "-1 2 -3 4 5", "1 0 -3 4", "-1 -2 3 4"):
        try:
            hf_extent.parse_stock_box(bad)
            assert False, "bad STOCK_BOX accepted: %r" % bad
        except SystemExit:
            pass


def test_z5b_heightfield_rasterize_sidecar(tmp_path, monkeypatch):
    """Fake rasteriser (no FreeCAD): rasterize with STOCK_BOX produces a
    grid covering stock + tool_r + margin; sidecar meta records stock_box,
    tool_r, margin, pad_mm per side and grid_bounds; outer cells are the
    zmin floor. PAD-only callers keep the old meta shape (stock_box null)."""
    import json
    import types
    sys.modules.setdefault("FreeCAD", types.ModuleType("FreeCAD"))
    sys.modules.setdefault("Part", types.ModuleType("Part"))
    import heightfield

    class _FakeShape:
        """Flat square top at z=10 over [-10, 8] x [-6, 5]."""
        BoundBox = types.SimpleNamespace(XMin=-10.0, XMax=8.0,
                                          YMin=-6.0, YMax=5.0,
                                          ZMin=0.0, ZMax=10.0)

        def tessellate(self, tol):
            v = [types.SimpleNamespace(x=x, y=y, z=10.0)
                 for x, y in ((-10.0, -6.0), (8.0, -6.0),
                              (8.0, 5.0), (-10.0, 5.0))]
            return v, [(0, 1, 2), (0, 2, 3)]

    cell = 0.5
    stock = [-20.0, 20.0, -15.0, 15.0]
    tool_r, margin = 6.35, 5.0
    hf, meta = heightfield.rasterize(_FakeShape(), cell=cell, tol=0.01,
                                      stock_box=stock, tool_r=tool_r,
                                      margin=margin)
    grow = tool_r + margin
    gxmin, gxmax, gymin, gymax = meta["grid_bounds"]
    assert gxmin <= stock[0] - grow and gxmax >= stock[1] + grow
    assert gymin <= stock[2] - grow and gymax >= stock[3] + grow
    assert meta["x0"] == gxmin and meta["y0"] == gymin
    assert hf.shape == (meta["ny"], meta["nx"])
    assert meta["stock_box"] == stock
    assert meta["tool_r"] == tool_r
    assert meta["margin"] == margin
    for side, need in (("xmin", stock[0] - grow - gxmin),
                       ("xmax", gxmax - (stock[1] + grow))):
        assert meta["pad_mm"][side] >= need
    # geometry lands where it should; the grown ring is part-free = zmin
    i_part = int((0.0 - gxmin) / cell)
    j_part = int((0.0 - gymin) / cell)
    assert hf[j_part, i_part] == 10.0
    assert hf[0, 0] == 0.0 and hf[-1, -1] == 0.0
    # sidecar written through the same meta keeps every new field
    npy = tmp_path / "part_hf.npy"
    np.save(npy, hf)
    with open(str(npy).replace(".npy", ".json"), "w") as f:
        json.dump(meta, f)
    side = json.loads((tmp_path / "part_hf.json").read_text())
    for key in ("stock_box", "tool_r", "margin", "pad_mm", "grid_bounds"):
        assert key in side


def test_z5b_heightfield_get_args(monkeypatch):
    """Env and flag forms of the new inputs; PAD stays for old callers."""
    import types
    sys.modules.setdefault("FreeCAD", types.ModuleType("FreeCAD"))
    sys.modules.setdefault("Part", types.ModuleType("Part"))
    import heightfield

    for k in ("STEP_IN", "HF_OUT", "CELL", "PAD", "STOCK_BOX", "TOOL_R",
              "MARGIN"):
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setattr(sys, "argv", ["heightfield.py"])
    monkeypatch.setenv("STEP_IN", "a.step")
    monkeypatch.setenv("HF_OUT", "hf.npy")
    monkeypatch.setenv("STOCK_BOX", "-20 20 -15 15")
    monkeypatch.setenv("TOOL_R", "6.35")
    step, out, cell, pad, sb, tr, mg = heightfield.get_args()
    assert (step, out) == ("a.step", "hf.npy")
    assert sb == [-20.0, 20.0, -15.0, 15.0]
    assert tr == 6.35 and mg == 5.0 and pad == 0.0

    monkeypatch.setattr(sys, "argv", ["heightfield.py", "a.step", "hf.npy",
                                       "0.1", "2.0", "--stock-box",
                                       "-30", "30", "-25", "25",
                                       "--tool-r", "8", "--margin", "7"])
    step, out, cell, pad, sb, tr, mg = heightfield.get_args()
    assert (step, out, cell, pad) == ("a.step", "hf.npy", 0.1, 2.0)
    assert sb == [-30.0, 30.0, -25.0, 25.0]
    assert tr == 8.0 and mg == 7.0

    # no stock box: old caller path, everything defaults
    monkeypatch.delenv("STOCK_BOX")
    monkeypatch.delenv("TOOL_R")
    monkeypatch.setattr(sys, "argv", ["heightfield.py"])
    step, out, cell, pad, sb, tr, mg = heightfield.get_args()
    assert sb is None and tr == 0.0 and mg == 5.0


def test_z5b_builder_grid_satisfies_zmap_stock_gate(tmp_path):
    """End-to-end on synthetic arrays: a zmap run whose stock exceeded the
    old tight grid now passes when judged on a builder-sized grid, while an
    un-grown grid still fails (the zmap gate itself is untouched)."""
    import json
    part = block_part(hi=10.0, half=15.0)  # part bbox [-25,25]^2 on std grid
    gc = _z5_gcode(tmp_path, "G0 X-15. Y0. Z10.\nG1 X5. Y0. Z5. F100.\n"
                              "G1 X23. Y0. F500.\n")
    stock = [-25.0, 25.0, -25.0, 28.0, 0.0, 10.0]  # 3 mm past the std grid
    stock_args = ["--stock"] + [str(v) for v in stock]
    tight = tmp_path / "tight.npy"
    np.save(tight, part)
    (tmp_path / "tight.json").write_text(json.dumps(
        {"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}))
    out = tmp_path / "rep.json"
    assert zmap.main([str(gc), "--part", str(tight)] + stock_args
                     + ["--out-json", str(out)]) != 0, \
        "tight grid must still fail the stock gate"

    # builder-sized grid: stock + tool_r(3) + margin(5), cell-aligned
    ext = hf_extent.grid_extent((X0, X0 + N * CELL, Y0, Y0 + N * CELL),
                                 stock_box=stock[:4], tool_r=3.0, margin=5.0,
                                 cell=CELL)
    grown = np.full((ext["ny"], ext["nx"]), 0.0)
    j0 = int(round((Y0 - ext["y0"]) / CELL))
    i0 = int(round((X0 - ext["x0"]) / CELL))
    grown[j0:j0 + N, i0:i0 + N] = part
    big = tmp_path / "grown.npy"
    np.save(big, grown)
    (tmp_path / "grown.json").write_text(json.dumps(
        {"cell": CELL, "x0": ext["x0"], "y0": ext["y0"],
         "tess_tol": 0.01, "stock_box": stock[:4], "tool_r": 3.0,
         "margin": 5.0, "pad_mm": ext["pad_mm"],
         "grid_bounds": ext["grid_bounds"]}))
    out2 = tmp_path / "rep2.json"
    rc = zmap.main([str(gc), "--part", str(big)] + stock_args
                   + ["--out-json", str(out2)])
    assert rc == 0, "builder grid must satisfy the stock + footprint gates"
    rep = json.loads(out2.read_text())
    assert rep["outside_grid"]["count"] == 0



# ============================================= task CP: --strict subset ====

STRICT_OK = """O1001
( posted program, supported subset )
G21 G90 G17 G40 G80 G49 G94
G54
T13 M06
G43 Z25. H13 M03 S7500 M08
G0 X-15. Y0. Z10.
G1 X5. Y0. Z5. F300.
G1 X-20. Y0. F1500.
G2 X0. Y20. I20. J0. F1500.
G3 X20. Y0. R20.
G04 P2000.
G1 X-20. Y0. F1500.
G0 Z25.
M09
M05
G53 G00 Z0.
G49
G91 G28 X0. Y0.
G90
M30
%
"""


def codes_of(findings):
    return [(f["code"], f["line"]) for f in findings]


def test_strict_accepts_supported_subset():
    assert zmap.strict_check(STRICT_OK) == []


@pytest.mark.parametrize("line,code", [
    ("G18", "G18"),
    ("G19", "G19"),
    ("G41", "G41"),
    ("G42", "G42"),
    ("G81 Z-5. R2.", "G81"),
    ("G82 Z-5. P1000.", "G82"),
    ("G83 Z-5. Q2.", "G83"),
    ("G84", "G84"),
    ("G85 Z-5.", "G85"),
    ("G86 Z-5.", "G86"),
    ("G87 Z-5.", "G87"),
    ("G88 Z-5.", "G88"),
    ("G89 Z-5.", "G89"),
    ("G91 X5.", "G91"),
    ("G68", "G68"),
    ("G51", "G51"),
    ("M98 P1001", "M98"),
    ("M99", "M99"),
    ("#5=1", "#"),
    ("U5.", "U"),
    ("D3", "D"),
])
def test_strict_rejects_every_unsupported_code(line, code):
    text = "G21 G90\nG0 X0. Y0.\n%s\n" % line
    findings = zmap.strict_check(text)
    assert codes_of(findings), "must not skip %r silently" % line
    assert findings[0]["code"] == code
    assert findings[0]["line"] == 3


def test_strict_rejects_comp_and_planes_in_program():
    text = ("G21 G90\nG1 X0. Y0. F500.\nG41 X10. D3 F500.\n"
            "G18\nG2 X20. Z0. I10. K0.\n")
    codes = [f["code"] for f in zmap.strict_check(text)]
    assert "G41" in codes and "D" in codes and "G18" in codes
    assert "K" in codes


def test_strict_home_line_only_at_end():
    home = "G91 G28 X0. Y0."
    assert zmap.strict_check("G21\n%s\nM30\n%%\n" % home) == []
    # a cutting move after the home line: the home line was not at the end
    bad = "G21\n%s\nG1 X5. Y5. F100.\nM30\n" % home
    findings = zmap.strict_check(bad)
    assert ("G28", 2) in codes_of(findings)


def test_strict_g53_z_only_ok_axes_rejected():
    assert zmap.strict_check("G21\nG53 G00 Z0.\n") == []
    findings = zmap.strict_check("G21\nG53 G00 X0. Y0. Z0.\n")
    assert ("G53", 2) in codes_of(findings)


def test_strict_g43_needs_h_and_dwell_needs_p():
    findings = zmap.strict_check("G21\nG43 Z5.\n")
    assert ("G43", 2) in codes_of(findings)
    findings = zmap.strict_check("G21\nG0 X0.\nP1000.\n")
    assert ("P", 3) in codes_of(findings)


def test_strict_r_smaller_than_chord_rejected():
    findings = zmap.strict_check("G21 G90\nG0 X0. Y0.\n"
                                  "G1 X20. Y0.\nG2 X0. Y0. R5.\n")
    assert ("R", 4) in codes_of(findings)


def test_strict_cli_rejects_with_json(tmp_path):
    gc = tmp_path / "p.nc"
    gc.write_text("G21 G90\nG0 X0. Y0.\nG81 Z-5. R2. F100.\n"
                  "G41 X5. D1\n")
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(tmp_path / "none.npy"),
                    "--strict", "--out-json", str(out)])
    assert rc != 0, "unsupported program must exit non-zero"
    rep = json.loads(out.read_text())
    codes = [f["code"] for f in rep["unsupported"]]
    assert codes[0] == "G81" and "G41" in codes
    assert rep["unsupported"][0]["line"] == 3


def test_strict_cli_ok_and_reports(tmp_path):
    gc = tmp_path / "p.nc"
    gc.write_text(STRICT_OK)
    part = np.full((100, 100), 5.0)
    p = tmp_path / "part.npy"
    np.save(p, part)
    (tmp_path / "part.json").write_text(json.dumps(
        {"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}))
    out = tmp_path / "rep.json"
    rc = zmap.main([str(gc), "--part", str(p), "--stock", "-25", "25",
                    "-25", "25", "0", "10", "--tool", "flat", "--dia", "6",
                    "--strict", "--engage-report", "--out-json", str(out)])
    assert rc == 0, "supported program must pass --strict"
    rep = json.loads(out.read_text())
    assert rep["strict"] is True and rep["unsupported"] == []
    # report-only engagement: present, no threshold, nothing flagged
    assert rep["engagement"]["threshold_mm"] is None
    assert rep["engagement"]["count"] == 0


def _arc_compare_programs(R=10.0):
    """(I/J form, R form, finely linearized G1) of the same CW semicircle
    from (R,0) to (-R,0), chord <= 0.01 mm on the linear form."""
    head = "G21 G90 F500\nG0 X%.3f Y0. Z20.\nG1 Z5. F100.\n" % R
    tail = "\nG0 Z20.\nM30\n"
    ij = head + "G2 X%.3f Y0. I-%.3f J0. F500." % (-R, R) + tail
    rr = head + "G2 X%.3f Y0. R%.3f F500." % (-R, R) + tail
    n = int(math.ceil(math.pi * R / 0.01))
    pts = []
    for k in range(1, n + 1):
        a = -math.pi * k / n
        pts.append("G1 X%.5f Y%.5f F500." % (R * math.cos(a),
                                               R * math.sin(a)))
    lin = head + "\n".join(pts) + tail
    return ij, rr, lin


def test_r_form_and_ij_form_match_fine_linearization():
    Rpath, Rtool = 10.0, 3.0
    xs = centers()[None, :]
    ys = centers()[:, None]
    r = np.hypot(xs, ys)
    part = np.where((r >= Rpath - Rtool) & (r <= Rpath + Rtool), 5.0, 10.0)
    ij, rr, lin = _arc_compare_programs(Rpath)
    res_ij = run(ij, part)
    res_r = run(rr, part)
    res_lin = run(lin, part)
    for key in ("gouges", "rapid_collisions"):
        assert res_r[key]["count"] == res_ij[key]["count"] == \
            res_lin[key]["count"], key
    assert res_ij["gouges"]["count"] == 0
    assert res_r["leftover"]["max"] == pytest.approx(
        res_lin["leftover"]["max"], abs=1e-6)
    assert res_r["leftover"]["mean"] == pytest.approx(
        res_lin["leftover"]["mean"], abs=1e-3)
    assert res_ij["leftover"]["mean"] == pytest.approx(
        res_lin["leftover"]["mean"], abs=1e-3)
    assert abs(res_r["cutting_length_mm"] - res_lin["cutting_length_mm"]) \
        < 0.05


def test_negative_r_over_180_matches_linearization():
    # 270 deg CW arc from (-10,0) to (0,-10): negative R in the R form
    Rpath, Rtool = 10.0, 3.0
    xs = centers()[None, :]
    ys = centers()[:, None]
    r = np.hypot(xs, ys)
    part = np.where((r >= Rpath - Rtool) & (r <= Rpath + Rtool), 5.0, 10.0)
    head = "G21 G90 F500\nG0 X-10. Y0. Z20.\nG1 Z5. F100.\n"
    rr = head + "G2 X0. Y-10. R-10. F500.\nG0 Z20.\n"
    n = int(math.ceil(1.5 * math.pi * Rpath / 0.01))
    pts = []
    for k in range(1, n + 1):
        a = math.pi - 1.5 * math.pi * k / n
        pts.append("G1 X%.5f Y%.5f F500." % (Rpath * math.cos(a),
                                               Rpath * math.sin(a)))
    lin = head + "\n".join(pts) + "\nG0 Z20.\n"
    res_r = run(rr, part)
    res_lin = run(lin, part)
    assert res_r["gouges"]["count"] == res_lin["gouges"]["count"]
    assert res_r["rapid_collisions"]["count"] == \
        res_lin["rapid_collisions"]["count"]
    assert res_r["leftover"]["mean"] == pytest.approx(
        res_lin["leftover"]["mean"], abs=1e-3)


def test_strict_skips_home_and_dwell_moves():
    moves = zmap.parse_gcode(STRICT_OK, strict=True)
    assert all(not (m["x"] == 0.0 and m["y"] == 0.0
                   and m["motion"] == "G1") for m in moves)
    # default behaviour unchanged: home line still parses as before
    dflt = zmap.parse_gcode("G91 G28 X0. Y0.\n")
    assert len(dflt) == 1


# =========================================================== task ZA: axial plunges ==

def test_axial_flat_plunge_into_solid_fails(tmp_path):
    """A straight vertical G1 descent driving a flat bottom into solid stock
    is an axial plunge: counted, and the CLI exits non-zero for flat/bull."""
    part = block_part(hi=10.0, half=15.0)
    res = run("""
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z0.5 F100.
G1 X10. Y0. F500.
""", part, tool="flat", dia=6.0)
    ap = res["axial_plunges"]
    assert ap["count"] == 1, ap
    assert abs(ap["max_depth_mm"] - 9.5) < 1e-6, ap
    assert ap["first_line"] == 4, ap
    assert ap["worst_xy"] == [0.0, 0.0], ap

    rc = _axial_cli(tmp_path, part, tool="flat", dia=6.0, body="""
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z0.5 F100.
G1 X10. Y0. F500.
""")
    assert rc == 1, "flat plunge must fail the run"


def test_axial_steep_diagonal_entry_into_solid_fails(tmp_path):
    """Task ZA2: a 71 deg straight diagonal into the block (G0 X5 Y0 Z20
    then G1 X0 Y0 Z5) is a disguised plunge (steeper than MAX_RAMP_DEG):
    counted, and the flat run FAILS."""
    part = block_part(hi=10.0, half=15.0)
    body = """
G21 G90 F500
G0 X5. Y0. Z20.
G1 X0. Y0. Z5. F100.
"""
    res = run(body, part, tool="flat", dia=6.0)
    ap = res["axial_plunges"]
    assert ap["count"] == 1, ap  # atan(15/5) = 71.6 deg > 15
    assert abs(ap["max_depth_mm"] - 5.0) < 1e-6, ap
    assert ap["first_line"] == 4, ap  # G21 line 2, G0 line 3, G1 line 4
    rc = _axial_cli(tmp_path, part, tool="flat", dia=6.0, body=body)
    assert rc == 1, "steep diagonal entry into solid stock must FAIL"


def test_axial_descent_into_cleared_pocket_passes(tmp_path):
    """Task ZA2: a straight descent into an area already cleared by an
    earlier side-entry pass (stock down to the floor there) removes nothing
    under the flat bottom: no axial plunge, exit 0."""
    part = block_part(hi=10.0, half=15.0)
    sb = (-15.0, 15.0, -15.0, 15.0, 0.0, 10.0)  # stock = part footprint
    body = """
G21 G90 F500
G0 X20. Y0. Z20.
G1 Z4. F100.
G1 X-12. Y0. Z4. F500.
G0 Z20.
G0 X0. Y0.
G1 Z4. F100.
G1 X6. Y0. F500.
"""
    moves = zmap.parse_gcode(body)
    res = zmap.simulate(moves, part, CELL, X0, Y0, sb, tool="flat",
                        dia=6.0)
    assert res["axial_plunges"]["count"] == 0, res["axial_plunges"]
    rc = _axial_cli(tmp_path, part, tool="flat", dia=6.0, body=body,
                    stock=sb)
    assert rc == 0, "descent into an already-cleared area must pass"


def test_axial_helix_entry_into_solid_passes(tmp_path):
    """Task ZA2: a 2 deg helical G2 full circle (I/J form, Z drop over one
    turn) into the solid block is a legitimate ramped entry (<= MAX_RAMP_DEG,
    angle measured from the arc length): no axial plunge, exit 0."""
    part = block_part(hi=10.0, half=15.0)
    drop = 2.0 * math.pi * 10.0 * math.tan(math.radians(2.0))  # 2.195 mm
    body = """
G21 G90 G17 F500
G0 X-10. Y0. Z11.5.
G2 X-10. Y0. Z%.3f I10. J0. F200.
G1 X10. Y0. F500.
""" % (11.5 - drop)
    res = run(body, part, tool="flat", dia=6.0)
    assert res["axial_plunges"]["count"] == 0, res["axial_plunges"]
    # the helix really cut into the block (not an air move)
    assert res["stock"].min() < 10.0 - 1e-6
    rc = _axial_cli(tmp_path, part, tool="flat", dia=6.0, body=body)
    assert rc == 0, "helical entry at 2 deg must pass the axial gate"


def test_axial_helix_30deg_into_solid_fails(tmp_path):
    """Task ZA2: a 30 deg helical arc into the block is steeper than
    MAX_RAMP_DEG=15: counted as an axial plunge, the flat run FAILS."""
    part = block_part(hi=10.0, half=15.0)
    drop = math.tan(math.radians(30.0)) * math.pi * 10.0 / 2.0  # 9.063 mm
    body = """
G21 G90 G17 F500
G0 X-10. Y0. Z10.5.
G2 X0. Y10. Z%.3f I10. J0. F200.
""" % (10.5 - drop)
    res = run(body, part, tool="flat", dia=6.0)
    ap = res["axial_plunges"]
    assert ap["count"] == 1, ap
    assert ap["first_line"] == 4, ap
    rc = _axial_cli(tmp_path, part, tool="flat", dia=6.0, body=body)
    assert rc == 1, "30 deg helix into solid stock must FAIL"


def test_axial_helix_g1_segments_2deg_passes(tmp_path):
    """Task ZA2: a 2 deg helix linearized into short G1 segments into the
    block: every segment is a ramp at 2 deg <= MAX_RAMP_DEG, so no axial
    plunge even though it descends into solid stock."""
    part = block_part(hi=10.0, half=15.0)
    drop = 2.0 * math.pi * 10.0 * math.tan(math.radians(2.0))
    lines = ["G21 G90 F500", "G0 X-10. Y0. Z11.5."]
    n = 36
    for k in range(1, n + 1):
        a = math.pi + 2.0 * math.pi * k / n
        lines.append("G1 X%.4f Y%.4f Z%.4f F200."
                     % (10.0 * math.cos(a), 10.0 * math.sin(a),
                       11.5 - drop * k / n))
    body = "\n".join(lines) + "\n"
    res = run(body, part, tool="flat", dia=6.0)
    assert res["axial_plunges"]["count"] == 0, res["axial_plunges"]
    assert res["stock"].min() < 10.0 - 1e-6  # really entered the block
    rc = _axial_cli(tmp_path, part, tool="flat", dia=6.0, body=body)
    assert rc == 0, "2 deg helix of short G1 segments must pass"


def test_axial_ball_plunge_counted_not_failing(tmp_path):
    """A ball plunge into solid stock is counted (report-only) but does not
    fail the run: zmap exits 0 for ball."""
    part = block_part(hi=10.0, half=15.0)
    res = run("""
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z0.5 F100.
G1 X10. Y0. F500.
""", part, tool="ball", dia=6.0, corner=3.0)
    ap = res["axial_plunges"]
    assert ap["count"] == 1, ap
    assert ap["max_depth_mm"] > 9.0, ap
    rc = _axial_cli(tmp_path, part, tool="ball", dia=6.0, corner=3.0, body="""
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z0.5 F100.
G1 X10. Y0. F500.
""")
    assert rc == 0, "ball axial plunge is report-only, never fails"


def _axial_cli(tmp_path, part, tool, dia, body, corner=0.0, stock=None):
    """Write a part heightfield + gcode and run zmap.main; return its code."""
    import tempfile
    hf = tmp_path / "part.npy"
    np.save(hf, part)
    with open(tmp_path / "part.json", "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    gc = tmp_path / "prog.ngc"
    gc.write_text(body)
    out = tmp_path / "check.json"
    return zmap.main([str(gc), "--part", str(hf), "--tool", tool,
                      "--dia", "%.4f" % dia, "--corner", "%.4f" % corner,
                      "--stock", *[str(v) for v in (stock or STOCK)],
                      "--out-json", str(out)])


def test_axial_parallel_matches_serial_count():
    """--jobs merges axial plunges exactly like the serial run."""
    part = block_part(hi=10.0, half=15.0)
    gcode = """
G21 G90 F500
G0 X0. Y0. Z20.
G1 Z0.5 F100.
G1 X10. Y0. F500.
G0 X10. Y10. Z20.
G1 Z0.2 F100.
"""
    moves = zmap.parse_gcode(gcode)
    serial = zmap.simulate(moves, part, CELL, X0, Y0, STOCK, tool="flat",
                          dia=6.0)
    par = zmap.simulate_parallel(zmap.parse_gcode(gcode), part, CELL, X0,
                                 Y0, STOCK, 4, tool="flat", dia=6.0)
    assert par["axial_plunges"]["count"] == serial["axial_plunges"]["count"]
    assert abs(par["axial_plunges"]["max_depth_mm"]
              - serial["axial_plunges"]["max_depth_mm"]) < 1e-9


def test_axial_real_core_front_rough_fails():
    """Task ZA/ZA2 real case: zmap on out/core_front_roughRT_before.ngc (the
    current Core Front T13 flat rough, D=12.686) FAILS with 489 axial
    plunges (worst 25.654 mm at XY -2.593, -52.230, first line 63675).
    The measured removed-depth distribution is bimodal: 14 stepdown
    re-entries of 1.12-1.62 mm and 475 solid-stock plunges of 10.16-25.65
    mm; both are axial removal under the flat bottom and both exceed
    AXIAL_FLOOR=0.2, so the 1.1-1.6 mm re-entries count too (489 total;
    see zmap.py)."""
    import json
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gc = os.path.join(repo, "out", "core_front_roughRT_before.ngc")
    part = os.path.join(repo, "out", "cf_hf01_z5b.npy")
    out = os.path.join(repo, "out", "_za_check.json")
    try:
        rc = zmap.main([gc, "--part", part, "--tool", "flat",
                        "--dia", "12.686", "--stock",
                        "-128.651", "128.651", "-82.55", "82.55",
                        "0", "60.96", "--jobs", "8", "--out-json", out])
        assert rc == 1, "flat rough plunging into solid stock must FAIL"
        rep = json.load(open(out))
        ap = rep["axial_plunges"]
        assert ap["count"] == 489, "exact axial plunge count: %r" % (ap,)
        assert abs(ap["max_depth_mm"] - 25.654) < 1e-3, ap
        assert ap["first_line"] == 63675, ap
    finally:
        if os.path.exists(out):
            os.unlink(out)


# ---------------------------------------------------------------------------
# Task ZE2F: ae2 windows carry their feed; full-width split by cutting vs
# entry feed; entry-feed full-width allowed only right after a helix with
# a <= that helix's measured pitch + AE2_PITCH_TOL. Report-only.
# ---------------------------------------------------------------------------

def _helix_gcode(cx, cy, r, z0, pitch, turns, feed=1270.0, seg=72):
    lines = ["G21 G90",
             "G0 X%.4f Y%.4f Z20." % (cx + r, cy),
             "G1 X%.4f Y%.4f Z%.4f F%.1f" % (cx + r, cy, z0, feed)]
    for k in range(1, int(seg * turns) + 1):
        a = 2.0 * math.pi * k / seg
        lines.append("G1 X%.4f Y%.4f Z%.4f F%.1f" % (
            cx + r * math.cos(a), cy + r * math.sin(a), z0 - pitch * k / seg,
            feed))
    return lines


def test_ze2f_helix_pitch_measured_and_plunge_is_none():
    run = [(3.0 * math.cos(2 * math.pi * k / 72), 3.0 * math.sin(2 * math.pi * k / 72),
            18.6 - 0.8 * k / 72) for k in range(0, 3 * 72 + 1)]
    assert abs(zmap._helix_pitch(run) - 0.8) <= 0.02
    assert zmap._helix_pitch([(0.0, 0.0, 18.6 - 0.5 * k) for k in range(6)]) is None
    assert zmap._helix_pitch(run[:3]) is None


def test_ze2f_window_after_helix_carries_pitch_and_feed_breaks():
    """A real helix (r 3, pitch 1.0, 2 turns) then horizontal feeds: the
    first window after the helix carries helix_pitch ~1.0 and the entry feed;
    a feed change at the same Z and direction starts a new window without a
    pitch."""
    part = np.zeros((NF, NF))
    g = _helix_gcode(0.0, 0.0, 3.0, 18.6, 1.0, 2)
    g += ["G1 X%.4f Y0. F1270." % (3.0 + 0.2 * i) for i in range(1, 7)]
    g += ["G1 X%.4f Y0. F3429." % (4.2 + 0.2 * i) for i in range(1, 7)]
    res = _run_ae2("\n".join(g) + "\n", part)
    wins = res["_ae2_raw"]
    assert len(wins) == 2, wins
    assert wins[0]["feed"] == 1270.0 and wins[1]["feed"] == 3429.0
    assert abs(wins[0]["helix_pitch"] - 1.0) <= 0.03
    assert wins[1]["helix_pitch"] is None


def test_ze2f_fw_split_by_feed_and_helix_bottom_exception():
    """Crafted windows: cutting feed = the feed with most travel. A cutting
    full-width window is always a finding; an entry-feed one is allowed only
    with a helix pitch and a <= pitch + 0.05."""
    def w(feed, a, pitch, length=1.0, ae=12.6):
        return {"line": 1, "x": 0.0, "y": 0.0, "z": 0.0, "ae_eff": ae, "a": a,
                "width_mm": 12.686, "length_mm": length, "feed": feed,
                "helix_pitch": pitch}
    wins = [w(3429.0, 0.0, None, length=50.0, ae=1.0),  # bulk cutting travel
            w(3429.0, 7.0, None),          # cutting-feed FW -> finding
            w(1270.0, 1.04, 1.0),          # helix bottom within pitch -> allowed
            w(1270.0, 1.2, 1.0),           # deeper than the pitch -> finding
            w(1270.0, 0.9, None)]          # entry feed, no helix -> finding
    k = zmap._ae2_engagement_keys(wins, 12.686)
    assert k["ae2_cutting_feed"] == 3429.0
    assert k["full_width_slots_ae2"]["count"] == 4       # unchanged ZE2 key
    assert k["full_width_slots_ae2_cutting_feed"]["count"] == 1
    ent = k["full_width_slots_ae2_entry_feed"]
    assert ent["count"] == 3 and ent["allowed_helix_bottom"] == 1
    assert ent["not_allowed"]["count"] == 2
    t = k["roughing_target_ae2"]
    assert t == {"fw_cutting_feed": 1, "fw_entry_not_allowed": 2, "met": False}
    clean = [wins[0], wins[2]]
    assert zmap._ae2_engagement_keys(clean, 12.686)["roughing_target_ae2"]["met"]


def test_ze2l_floor_circle_judged_by_load():
    """ZE2L (James 2026-10-27, judge by load): a helix-bottom window (pitch
    carried) leaves overload_feeds_ae2_load only with a <= pitch + 0.05 AND
    load = ae_eff x a x feed / (2.032 x 19.05 x cutting feed) <= 1.2; the raw
    overload_feeds_ae2 count is unchanged; every other window keeps the ae2
    rule. Same windows drive the full-width entry-feed class."""
    def w(feed, a, pitch, length=1.0, ae=12.6):
        return {"line": 1, "x": 0.0, "y": 0.0, "z": 0.0, "ae_eff": ae, "a": a,
                "width_mm": 12.686, "length_mm": length, "feed": feed,
                "helix_pitch": pitch}
    bulk = w(3429.0, 0.0, None, length=50.0, ae=1.0)   # sets the cutting feed
    ok = w(1270.0, 1.04, 1.0)          # floor turn: within pitch, load ~0.125
    heavy = w(3000.0, 10.0, 10.0)      # within its pitch but load ~2.85
    deep = w(1270.0, 1.2, 1.0)         # deeper than pitch + 0.05, load ~0.14
    slot = w(3429.0, 7.0, None)        # non-entry full-width at cutting feed
    k = zmap._ae2_engagement_keys([bulk, ok, heavy, deep, slot], 12.686,
                                  load_rule=True)
    assert abs(ok["load"] - 0.1250) < 0.002 and heavy["load"] > 2.8, \
        (ok["load"], heavy["load"])
    assert k["overload_feeds_ae2"]["count"] == 4          # raw rule unchanged
    L = k["overload_feeds_ae2_load"]
    assert L["raw_count"] == 4 and L["floor_circles_allowed"] == 1 \
        and L["count"] == 3, L
    ent = k["full_width_slots_ae2_entry_feed"]
    assert ent["allowed_helix_bottom"] == 1 and ent["not_allowed"]["count"] == 2
    assert k["full_width_slots_ae2_cutting_feed"]["count"] == 1   # slot fails
    # the design stepdown is honoured: at 1 mm the same floor turn is 19x the
    # load (~2.38 > 1.2) and stops being allowed
    k1 = zmap._ae2_engagement_keys([bulk, ok], 12.686, design_stepdown=1.0,
                                   load_rule=True)
    assert k1["overload_feeds_ae2_load"]["floor_circles_allowed"] == 0
    # opt-in: without --load-rule the report has no new key (JSON unchanged)
    assert "overload_feeds_ae2_load" not in zmap._ae2_engagement_keys(
        [bulk, ok], 12.686)


def test_ze2f2_pitch_carries_along_the_helix_bottom_run():
    """ZE2F2: after a helix, every window of the contiguous run at its bottom
    Z and entry feed (a floor circle) carries the helix pitch; the first move
    at a different feed (or any Z change) drops it."""
    part = np.zeros((NF, NF))
    g = _helix_gcode(0.0, 0.0, 3.0, 18.6, 1.0, 2)
    zb = 18.6 - 2.0
    g += ["G1 X%.4f Y%.4f Z%.4f F1270." % (3.0 * math.cos(2 * math.pi * k / 72), 3.0 * math.sin(2 * math.pi * k / 72), zb)
          for k in range(1, 73)]                      # one full circle at the bottom, entry feed
    g += ["G1 X%.4f Y0. F3429." % (3.0 + 0.2 * i) for i in range(1, 7)]
    res = _run_ae2("\n".join(g) + "\n", part)
    wins = res["_ae2_raw"]
    circ = [w for w in wins if w["feed"] == 1270.0]
    cutw = [w for w in wins if w["feed"] == 3429.0]
    assert len(circ) >= 10 and cutw, (len(circ), len(cutw))
    assert all(w["helix_pitch"] is not None and abs(w["helix_pitch"] - 1.0) <= 0.03 for w in circ), \
        [w["helix_pitch"] for w in circ]
    assert all(w["helix_pitch"] is None for w in cutw)


def test_ze2f2_carry_is_bounded_to_one_circle():
    """ZE2F2 bound: an entry-feed run at the helix bottom LONGER than one
    circumference (+1 mm) loses the pitch beyond that length - those windows
    are judged as normal windows."""
    part = np.zeros((NF, NF))
    g = _helix_gcode(0.0, 0.0, 3.0, 18.6, 1.0, 2)
    zb = 18.6 - 2.0
    g += ["G1 X%.4f Y%.4f Z%.4f F1270." % (3.0 * math.cos(2 * math.pi * k / 72), 3.0 * math.sin(2 * math.pi * k / 72), zb)
          for k in range(1, 3 * 72 + 1)]              # THREE circles at the bottom, entry feed
    res = _run_ae2("\n".join(g) + "\n", part)
    wins = [w for w in res["_ae2_raw"] if w["feed"] == 1270.0]
    carried = sum(w["length_mm"] for w in wins if w["helix_pitch"] is not None)
    uncarried = [w for w in wins if w["helix_pitch"] is None]
    assert carried <= 2 * math.pi * 3.0 + 1.0 + 1.1, carried   # one circle + 1 mm (+ one window)
    assert uncarried and sum(w["length_mm"] for w in uncarried) > 2 * math.pi * 3.0, \
        "the second and third circles must be judged as normal windows"


def test_ze2d_full_width_depth_true_slot_vs_ridge_plus_graze():
    """ZE2D: full_width_depth = largest h with (area removed >= h deep) /
    travel >= 0.9 D. A true full-width slot 10 mm deep scores ~10; a 1 mm
    full-width ridge plus a 0.3 mm-wide 18 mm-tall graze scores ~1, although
    its a (max removed height) is 18."""
    part = np.zeros((NF, NF))
    # (1) true slot: solid stock top 18.6, tip at 8.6 -> 10 mm deep, full width
    pts = [(-15.0 + 0.5 * i, 0.0) for i in range(1, 61)]
    res = _run_ae2(_ae2_gcode(pts, (-20.0, 0.0), 8.6), part)
    slot = [w for w in res["_ae2_raw"] if w["ae_eff"] >= 0.9 * D_ZE2]
    assert slot, "no full-width window in the true slot"
    assert all(abs(w["full_width_depth"] - 10.0) <= 0.3 for w in slot), \
        [w["full_width_depth"] for w in slot]
    # (2) ridge + graze: stock 1 mm above the tip everywhere (the ridge), plus a
    # 0.3 mm-wide 18 mm-tall wall at y = +6.2..6.5 inside the tool's rim reach
    xs = _centers_f()
    stock = np.full((NF, NF), 9.6)                   # tip at 8.6 -> 1 mm ridge
    wall = (xs >= 6.2) & (xs < 6.5)
    stock[wall, :] = 26.6                            # rows = y: 18 mm above the tip
    res2 = _run_ae2(_ae2_gcode(pts, (-20.0, 0.0), 8.6), part, stock_init=stock)
    fw2 = [w for w in res2["_ae2_raw"] if w["ae_eff"] >= 0.9 * D_ZE2]
    assert fw2, "the 1 mm ridge must still read full width"
    assert all(w["a"] > 17.5 for w in fw2), [w["a"] for w in fw2]     # a alone says 'deep'
    assert all(abs(w["full_width_depth"] - 1.0) <= 0.3 for w in fw2), \
        [w["full_width_depth"] for w in fw2]
    bands = res2["engagement"]["full_width_depth_bands_ae2"]
    assert bands["cutting_feed"]["0.5-2"]["count"] == len(fw2)


# ---------------------------------------------------------------------------
# Task ZE2B: ball-tool engagement vs the live stock zmap (report-only).
# BOTH widths: w_plan vs the ball chord c(a) for the full-width flag, and
# ae_eq (removed volume per mm of 3D travel / a) vs --engage-max for load.
# Fixtures: ball D = 9.525, cell 0.05 mm; a >= 0.05 gate; descents (horiz
# < 10 % of 3D travel) are tagged and never full width.
# ---------------------------------------------------------------------------

D_ZB = 9.525
CELL_B = 0.05
NB = 400                      # grid covers [-10, 10] x [-10, 10]
X0_B = Y0_B = -10.0
STOCK_B = (-10.0, 10.0, -10.0, 10.0, 0.0, 10.0)
NB_L = 900                    # long grid covers [-12, 33] (long side pass)
X0_L = Y0_L = -12.0
STOCK_L = (-12.0, 33.0, -12.0, 33.0, 0.0, 10.0)


def _run_zb(gcode, part, stock_init=None, x0=X0_B, y0=Y0_B, stock=STOCK_B):
    moves = zmap.parse_gcode(gcode)
    return zmap.simulate(moves, part, CELL_B, x0, y0, stock, tool="ball",
                        dia=D_ZB, engage_max=2.286, stock_init=stock_init)


def _zb_pass_gcode(y, z, x0=-5.0, x1=5.0):
    """rapid above (x0, y), vertical feed descent to the tip Z=z (a descent
    window: horiz = 0), then the X-direction feed pass at lateral y, F500."""
    return "\n".join([
        "G21 G90 F500",
        "G0 X%.4f Y%.4f Z12." % (x0, y),
        "G1 X%.4f Y%.4f Z%.4f F100." % (x0, y, z),
        "G1 X%.4f Y%.4f F500." % (x1, y),
    ]) + "\n"


def _check_side_pass(res):
    """Design case 1: straight pass at a = 2.0 beside a cleared pass at
    stepover s = 1.905 -> ae_eq ~ s (+-5 %); w_plan/c(a) ~ 0.62 (contact from
    the scallop crest at -s/2 to the far chord edge); NOT full width."""
    a = 2.0
    c_a = 2.0 * math.sqrt(a * (D_ZB - a))
    horiz = [w for w in res["_zb_raw"] if not w["descent"]]
    assert len(horiz) == 1, "expected one non-descent window: %d" % len(horiz)
    w = horiz[0]
    assert abs(w["a"] - a) <= 0.1
    assert abs(w["c_a"] - c_a) <= 0.05
    assert abs(w["theta"] - math.degrees(
        math.acos(1.0 - a / (D_ZB / 2.0)))) <= 1.0
    assert abs(w["ae_eq"] - 1.905) <= 0.05 * 1.905, \
        "ae_eq %.3f not within 5%% of stepover" % w["ae_eq"]
    assert abs(w["w_plan"] / w["c_a"] - 0.62) <= 0.08, \
        "w_plan/c(a) %.3f not ~0.62" % (w["w_plan"] / w["c_a"])
    eng = res["engagement"]["ze2b"]
    assert eng["full_width"]["count"] == 0, \
        "side pass flagged full width: %r" % eng["full_width"]["worst"]
    assert eng["descent"]["count"] >= 1


def test_ze2b_side_pass_ae_eq_is_stepover():
    part = np.zeros((NB_L, NB_L))
    g_a = _zb_pass_gcode(-2.905, 8.0, x0=-5.0, x1=20.0)
    res_a = _run_zb(g_a, part, x0=X0_L, y0=Y0_L, stock=STOCK_L)
    res = _run_zb(_zb_pass_gcode(-1.0, 8.0, x0=-5.0, x1=20.0), part,
                  stock_init=res_a["stock"], x0=X0_L, y0=Y0_L, stock=STOCK_L)
    _check_side_pass(res)


def _check_full_slot(res):
    """Design case 2: full-width slot at a = 2.0 into flat stock -> w_plan ~
    c(2.0) = 7.76 and full_width flagged; ae_eq = segment area / a ~ 5.44."""
    a = 2.0
    c_a = 2.0 * math.sqrt(a * (D_ZB - a))
    assert abs(c_a - 7.759) <= 0.01
    horiz = [w for w in res["_zb_raw"] if not w["descent"]]
    assert len(horiz) == 1, "expected one non-descent window: %d" % len(horiz)
    w = horiz[0]
    assert abs(w["w_plan"] - c_a) <= 0.15, \
        "w_plan %.3f vs c(a) %.3f" % (w["w_plan"], c_a)
    assert abs(w["ae_eq"] - 5.44) <= 0.27, "ae_eq %.3f" % w["ae_eq"]
    eng = res["engagement"]["ze2b"]
    assert eng["full_width"]["count"] == 1, \
        "slot pass not flagged full width: %r" % eng["full_width"]
    assert eng["overload"]["count"] >= 1        # ae_eq ~5.4 > 2.286
    assert eng["descent"]["count"] == 1         # plunge tagged...
    assert eng["full_width"]["worst"][0]["line"] == w["line"]  # ... not flagged


def test_ze2b_full_slot_flagged_chord_and_ae_eq():
    res = _run_zb(_zb_pass_gcode(0.0, 8.0), np.zeros((NB, NB)))
    _check_full_slot(res)


def test_ze2b_slope_skim_not_flagged():
    """Design case 3: 0.2 mm normal-thickness skim on a 45 deg slope -> not
    full width, not overload at the spike load 2.286."""
    ys = X0_B + (np.arange(NB) + 0.5) * CELL_B
    stock = np.broadcast_to(ys[:, None] + 10.0, (NB, NB)).copy()
    # ball centre 0.2 mm (normal) off the plane z = y + 10 at y = 0
    tip = (10.0 + (D_ZB / 2.0 - 0.2) * math.sqrt(2.0)) - D_ZB / 2.0
    res = _run_zb(_zb_pass_gcode(0.0, tip), np.zeros((NB, NB)),
                  stock_init=stock)
    eng = res["engagement"]["ze2b"]
    assert eng["full_width"]["count"] == 0
    assert eng["overload"]["count"] == 0
    assert eng["ae_eq"]["max"] < 2.286
    assert eng["ae_eq"]["max"] > 0.0           # it does cut


def test_ze2b_helix_finite_and_descent_tagged():
    """Design case 4: 2 deg helix descent (r 3, ~5 mm deep): finite
    ae_eq/w_plan everywhere, nothing above D, the vertical entry tagged."""
    lines = ["G21 G90 F500", "G0 X3. Y0. Z12.", "G1 X3. Y0. Z9.5 F100."]
    pitch = 0.658                              # 2 deg at r 3 per turn
    for i in range(1, 229):                   # 12 deg steps, 7.6 turns
        th = math.radians(12.0 * i)
        lines.append("G1 X%.4f Y%.4f Z%.4f F100."
                     % (3.0 * math.cos(th), 3.0 * math.sin(th),
                        9.5 - pitch * i / 30.0))
    res = _run_zb("\n".join(lines) + "\n", np.zeros((NB, NB)))
    wins = res["_zb_raw"]
    assert len(wins) >= 50
    for w in wins:
        assert math.isfinite(w["ae_eq"]) and math.isfinite(w["w_plan"])
        assert w["w_plan"] <= D_ZB + 1e-9
        assert w["ae_eq"] <= D_ZB
    eng = res["engagement"]["ze2b"]
    assert eng["descent"]["count"] >= 1       # the vertical entry is tagged
    assert wins[0]["descent"] is True
    assert wins[-1]["descent"] is False      # helix windows are not descents
    assert eng["a"]["max"] <= D_ZB / 2.0 + 1e-9   # a clipped to R


def test_ze2b_flat_and_bull_json_byte_identical(tmp_path):
    """Design case 5: flat/bull --out-json stays BYTE-IDENTICAL to b1688b8's
    zmap (the ZE2B block is ball-only)."""
    import subprocess
    here = os.path.dirname(os.path.abspath(zmap.__file__))
    root = os.path.dirname(here)
    old = tmp_path / "zmap_b1688b8.py"
    old.write_bytes(subprocess.check_output(
        ["git", "-C", root, "show", "b1688b8:verify/zmap.py"]))
    part = block_part(hi=10.0, half=15.0)
    npf = tmp_path / "part.npy"
    np.save(npf, part)
    with open(tmp_path / "part.json", "w") as f:
        json.dump({"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}, f)
    ngc = tmp_path / "prog.ngc"
    ngc.write_text("G21 G90 F500\nG0 X-20. Y0. Z20.\nG1 Z5. F100.\n"
                   "G1 X20. Y0. F500.\nG0 X-20. Y2. Z20.\nG1 Z5. F100.\n"
                   "G1 X20. Y2. F500.\n")
    stock_args = ["-15.0", "15.0", "-15.0", "15.0", "0.0", "10.0"]
    for extra in ([], ["--tool", "bull", "--corner", "1.0"]):
        outs = []
        for script in (str(old), os.path.join(here, "zmap.py")):
            o = tmp_path / ("out_%d_%s.json"
                            % (len(extra), os.path.basename(script)))
            rc = subprocess.call(
                [sys.executable, script, str(ngc), "--part", str(npf),
                 "--stock"] + stock_args + ["--engage-max", "2.0"]
                + ["--out-json", str(o)] + extra)
            assert rc == 0, "zmap run failed: %s %s" % (script, extra)
            outs.append(json.loads(o.read_bytes()))
        _assert_pinned_plus_zg1(outs[0], outs[1], "missing", extra)


def _assert_pinned_plus_zg1(pinned, new, part_mask, label):
    """ZG1 (supervisor, coordinator-approved): every key of the b1688b8 JSON is
    present with a byte-identical value (json.dumps, sort_keys); the ONLY
    extra keys are below_stock_bottom (count 0) and part_mask (this synthetic
    part has no .hit.npy, so "missing")."""
    for k, v in pinned.items():
        assert k in new, "pinned key %r gone: %r" % (k, label)
        assert json.dumps(new[k], sort_keys=True) == \
            json.dumps(v, sort_keys=True), \
            "flat/bull JSON changed at %r: %r" % (k, label)
    extra = set(new) - set(pinned)
    assert extra == {"below_stock_bottom", "part_mask"}, \
        "extra keys %r: %r" % (sorted(extra), label)
    assert new["below_stock_bottom"]["count"] == 0, new["below_stock_bottom"]
    assert new["part_mask"] == part_mask, (new["part_mask"], label)


def test_ze2b_cli_ball_block_and_dump(tmp_path):
    """ball + engagement: report carries engagement.ze2b and the ZE2 semantics
    marker; --ae2b-dump writes the windows with the design's fields."""
    part = np.zeros((NB, NB))
    npf = tmp_path / "p.npy"
    np.save(npf, part)
    with open(tmp_path / "p.json", "w") as f:
        json.dump({"cell": CELL_B, "x0": X0_B, "y0": Y0_B, "tess_tol": 0.01},
                  f)
    ngc = tmp_path / "slot.ngc"
    ngc.write_text(_zb_pass_gcode(0.0, 8.0))
    out = tmp_path / "rep.json"
    dump = tmp_path / "wins.json"
    rc = zmap.main([str(ngc), "--part", str(npf), "--tool", "ball",
                    "--dia", str(D_ZB), "--stock"]
                   + [str(v) for v in STOCK_B]
                   + ["--engage-max", "2.286", "--out-json", str(out),
                      "--ae2b-dump", str(dump)])
    assert rc == 0                                  # report-only, never fails
    with open(out) as f:
        eng = json.load(f)["engagement"]
    assert eng["semantics"] == "flat-only, see ze2b"
    zb = eng["ze2b"]
    for k in ("n_windows", "full_width", "overload", "ae_eq",
              "w_plan_over_chord", "a", "descent"):
        assert k in zb, "missing ze2b key %s" % k
    assert zb["n_windows"] >= 1
    with open(dump) as f:
        wins = json.load(f)
    assert wins
    need = {"line", "x", "y", "z", "a", "theta", "w_plan", "c_a", "ae_eq",
            "length_3d", "feed", "descent"}
    assert need <= set(wins[0]), sorted(need - set(wins[0]))


def test_ze2b_mutation_broken_chord_breaks_assertions(monkeypatch):
    """Design case 6, mutation proof: with c(a) replaced by D (a broken chord
    formula - monkeypatched wrapper, no edit to zmap.py) the full-width slot
    and side-pass checks must FAIL BY ASSERTION."""
    monkeypatch.setattr(zmap, "_ze2b_chord", lambda a, dia: dia)
    with pytest.raises(AssertionError):
        _check_full_slot(_run_zb(_zb_pass_gcode(0.0, 8.0),
                                 np.zeros((NB, NB))))
    part = np.zeros((NB_L, NB_L))
    res_a = _run_zb(_zb_pass_gcode(-2.905, 8.0, x0=-5.0, x1=20.0), part,
                    x0=X0_L, y0=Y0_L, stock=STOCK_L)
    with pytest.raises(AssertionError):
        _check_side_pass(_run_zb(_zb_pass_gcode(-1.0, 8.0, x0=-5.0, x1=20.0),
                                 part, stock_init=res_a["stock"],
                                 x0=X0_L, y0=Y0_L, stock=STOCK_L))


# ---------------------------------------------------------------------------
# Task ZG1: the gouge rule's blind spot at the global part minimum.
# A plate whose top face IS the part's global minimum must have cuts into
# it reported as gouges (via <stem>.hit.npy, or fail-closed strict when the
# mask is missing); below_stock_bottom is a hard gate.
# ---------------------------------------------------------------------------

def _zg1_plate(tmp_path, hit=None, top=10.0, stem="plate"):
    """Uniform plate: top face == the part's global minimum (the blind
    spot), flush with the stock top. Optional bool hit mask as .hit.npy."""
    npy = tmp_path / (stem + ".npy")
    np.save(npy, np.full((N, N), top))
    (tmp_path / (stem + ".json")).write_text(json.dumps(
        {"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}))
    if hit is not None:
        np.save(str(npy)[:-4] + ".hit.npy", hit)
    return npy


def _zg1_cli(tmp_path, npy, body, tool=None):
    gc = tmp_path / "zg1.ngc"
    gc.write_text("G21 G90 F500\n" + body)
    out = tmp_path / "zg1.json"
    argv = [str(gc), "--part", str(npy), "--stock"]
    argv += [str(v) for v in STOCK] + ["--out-json", str(out)]
    if tool:
        argv += tool
    rc = zmap.main(argv)
    return rc, json.loads(out.read_text())


def test_zg1_plate_minimum_face_gouge_with_hit_mask(tmp_path):
    """Cut 0.1 mm into a plate face sitting at the part's global minimum:
    with a .hit.npy mask it is a gouge (fails under the old footprint rule)."""
    npy = _zg1_plate(tmp_path, hit=np.ones((N, N), dtype=bool))
    rc, rep = _zg1_cli(tmp_path, npy, "G0 X-20. Y0. Z20.\n"
                                      "G1 Z9.9 F100.\nG1 X20. F500.\n")
    assert rep["part_mask"] == "present"
    assert abs(rep["gouges"]["max_depth"] - 0.1) < 1e-6, \
        "measured gouge depth must be 0.1 mm: %r" % rep["gouges"]
    assert rep["gouges"]["worst_xy"] is not None
    assert rc == 0  # gouges stay report-only


def test_zg1_plate_minimum_face_gouge_without_mask(tmp_path):
    """Same cut with NO .hit.npy: fail closed, judge every valid cell
    strictly, and say so in the JSON."""
    npy = _zg1_plate(tmp_path)
    rc, rep = _zg1_cli(tmp_path, npy, "G0 X-20. Y0. Z20.\n"
                                      "G1 Z9.9 F100.\nG1 X20. F500.\n")
    assert rep["part_mask"] == "missing"
    assert abs(rep["gouges"]["max_depth"] - 0.1) < 1e-6, \
        "fail-closed fallback must report the 0.1 mm gouge: %r" % rep["gouges"]
    assert rc == 0


def test_zg1_hit_mask_excludes_part_free_cells(tmp_path):
    """Mask present: cuts BELOW the zmin fill outside the part footprint
    (depth 0.15) must NOT count as gouges; the 0.1 mm cut into real part
    geometry must. Drop the mask use -> measured depth becomes 0.15."""
    xs = centers()[None, :]
    ys = centers()[:, None]
    hit = (np.abs(xs) <= 5.0) & (np.abs(ys) <= 5.0)
    npy = _zg1_plate(tmp_path, hit=hit)
    rc, rep = _zg1_cli(tmp_path, npy,
                       "G0 X-5. Y0. Z20.\nG1 Z9.9 F100.\nG1 X5. F500.\n"
                       "G0 X-10. Y10. Z20.\nG1 Z9.85 F100.\nG1 X10. F500.\n")
    assert rep["part_mask"] == "present"
    assert abs(rep["gouges"]["max_depth"] - 0.1) < 1e-6, \
        "only the 0.1 mm cut into part geometry may gouge: %r" % rep["gouges"]
    assert rc == 0


def test_zg1_below_stock_bottom_hard_gate(tmp_path):
    """Tip 0.1 mm below the stock bottom Z0: non-zero exit, with count,
    max depth, worst xy and first line."""
    npy = _zg1_plate(tmp_path)
    rc, rep = _zg1_cli(tmp_path, npy,
                       "G0 X-20. Y0. Z20.\nG1 Z-0.1 F100.\nG1 X20. F500.\n",
                       tool=["--tool", "ball"])  # ball: axial stays report-only
    bs = rep["below_stock_bottom"]
    assert bs["count"] > 0
    assert abs(bs["max_depth"] - 0.1) < 1e-6, \
        "measured depth below the stock bottom must be 0.1 mm: %r" % bs
    assert bs["worst_xy"] == [-20.0, 0.0], bs
    assert bs["first_line"] == 3, bs
    assert rc == 1, "below_stock_bottom must exit non-zero"


def test_zg1_at_stock_bottom_not_flagged(tmp_path):
    """Cutting exactly TO the stock bottom is not below it: gate stays 0."""
    npy = _zg1_plate(tmp_path)
    rc, rep = _zg1_cli(tmp_path, npy,
                       "G0 X-20. Y0. Z20.\nG1 Z0. F100.\nG1 X20. F500.\n",
                       tool=["--tool", "ball"])
    assert rep["below_stock_bottom"]["count"] == 0
    assert rep["below_stock_bottom"]["max_depth"] == 0.0
    assert rc == 0


def test_zg1_heightfield_writes_hit_mask(tmp_path):
    """rasterize(hit_out=...) writes the bool geometry-hit mask: True where
    part geometry was hit (even a top face AT zmin), False in the grown,
    part-free zmin-fill ring."""
    import types
    sys.modules.setdefault("FreeCAD", types.ModuleType("FreeCAD"))
    sys.modules.setdefault("Part", types.ModuleType("Part"))
    import heightfield

    class _Square:
        """Flat square top at z=top over [-10, 8] x [-6, 5]."""
        def __init__(self, top):
            self.top = top
            self.BoundBox = types.SimpleNamespace(
                XMin=-10.0, XMax=8.0, YMin=-6.0, YMax=5.0,
                ZMin=0.0, ZMax=top)

        def tessellate(self, tol):
            v = [types.SimpleNamespace(x=x, y=y, z=self.top)
                 for x, y in ((-10.0, -6.0), (8.0, -6.0),
                              (8.0, 5.0), (-10.0, 5.0))]
            return v, [(0, 1, 2), (0, 2, 3)]

    for top in (10.0, 0.0):  # 0.0: top face IS the global minimum
        hp = tmp_path / ("hf_%s.hit.npy" % top)
        hf, meta = heightfield.rasterize(_Square(top), cell=0.5, tol=0.01,
                                         stock_box=[-20.0, 20.0, -15.0, 15.0],
                                         tool_r=6.35, margin=5.0,
                                         hit_out=str(hp))
        hit = np.load(str(hp))
        assert hit.dtype == bool and hit.shape == hf.shape
        i0 = int((0.0 - meta["x0"]) / 0.5)
        j0 = int((0.0 - meta["y0"]) / 0.5)
        assert bool(hit[j0, i0]), "geometry column must be hit (top=%s)" % top
        assert not bool(hit[0, 0]), "grown ring is part-free (top=%s)" % top
        assert hf[0, 0] == 0.0


# ---------------------------------------------------------------------------
# Task ZG1b: below_stock_bottom must use the TRUE stock bottom through
# --stock-in chains. --stock-out records the ORIGINAL stock box in the stock
# sidecar <stem>.json under "stock_box"; --stock-in reads it back. Without a
# box (old stock files) the check is "unknown" and never gates.
# ---------------------------------------------------------------------------

_ZG1B_BOX = [-25.0, 25.0, -25.0, 25.0, 0.0, 10.0]  # == list(STOCK)


def _zg1b_prog1_out(tmp_path, stem="st1"):
    """Stage 1: cut to Z 6.0 with --stock, --stock-out -> grid + sidecar."""
    npy = _zg1_plate(tmp_path, stem="zg1b")
    g1 = tmp_path / "p1.ngc"
    g1.write_text("G21 G90 F500\nG0 X-20. Y0. Z20.\n"
                  "G1 Z6. F100.\nG1 X20. F500.\n")
    st = tmp_path / (stem + ".npy")
    rc = zmap.main([str(g1), "--part", str(npy), "--tool", "ball", "--stock"]
                   + [str(v) for v in STOCK]
                   + ["--stock-out", str(st),
                      "--out-json", str(tmp_path / (stem + ".json"))])
    assert rc == 0, "stage 1 (legal cut to Z 6.0) must pass"
    return npy, st


def test_zg1b_chain_below_true_bottom_fails_by_value(tmp_path):
    """Chained run, program 2 with --stock-in and NO --stock: a tip 0.25 mm
    below the TRUE bottom Z 0.0 must exit 1 with measured depth 0.25 mm
    (the remaining stock bottoms out at Z 6.0 - gating on that would
    measure 6.25 mm and reject the legal part too)."""
    npy, st1 = _zg1b_prog1_out(tmp_path)
    box = json.loads((tmp_path / "st1.json").read_text())["stock_box"]
    assert box == _ZG1B_BOX, "sidecar must carry the ORIGINAL box: %r" % box
    g2 = tmp_path / "p2.ngc"
    g2.write_text("G21 G90 F500\nG0 X-20. Y0. Z20.\n"
                  "G1 Z-0.25 F100.\nG1 X20. F500.\n")
    j2 = tmp_path / "j2.json"
    st2 = tmp_path / "st2.npy"
    rc = zmap.main([str(g2), "--part", str(npy), "--tool", "ball",
                    "--stock-in", str(st1), "--stock-out", str(st2),
                    "--out-json", str(j2)])
    bs = json.loads(j2.read_text())["below_stock_bottom"]
    assert bs["count"] > 0, bs
    assert abs(bs["max_depth"] - 0.25) < 1e-6, \
        "measured depth below the TRUE bottom must be 0.25 mm: %r" % bs
    assert rc == 1, "below the true stock bottom must exit non-zero"
    # the true bottom travels on: stage 2's sidecar keeps the ORIGINAL box
    assert json.loads((tmp_path / "st2.json").read_text())["stock_box"] \
        == _ZG1B_BOX


def test_zg1b_stock_without_sidecar_box_is_unknown(tmp_path):
    """Old stock file (no sidecar stock_box): below_stock_bottom is
    'unknown', the report says the check was NOT done and why, and a cut
    below the lowest REMAINING stock (Z 6.0) does NOT exit 1 for that
    reason (the old nanmin derivation would have failed it with 1.5 mm)."""
    npy, st1 = _zg1b_prog1_out(tmp_path)
    (tmp_path / "st1.json").unlink()  # simulate a pre-ZG1b stock file
    g2 = tmp_path / "p2.ngc"
    g2.write_text("G21 G90 F500\nG0 X-20. Y0. Z20.\n"
                  "G1 Z4.5 F100.\nG1 X20. F500.\n")
    j2 = tmp_path / "j2.json"
    rc = zmap.main([str(g2), "--part", str(npy), "--tool", "ball",
                    "--stock-in", str(st1), "--out-json", str(j2)])
    rep = json.loads(j2.read_text())
    bs = rep["below_stock_bottom"]
    assert bs["status"] == "unknown", bs
    assert bs["count"] == 0, bs
    assert "NOT done" in bs["reason"], bs
    assert bs["next_step"] == \
        "pass --stock or regenerate the stock file with this version", bs
    assert rc == 0, "an unknown bottom must never gate: rc=%d %r" % (rc, bs)


def test_zg1b_stock_vs_sidecar_box_disagreement_fails(tmp_path, capsys):
    """--stock plus a --stock-in sidecar box differing by > 1e-6 mm must
    fail with an error naming BOTH boxes (an exact match stays OK)."""
    npy, st1 = _zg1b_prog1_out(tmp_path)
    sc = tmp_path / "st1.json"
    meta = json.loads(sc.read_text())
    meta["stock_box"][4] = 0.5
    sc.write_text(json.dumps(meta))
    g2 = tmp_path / "p2.ngc"
    g2.write_text("G21 G90 F500\nG0 X-20. Y0. Z20.\n"
                  "G1 Z4.5 F100.\nG1 X20. F500.\n")
    rc = zmap.main([str(g2), "--part", str(npy), "--tool", "ball", "--stock"]
                   + [str(v) for v in STOCK]
                   + ["--stock-in", str(st1),
                      "--out-json", str(tmp_path / "j2.json")])
    err = capsys.readouterr().err
    assert rc == 1, "a >1e-6 mm box disagreement must exit 1"
    assert "disagree" in err and "0.5" in err and "0.0" in err, err


def test_zg1b_stock_out_merges_existing_sidecar(tmp_path):
    """--stock-out adds stock_box to an existing chain sidecar instead of
    dropping its keys (chain scripts write x0/y0/cell there)."""
    npy = _zg1_plate(tmp_path, stem="zg1bm")
    g1 = tmp_path / "p1.ngc"
    g1.write_text("G21 G90 F500\nG0 X-20. Y0. Z20.\n"
                  "G1 Z6. F100.\nG1 X20. F500.\n")
    st = tmp_path / "stm.npy"
    (tmp_path / "stm.json").write_text(json.dumps(
        {"x0": X0, "y0": Y0, "cell": CELL}))
    rc = zmap.main([str(g1), "--part", str(npy), "--tool", "ball", "--stock"]
                   + [str(v) for v in STOCK]
                   + ["--stock-out", str(st),
                      "--out-json", str(tmp_path / "jm.json")])
    assert rc == 0
    meta = json.loads((tmp_path / "stm.json").read_text())
    assert meta["x0"] == X0 and meta["y0"] == Y0 and meta["cell"] == CELL, meta
    assert meta["stock_box"] == _ZG1B_BOX, meta


def test_zg1_window_is_speed_only_off_window_gouge_not_judged(tmp_path):
    """ZG1 (coordinator): --window is a SPEED option that simulates and
    judges only cells within 2 mm of steep walls. A 0.1 mm gouge on the flat
    block top, more than 2 mm from any wall, is reported without --window
    and NOT judged with it; the --window report says so plainly."""
    npy = tmp_path / "blk.npy"
    np.save(npy, block_part(hi=10.0, half=15.0))
    (tmp_path / "blk.json").write_text(json.dumps(
        {"cell": CELL, "x0": X0, "y0": Y0, "tess_tol": 0.01}))
    body = "G0 X-5. Y0. Z20.\nG1 Z9.9 F100.\nG1 X5. F500.\n"
    _rc0, plain = _zg1_cli(tmp_path, npy, body)
    _rc1, win = _zg1_cli(tmp_path, npy, body, tool=["--window"])
    assert plain["gouges"]["count"] >= 1, plain["gouges"]
    assert abs(plain["gouges"]["max_depth"] - 0.1) < 1e-6, plain["gouges"]
    assert win["gouges"]["count"] == 0, \
        "--window restricts what is simulated: off-window gouge measured " \
        "count %r, expected 0 (not judged)" % win["gouges"]["count"]
    assert "NOT judged" in (win["window"] or ""), win["window"]
    assert plain["window"] is None
