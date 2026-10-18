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
