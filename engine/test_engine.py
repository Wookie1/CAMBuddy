#!/usr/bin/env python3
"""Engine tests. Run standalone with VibeCAD python:
    /Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_engine.py
also pytest-compatible under any python that can import `area`
(otherwise the Adaptive2d test is skipped).

Proves the area.Adaptive2d boundary convention used by engine/rough.py:
Adaptive2d offsets every geometry loop inward/off by tool_radius +
stockToLeave (proven empirically: a raw boss loop yields centres exactly
tool_r + leave away; a pre-grown loop would be double-offset). So:
  * outer boundary = stock box grown by tool_r + leave -> centres reach the
    stock edge exactly and the tool breaks cleanly through the stock edge;
  * islands = raw silhouette (material cross-section) loops at level Z, from
    an ocl waterline with a near-zero-radius cutter -> centres end up exactly
    tool_r + leave from the part, i.e. `leave` mm radial stock left.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")

try:
    import area
    HAVE_AREA = True
except ImportError:
    try:
        import pytest
        pytest.importorskip("area")
    except ImportError:
        pass
    HAVE_AREA = False

from engine.rough import (plan_levels, plan_stepup_levels, rect_loop,  # noqa: E402
                          decimate, allowance_violation)
from engine.stock import StockField  # noqa: E402
from engine.gcode import moves_to_gcode  # noqa: E402


def _dist_pt_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _rect_edges(r):
    pts = rect_loop(*r)
    return [(pts[i][0], pts[i][1], pts[(i + 1) % 4][0], pts[(i + 1) % 4][1])
            for i in range(4)]


def _grow_rect(r, d):
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def test_adaptive2d_offset_convention():
    """Square boss in a box: tool centre stays exactly tool_r + allowance from
    the boss, and reaches exactly the stock edge on the outside."""
    if not HAVE_AREA:
        print("SKIP test_adaptive2d_offset_convention (no area module)")
        return
    box = (0.0, 0.0, 40.0, 40.0)
    boss = (10.0, 10.0, 30.0, 30.0)
    tool_d, leave = 6.0, 0.5
    r = tool_d / 2.0
    off = r + leave  # the offset Adaptive2d is supposed to apply itself

    outer = rect_loop(*_grow_rect(box, off))  # grown stock outline
    island = rect_loop(*boss)                 # raw boss silhouette (island)
    a2d = area.Adaptive2d()
    a2d.stepOverFactor = 0.15
    a2d.toolDiameter = tool_d
    a2d.helixRampTargetDiameter = 0.8 * tool_d
    a2d.helixRampMinDiameter = 0.4 * tool_d
    a2d.keepToolDownDistRatio = 3.0
    a2d.stockToLeave = leave
    a2d.tolerance = 0.001
    a2d.forceInsideOut = False
    a2d.finishingProfile = False
    a2d.opType = area.AdaptiveOperationType.ClearingInside
    results = a2d.Execute([outer], [outer, island], [], lambda tp: False)

    cut = []
    for res in results:
        if getattr(res, "StartPointNotFound", False):
            continue
        for mt, pts in res.AdaptivePaths:
            if mt == area.AdaptiveMotionType.Cutting:
                cut += [(p[0], p[1]) for p in pts]
    assert len(cut) > 500, "adaptive produced too few points: %d" % len(cut)

    boss_d = []
    for (px, py) in cut:
        inside = boss[0] <= px <= boss[2] and boss[1] <= py <= boss[3]
        assert not inside, "cutting centre %r entered the boss" % ((px, py),)
        boss_d.append(min(_dist_pt_seg(px, py, *e) for e in _rect_edges(boss)))
    edge_d = [min(px - box[0], box[2] - px, py - box[1], box[3] - py)
              for (px, py) in cut]

    # centre stays exactly tool_r + allowance from the boss (never closer)
    assert min(boss_d) >= off - 0.01, \
        "boss clearance %.4f < tool_r+leave %.2f" % (min(boss_d), off)
    assert min(boss_d) <= off + 0.05, \
        "boss clearance %.4f much greater than tool_r+leave %.2f" % (
            min(boss_d), off)
    # centres reach exactly the stock edge (grown outline cancels a2d offset)
    assert min(edge_d) <= 0.05, \
        "centres never reach stock edge: min edge dist %.4f" % min(edge_d)
    assert min(edge_d) >= -0.05, \
        "centres stray past stock edge: min edge dist %.4f" % min(edge_d)
    # the ring between boss+clearance and stock edge is actually cleared:
    # outermost pass hugs the edge, innermost hugs the boss
    assert max(boss_d) >= off + 1.0, "ring not cleared outward"
    # HARD allowance post-check (the same one engine/rough.py runs per level):
    # every cutting centre must stay >= tool_r + leave - 0.02 from the island
    viol = allowance_violation(cut, [island], r, leave)
    assert viol is None, \
        "allowance post-check: centre (%.3f, %.3f) is %.4f mm from the boss "\
        "loop, need >= %.4f" % (viol[0], viol[1], viol[2], off - 0.02)
    print("PASS adaptive2d convention: boss clearance %.4f == tool_r+leave "
          "%.2f, stock edge reach %.4f" % (min(boss_d), off, min(edge_d)))


def test_plan_levels():
    zs = plan_levels(60.96, 24.8, 0.3, 1.9)
    assert abs(zs[-1] - 25.1) < 1e-9
    assert all(zs[i] > zs[i + 1] for i in range(len(zs) - 1))
    assert all(zs[i] - zs[i + 1] <= 1.9 + 1e-9 for i in range(len(zs) - 1))
    assert zs[0] < 60.96  # level flush with stock top removed (cuts nothing)
    print("PASS plan_levels: %d levels %.3f..%.3f" % (len(zs), zs[0], zs[-1]))


def test_plan_levels_cutting_data():
    """James's cutting data: stepdown 19.05, axial leave, explicit final
    ZMIN 24.95, flat-area levels at floor + axial leave."""
    floors = [42.463, 42.545, 39.908, 39.224, 34.925, 24.765]
    zs = plan_levels(60.96, 24.765, 0.381, 19.05, flat_floors=floors,
                    axial_leave=0.381, final_zmin=24.95)
    assert abs(zs[-1] - 24.95) < 1e-9, "final level must match the given ZMIN"
    assert all(zs[i] > zs[i + 1] for i in range(len(zs) - 1))
    assert all(zs[i] - zs[i + 1] <= 19.05 + 1e-9 for i in range(len(zs) - 1))
    assert zs[0] < 60.96
    # flat floors add levels at floor + axial leave
    for want in (42.926, 40.289, 39.605, 35.306):
        assert any(abs(z - want) < 1e-9 for z in zs), \
            "flat-area level %.3f missing: %r" % (want, zs)
    # redundant candidates dropped: main-floor 25.146 within min gap of the
    # final level, and 42.545+0.381 within min gap of 42.926
    assert not any(abs(z - 25.146) < 1e-9 for z in zs)
    assert not any(abs(z - 42.545 + 0.381) < 1e-9 and
                   abs(z - 42.926) > 1e-9 for z in zs)
    assert all(zs[i] - zs[i + 1] >= 0.5 - 1e-9 for i in range(len(zs) - 1))
    print("PASS plan_levels cutting data: levels %r" % (zs,))


def test_allowance_violation():
    """Hard post-check: flag CL centres closer than tool_r + leave - 0.02 to
    an island loop (the round-5 failure lost 0.37 mm near a tall feature)."""
    tool_r, leave = 3.0, 0.5
    island = [[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]
    ok = [(6.5, 15.0), (23.5, 15.0), (15.0, 6.5), (15.0, 23.5),
          (0.0, 0.0), (30.0, 30.0), (6.52, 10.0)]
    assert allowance_violation(ok, [island], tool_r, leave) is None
    bad = [(23.4, 15.0)]  # 0.1 mm inside the required 3.48 mm envelope
    v = allowance_violation(bad, [island], tool_r, leave)
    assert v is not None and abs(v[2] - 3.4) < 1e-9, "missed violation: %r" % (v,)
    assert abs(v[0] - 23.4) < 1e-9 and abs(v[1] - 15.0) < 1e-9
    # round-5 style: centre 6.277 from material vs intended 6.65
    # (R1: points must be OUTSIDE the loop - inside is a containment
    # violation, covered by test_allowance_violation_containment)
    big = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
    v2 = allowance_violation([(-6.277, 50.0)], [big], 6.35, 0.3)
    assert v2 is not None and abs(v2[2] - 6.277) < 1e-9
    assert allowance_violation([(-6.63, 50.0)], [big], 6.35, 0.3) is None
    print("PASS allowance_violation")


def test_decimate():
    pts = [(0.0, 0.0), (0.01, 0.0), (0.5, 0.0), (0.5, 0.5), (1.0, 0.5)]
    out = decimate(pts, 0.05)
    assert out == [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (1.0, 0.5)]
    print("PASS decimate")


def test_gcode_emit():
    moves = [
        {"g": 0, "x": 1.0, "y": 2.0, "z": 62.96},
        {"g": 1, "x": 1.0, "y": 2.0, "z": 59.06, "f": 1270.0},
        {"g": 1, "x": 5.0, "y": 2.0, "z": 59.06, "f": 3429.0},
        {"g": 0, "x": 5.0, "y": 2.0, "z": 62.96},
    ]
    txt = moves_to_gcode(moves, spindle_rpm=7500, tool_comment="T1 bull")
    assert txt.startswith("G21\nG90\nG94\nG17\n")
    assert "S7500 M3" in txt and "M30" in txt
    assert "G1 X5.0000 Y2.0000 Z59.0600 F3429" in txt
    assert "G0 X1.0000 Y2.0000 Z62.9600" in txt
    print("PASS gcode_emit")


# ----------------------------------------------------- engine/stock.py tests
SB = (-20.0, 20.0, -10.0, 30.0, 0.0, 10.0)  # xmin xmax ymin ymax zmin zmax
SR = 3.0


def test_stock_mill_and_region():
    """Milling a level lowers the stock top under the footprint only; the
    region mask then excludes cleared cells and keeps the rest."""
    sf = StockField(SB, cell=0.5)
    assert sf.top_at(0.0, 10.0) == 10.0          # stock top everywhere
    assert sf.top_at(-25.0, 10.0) == -float("inf")  # outside the box
    sf.mill_path([(-19.0, 5.0), (-1.0, 5.0)], 8.0, SR)
    assert sf.top_at(-10.0, 5.0) <= 8.0 + 1e-9   # under the path: cut to z
    assert sf.top_at(-10.0, 5.0 + SR - 0.05) <= 8.0 + 1e-9  # inside radius
    assert sf.top_at(-10.0, 5.0 + SR + 0.3) > 9.9  # outside: untouched
    # level 6.0: cleared to 8.0 still leaves stock above 6.0 + leave
    m = sf.region_mask(6.0, axial_leave=0.5)
    # level 8.0: nothing left above 8.0 + leave there -> excluded
    m2 = sf.region_mask(8.0, axial_leave=0.5)
    i, j = sf._ci(-10.0), sf._cj(5.0)
    assert m[j, i] and not m2[j, i]
    assert m[int(sf.ny / 2) + 30, int(sf.nx / 2)]  # far corner still stock
    print("PASS stock mill/region")


def test_stock_bull_footprint():
    """Bull corner band: cells between r-cr and r are left up to cr high."""
    sf = StockField(SB, cell=0.5)
    cx, cy = 0.25, 9.75  # exact cell centres of this grid
    sf.mill_segment(cx, cy, cx, cy, 5.0, SR, corner_r=0.5)  # plunge disk
    assert abs(sf.top_at(cx, cy) - 5.0) < 1e-9  # flat centre
    dx, dy = 2.5, 1.5  # diagonal cell-centre offset, d ~ 2.915 in the band
    d = math.hypot(dx, dy)
    expect = 5.0 + 0.5 - math.sqrt(0.25 - (d - 2.5) ** 2)
    assert abs(sf.top_at(cx + dx, cy + dy) - expect) < 0.01
    assert abs(sf.top_at(cx, cy + SR) - 5.5) < 0.01  # at r: full cr high
    assert sf.top_at(cx, cy + SR + 0.25) > 9.9        # outside the disk
    print("PASS stock bull footprint")


def test_stock_contours():
    """Marching squares: solid box -> one CCW outer at the box edge; donut
    -> outer + CW hole (classification by containment, not stitch order)."""
    sf = StockField(SB, cell=0.5)
    m = sf.inb.copy()
    outers, holes = sf.contours(m)
    assert len(outers) == 1 and len(holes) == 0
    xs = [p[0] for p in outers[0]]
    ys = [p[1] for p in outers[0]]
    assert abs(min(xs) - SB[0]) < 0.01 and abs(max(xs) - SB[1]) < 0.01
    assert abs(min(ys) - SB[2]) < 0.01 and abs(max(ys) - SB[3]) < 0.01
    area2 = sum(outers[0][i][0] * outers[0][(i + 1) % len(outers[0])][1] -
                outers[0][(i + 1) % len(outers[0])][0] * outers[0][i][1]
                for i in range(len(outers[0])))
    assert area2 > 0, "outer loop must be CCW"
    # donut: clear a disk at (0, 10) r=4
    import numpy as np
    ys2 = sf.y0 + (np.arange(sf.ny) + 0.5) * sf.cell
    xs2 = sf.x0 + (np.arange(sf.nx) + 0.5) * sf.cell
    X, Y = np.meshgrid(xs2, ys2)
    m2 = sf.inb & ~((X - 0.0) ** 2 + (Y - 10.0) ** 2 <= 4.0 ** 2)
    outers, holes = sf.contours(m2)
    assert len(outers) == 1 and len(holes) == 1
    area2 = sum(holes[0][i][0] * holes[0][(i + 1) % len(holes[0])][1] -
                holes[0][(i + 1) % len(holes[0])][0] * holes[0][i][1]
                for i in range(len(holes[0])))
    assert area2 < 0, "hole loop must be CW"
    print("PASS stock contours")


def test_stock_links_and_stepups():
    """Link clearance follows the model; step-up level plan matches James's
    cutting-data pattern (big level, climb grid, floor, climb grid)."""
    sf = StockField(SB, cell=0.5)
    sf.set_tool(SR)
    assert not sf.link_clear([(-10.0, 5.0), (10.0, 5.0)], 8.0)  # solid stock
    sf.mill_path([(-19.0, 5.0), (19.0, 5.0)], 8.0, SR)
    sf.refresh_tool()
    assert sf.link_clear([(-15.0, 5.0), (15.0, 5.0)], 8.0)
    assert not sf.link_clear([(-15.0, 5.0), (15.0, 5.0)], 7.9)
    assert sf.rise_clear(-15.0, 5.0, 8.0, 9.9)
    assert not sf.rise_clear(-15.0, -5.0, 8.0, 9.9)  # unmilled cell
    zs = plan_stepup_levels(60.96, 24.95, stepdown=19.05, stepup=1.905)
    assert zs[0] == 41.91 and 24.95 in zs
    i_floor = zs.index(24.95)
    assert abs(zs[i_floor + 1] - 26.855) < 1e-9   # climb after the floor
    for want in (43.815, 45.72, 47.625):
        assert any(abs(z - want) < 1e-9 for z in zs[:i_floor]), \
            "step-up %.3f must execute before the floor level" % want
    climb_after_floor = zs[i_floor + 1:]
    assert any(abs(z - 36.38) < 1e-9 for z in climb_after_floor)
    assert any(abs(z - 40.19) < 1e-9 for z in climb_after_floor)
    # candidates within min_level_gap of an earlier level are dropped
    assert not any(abs(z - 42.095) < 1e-9 for z in zs)
    assert all(z <= 60.96 - 0.381 + 1e-9 for z in zs)
    print("PASS stock links/step-ups: %d candidates" % len(zs))


def test_island_clear_fn():
    """island_clear_fn must return a per-point bool LIST (truthiness of the
    list itself once hid a clearance bug: `not isl_ok([p])` is always False).
    Points within `req` of the loop fail, points farther away pass, and
    points INSIDE an island loop always fail (R1: distance-only checks let
    centres deep inside a loop through - the no-hf gouge)."""
    from engine.rough import island_clear_fn
    sq = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    f = island_clear_fn([sq], 2.0)
    out = f([(5.0, 5.0), (12.05, 5.0), (11.0, 5.0), (5.0, -1.9)])
    assert isinstance(out, list) and len(out) == 4
    assert out == [False, True, False, False], out   # (5,5) is inside: fail
    # far outside passes
    assert f([(20.0, 5.0)]) == [True]
    # empty island set -> everything clear
    g = island_clear_fn([], 2.0)
    assert all(g([(0.0, 0.0), (99.0, 99.0)]))
    print("PASS island_clear_fn list semantics + containment")


def test_allowance_violation_containment():
    """R1: allowance_violation must flag centres INSIDE an island loop even
    when they are far from the loop line (the original blind spot)."""
    big = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
    v = allowance_violation([(50.0, 50.0)], [big], 3.0, 0.5)
    assert v is not None and v[2] == 0.0, \
        "centre inside island loop not flagged: %r" % (v,)
    assert allowance_violation([(105.0, 50.0)], [big], 3.0, 0.5) is None
    print("PASS allowance_violation containment")


# ------------------------------------------- R1: rough without --hf is safe
def _box_tris(x0, x1, y0, y1, z0, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
         (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
         (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [(v[a], v[b], v[c]) for a, b, c in f]


def _write_stl(path, tris):
    with open(path, "w") as fh:
        fh.write("solid s\n")
        for (p, q, r) in tris:
            fh.write(" facet normal 0 0 0\n  outer loop\n")
            for v in (p, q, r):
                fh.write("   vertex %.4f %.4f %.4f\n" % v)
            fh.write("  endloop\n endfacet\n")
        fh.write("endsolid s\n")


def test_rough_without_hf_safe():
    """R1 supervisor bug: `rough` WITHOUT --hf gouged the part (no part
    heightfield -> stock.part None -> every pz/min_rest clip and the
    island punch-out silently degraded, and with the small feature's
    waterline loop below min_perimeter the island post-check was blind).
    Synthetic slab + small tall boss (loop perimeter < 20 mm): roughing
    without hf must produce ZERO gouges under the engine's own drop-cutter
    and output identical to passing --hf explicitly."""
    if not HAVE_AREA:
        print("SKIP test_rough_without_hf_safe (no area module)")
        return
    import tempfile
    from opencamlib import ocl
    from engine.rough import rough, build_part_hf
    tris = _box_tris(-15.0, 15.0, -10.0, 10.0, 0.0, 8.0)
    tris += _box_tris(-2.0, 2.0, -2.0, 2.0, 8.0, 20.0)
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "slab_boss.stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        assert surf.size() == 24
        stock_box = (-16.0, 16.0, -11.0, 11.0, 0.0, 21.0)
        kw = dict(leave=0.381, axial_leave=0.381, stepdown=8.0, stepup=1.5,
                  stl_path=stl, workers=None, threads=1, stock_cell=0.5)
        moves_no, _ = rough(surf, stock_box, 3.175, 0.0, **kw)
        sf = StockField(stock_box, cell=0.5)
        hf = build_part_hf(surf, sf.x0, sf.y0, sf.cell, sf.nx, sf.ny,
                           threads=1, drop_z=-1.0)
        moves_hf, _ = rough(surf, stock_box, 3.175, 0.0,
                            part_hf=(hf, sf.x0, sf.y0, sf.cell), **kw)
        assert moves_no and len(moves_no) == len(moves_hf), \
            "no-hf output differs in length from --hf output"
        assert moves_no == moves_hf, "no-hf output differs from --hf output"
        # gouge check with the engine's own drop-cutter (ocl), not verify/zmap
        xs, ys, zs = [], [], []
        prev = None
        for mv in moves_no:
            cur = (mv["x"], mv["y"], mv["z"])
            if prev is not None and mv["g"] == 1:
                n = max(1, int(math.dist(prev[:2], cur[:2]) / 0.5) + 1)
                for t in range(1, n + 1):
                    f = t / n
                    xs.append(prev[0] + (cur[0] - prev[0]) * f)
                    ys.append(prev[1] + (cur[1] - prev[1]) * f)
                    zs.append(prev[2] + (cur[2] - prev[2]) * f)
            prev = cur
        cl = [None] * len(xs)
        CH = 4000
        for a in range(0, len(xs), CH):
            bd = ocl.BatchDropCutter()
            bd.setSTL(surf)
            bd.setCutter(ocl.CylCutter(3.175, 50.0))
            for i in range(a, min(a + CH, len(xs))):
                bd.appendPoint(ocl.CLPoint(float(xs[i]), float(ys[i]), -50.0))
            bd.run()
            cl[a:a + CH] = [p.z for p in bd.getCLPoints()]
        worst = max(c - z for c, z in zip(cl, zs))
        assert worst <= 0.05, \
            "no-hf roughing gouges %.3f mm below the part" % worst
        print("PASS rough without hf: %d moves identical to --hf, "
              "drop-cutter worst %.3f mm (no gouge)" % (len(moves_no), worst))


# ------------------------------------------- R2: drop-cutter islands, clcheck
TB_STL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "out", "test_block.stl")
TB_HF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "out", "test_block_hf_0.5.npy")


def test_rough_testblock_r2():
    """R2 (safety-critical) on samples/test_block with James's cutting data:
    * rough CLCHECK gate: actual-cutter drop-cutter on every cutting move
      (sampled <= 0.1 mm) -> tip must stay >= CL + axial_leave - 0.005
      (this also proves 0 gouges, axl 0 being the weaker check);
    * the mandatory flat-floor level Z27 + leave = 27.381 is present and
      runs, and the engine stock model shows that pocket floor ending
      0.381 +- 0.02 mm high;
    * regression for the fillet-meets-vertical-corner point (-17.56, 13.87)
      where the old OCL-waterline islands let the level-29.906 path run
      3.72 mm below CL: leave must be honoured there too."""
    if not (HAVE_AREA and os.path.exists(TB_STL) and os.path.exists(TB_HF)):
        print("SKIP test_rough_testblock_r2 (no area or out/test_block.*)")
        return
    import tempfile
    import json as _json
    import numpy as np
    from opencamlib import ocl
    from engine.rough import rough, actual_cutter
    from engine.probe_rough_clcheck import clcheck_moves
    surf = ocl.STLSurf()
    ocl.STLReader(TB_STL, surf)
    part = np.load(TB_HF)
    with open(TB_HF[:-4] + ".json") as fh:
        meta = _json.load(fh)
    hx0, hy0, hcell = float(meta["x0"]), float(meta["y0"]), float(meta["cell"])
    stock_box = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
    kw = dict(leave=0.381, axial_leave=0.381, stepdown=19.05, stepover=0.16,
              stl_path=TB_STL, workers=None, threads=4, stock_cell=0.5,
              final_zmin=20.381, part_hf=(part, hx0, hy0, hcell))
    with tempfile.TemporaryDirectory() as td:
        stock_out = os.path.join(td, "stock.npy")
        moves, stats = rough(surf, stock_box, 6.343, 20.0,
                            stock_out=stock_out, **kw)
        assert moves, "no moves"
        # 1. independent CLCHECK gate: 0 violations with leave, and the
        # weaker axl=0 check proves zero gouges.
        cutter = actual_cutter(6.343)
        viol = clcheck_moves(surf, cutter, moves, 0.381, ss=0.1, tol=0.005)
        assert not viol, "rough clcheck: %d violations, worst move %d at " \
            "(%.2f, %.2f) Z=%.3f, %.3f mm below CL + axl" % (
                len(viol), viol[0][0], viol[0][1], viol[0][2], viol[0][3],
                viol[0][4])
        gouge = clcheck_moves(surf, cutter, moves, 0.0, ss=0.1, tol=0.005)
        assert not gouge, "gouges: %d samples below CL, worst move %d at " \
            "(%.2f, %.2f) Z=%.3f, %.3f mm below CL" % (
                len(gouge), gouge[0][0], gouge[0][1], gouge[0][2],
                gouge[0][3], gouge[0][4])
        # 2. mandatory Z27 pocket level present, ran, and floor ends 0.381
        lvl27 = [l for l in stats["levels"] if l["z"] == 27.381]
        assert lvl27 and not lvl27[0].get("skipped"), \
            "Z27 pocket level 27.381 missing or skipped: %s" % stats["levels"]
        assert 27.381 in [round(z, 3) for z in stats.get(
            "mandatory_levels", [])], "27.381 not flagged mandatory"
        st = np.load(stock_out)
        with open(stock_out[:-4] + ".json") as fh:
            sm = _json.load(fh)
        sx0, sy0, scell = float(sm["x0"]), float(sm["y0"]), float(sm["cell"])
        pj, pi = np.nonzero(np.abs(part - 27.0) < 0.01)
        # plateau-27 cells the tool can actually reach at 27.381: no taller
        # part (frame/boss > 27.01) within tool_r + leave + one cell, and
        # >= tool_r + leave from the stock walls - there the floor must be
        # flat at level Z; nearer the walls the corner band is rest material.
        tall = (part > 27.01) & np.isfinite(part)
        reach = int(math.ceil((6.343 + 0.381 + 0.5) / hcell))
        offs = [(dj, di) for dj in range(-reach, reach + 1)
                for di in range(-reach, reach + 1)
                if (dj * dj + di * di) * hcell * hcell
                <= (6.343 + 0.381 + 0.5) ** 2]
        near_tall = np.zeros_like(tall)
        for dj, di in offs:
            js0, js1 = max(0, dj), min(part.shape[0], part.shape[0] + dj)
            is0, is1 = max(0, di), min(part.shape[1], part.shape[1] + di)
            near_tall[js0:js1, is0:is1] |= \
                tall[js0 - dj:js1 - dj, is0 - di:is1 - di]
        ok = []
        for j, i in zip(pj, pi):
            if near_tall[j, i]:
                continue
            x = hx0 + i * hcell
            y = hy0 + j * hcell
            if not (sx0 + 6.724 <= x <= sx0 + st.shape[1] * scell - 6.724
                    and sy0 + 6.724 <= y <= sy0 + st.shape[0] * scell - 6.724):
                continue
            si = int(round((x - sx0) / scell))
            sj = int(round((y - sy0) / scell))
            if 0 <= si < st.shape[1] and 0 <= sj < st.shape[0]:
                ok.append(st[sj, si])
        assert ok, "no plateau-27 interior cells found"
        med = float(np.median(ok))
        assert abs(med - 27.381) <= 0.02, \
            "Z27 pocket floor ends %.3f high (want 0.381 +- 0.02)" % (med - 27.0)
        assert min(ok) >= 27.381 - 0.02, \
            "Z27 pocket floor cut %.3f mm BELOW leave" % (27.381 - min(ok))
        # 3. fillet-meets-vertical-corner regression at (-17.56, 13.87):
        # the OLD waterline islands let the level-29.906 path put a cutter
        # CENTRE there (G-code line 20741), tip 3.72 mm below the true CL
        # (33.626). Now every horizontal cutting centre within 0.5 mm of
        # that XY must have its tip >= CL(centre) + axial_leave - 0.005
        # (and with CL ~33.6 here, that means no centre at all below 34.0).
        rx, ry = -17.56, 13.87
        pts_near = []
        prev = None
        for mv in moves:
            cur = (mv["x"], mv["y"], mv["z"])
            if prev is not None and mv["g"] == 1 and \
                    abs(cur[2] - prev[2]) < 1e-9:   # horizontal cutting only
                L = math.dist(prev[:2], cur[:2])
                k = max(1, int(L / 0.1) + 1)
                for t in range(1, k + 1):
                    f = t / k
                    px = prev[0] + (cur[0] - prev[0]) * f
                    py = prev[1] + (cur[1] - prev[1]) * f
                    if math.dist((px, py), (rx, ry)) <= 0.5:
                        pts_near.append((px, py, cur[2]))
            prev = cur
        worst = -1e9
        if pts_near:
            bd = ocl.BatchDropCutter()
            bd.setSTL(surf)
            bd.setCutter(cutter)
            for px, py, _z in pts_near:
                bd.appendPoint(ocl.CLPoint(px, py, -50.0))
            bd.run()
            for p, (_px, _py, z) in zip(bd.getCLPoints(), pts_near):
                worst = max(worst, float(p.z) + 0.381 - z)
        assert worst <= 0.005, \
            "leave violated near (-17.56, 13.87): %.3f mm below CL + axl " \
            "(%d centres nearby)" % (worst, len(pts_near))
        print("PASS rough test-block R2: %d moves, clcheck 0, floor Z27 "
              "ends %.3f high, corner regression: %d centres near "
              "(-17.56, 13.87), worst %.3f mm vs CL + axl"
              % (len(moves), med - 27.0, len(pts_near), worst))


def _pocket_block_stl(path, half=14.0, ztop=8.0, pk_half=8.0, pk_floor=4.0):
    """ASCII STL: block +-half x, +-half y, 0..ztop with an open-top square
    pocket +-pk_half down to pk_floor (28 triangles, synth_pocket shape)."""
    h, t, w, f = half, ztop, pk_half, pk_floor

    def quad(a, b, c, d):
        return [(a, b, c), (a, c, d)]

    tris = []
    tris += quad((-h, -h, 0), (-h, h, 0), (h, h, 0), (h, -h, 0))       # bottom
    tris += quad((h, -h, 0), (h, h, 0), (h, h, t), (h, -h, t))         # +X wall
    tris += quad((-h, -h, 0), (-h, -h, t), (-h, h, t), (-h, h, 0))     # -X wall
    tris += quad((-h, h, 0), (-h, h, t), (h, h, t), (h, h, 0))         # +Y wall
    tris += quad((-h, -h, 0), (-h, -h, t), (h, -h, t), (h, -h, 0))     # -Y wall
    # top ring z=t between +-h and +-w, split into four trapezoids
    tris += quad((-h, -h, t), (h, -h, t), (w, -w, t), (-w, -w, t))
    tris += quad((h, -h, t), (h, h, t), (w, w, t), (w, -w, t))
    tris += quad((h, h, t), (-h, h, t), (-w, w, t), (w, w, t))
    tris += quad((-h, h, t), (-h, -h, t), (-w, -w, t), (-w, w, t))
    tris += quad((-w, -w, f), (w, -w, f), (w, w, f), (-w, w, f))       # floor
    # pocket walls
    tris += quad((w, -w, f), (w, w, f), (w, w, t), (w, -w, t))
    tris += quad((-w, -w, f), (-w, -w, t), (-w, w, t), (-w, w, f))
    tris += quad((-w, w, f), (w, w, f), (w, w, t), (-w, w, t))
    tris += quad((-w, -w, f), (-w, -w, t), (w, -w, t), (w, -w, f))
    with open(path, "w") as fh:
        fh.write("solid pocket_block\n")
        for a, b, c in tris:
            fh.write(" facet normal 0 0 0\n  outer loop\n")
            for p in (a, b, c):
                fh.write("   vertex %.4f %.4f %.4f\n" % p)
            fh.write("  endloop\n endfacet\n")
        fh.write("endsolid pocket_block\n")
    return path


def test_islands_grid_edge_parity():
    """R3 regression: when the forbidden region F reaches the CL grid border
    (grid does not cover the outer CL jump), level_islands must still EXCLUDE
    cutter centres next to the pocket walls - silently dropping the open
    circuit flipped even-odd parity and admitted them (synth_pocket failure:
    centre at (-6.4, 23.508), 0.39 mm from the wall, at Z=4.381)."""
    if not HAVE_AREA:
        print("SKIP islands_grid_edge_parity (no area)")
        return
    import tempfile
    import numpy as np
    from opencamlib import ocl
    from engine.rough import big_cutter, cl_island_grid, level_islands, \
        _inside_loops
    with tempfile.TemporaryDirectory() as td:
        stl = _pocket_block_stl(os.path.join(td, "pb.stl"),
                                half=14.0, ztop=8.0, pk_half=8.0, pk_floor=4.0)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        assert surf.size() >= 24, "pocket-block STL too small: %d" \
            % surf.size()
        cbig = big_cutter(3.0, 0.381)
        # clipped grid: F's outer border (pk_half + R = 11.381) is outside
        gxs, gys, Zg = cl_island_grid(surf, cbig, -10.0, -10.0, 10.0, 10.0,
                                      0.5)
        isl, Fm = level_islands(surf, cbig, Zg, gxs, gys, 4.381, 0.381)
        assert isl, "no islands although F touches the clipped grid border"
        P = np.array([[0.0, 0.0], [0.0, 6.0], [-6.4, 7.5]])
        ins = _inside_loops(P, isl)
        assert not ins[0], "pocket centre wrongly forbidden (parity inverted)"
        assert ins[1:].all(), \
            "centres 2 mm from the pocket wall admitted at clipped-grid edge"
        # unclipped grid: F closes inside (outer jump at 14 + R = 17.381),
        # no fence, parity unchanged
        gxs, gys, Zg = cl_island_grid(surf, cbig, -18.0, -18.0, 18.0, 18.0,
                                      0.5)
        isl2, Fm2 = level_islands(surf, cbig, Zg, gxs, gys, 4.381, 0.381)
        assert len(isl2) == 2, "unclipped islands: %d loops" % len(isl2)
        ins = _inside_loops(P, isl2)
        assert (not ins[0]) and ins[1:].all(), "unclipped parity wrong"
        print("PASS islands grid-edge parity: clipped %d loops, unclipped "
              "%d loops" % (len(isl), len(isl2)))


def _check_pocket_block(pkl, label):
    """rough() end-to-end on a pocket-in-block: no backstop/clcheck violation
    (rough raises on any) and every horizontal cutting centre below the block
    top sits >= tool_r + leave - 0.02 from the pocket walls."""
    import numpy as np
    import tempfile
    from opencamlib import ocl
    from engine.rough import rough, actual_cutter
    from engine.probe_rough_clcheck import clcheck_moves
    tool_r, leave = 3.0, 0.381
    req = tool_r + leave - 0.02
    with tempfile.TemporaryDirectory() as td:
        stl = _pocket_block_stl(os.path.join(td, "pb.stl"), half=14.0,
                                ztop=8.0, pk_half=pkl, pk_floor=4.0)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        box = (-14.2, 14.2, -14.2, 14.2, -1.0, 8.4)
        moves, stats = rough(surf, box, tool_r, 4.0, leave=leave,
                            axial_leave=leave, stepdown=4.0, stepup=1.905,
                            stepover=2.0 / 6.0, tolerance=0.05, threads=4,
                            stock_cell=0.5, min_rest=0.5, corner_r=0.0)
        assert moves or label == "narrow", "no moves (%s)" % label
        if not moves:
            return 0, stats
        bad = clcheck_moves(surf, actual_cutter(tool_r), moves, leave,
                            ss=0.1, tol=0.005)
        assert not bad, "%s clcheck: %d violations, worst move %d at " \
            "(%.2f, %.2f) Z=%.3f" % (label, len(bad), bad[0][0], bad[0][1],
                                     bad[0][2], bad[0][3])
        prev = None
        n_below = 0
        for mv in moves:
            cur = (mv["x"], mv["y"], mv["z"])
            if prev is not None and mv["g"] == 1 and \
                    abs(cur[2] - prev[2]) < 1e-9 and cur[2] < 8.0 - 0.02:
                L = math.dist(prev[:2], cur[:2])
                k = max(1, int(L / 0.1) + 1)
                for t in range(1, k + 1):
                    f = t / k
                    px = prev[0] + (cur[0] - prev[0]) * f
                    py = prev[1] + (cur[1] - prev[1]) * f
                    n_below += 1
                    assert pkl - max(abs(px), abs(py)) >= req, \
                        "%s: centre (%.3f, %.3f) at Z=%.3f is %.3f mm from " \
                        "the pocket wall, need >= %.3f" % (
                            label, px, py, cur[2],
                            pkl - max(abs(px), abs(py)), req)
            prev = cur
        return n_below, stats


def test_rough_pocket_in_block():
    """R3: synthetic pocket-in-block, wide and narrow pocket.
    Wide (16 mm): the floor level runs and every cutter centre below the
    block top keeps >= tool_r + leave from the pocket walls.
    Narrow (5 mm < tool + 2x leave): the tool can never enter - no cutting
    centres below the block top at all, and nothing raises the backstop."""
    if not HAVE_AREA:
        print("SKIP rough_pocket_in_block (no area)")
        return
    n_wide, stats_w = _check_pocket_block(8.0, "wide")
    assert n_wide > 0, "wide pocket: no cutting below the block top"
    floor_lvl = [l for l in stats_w["levels"] if l["z"] == 4.381]
    assert floor_lvl and not floor_lvl[0].get("skipped"), \
        "wide pocket floor level 4.381 skipped: %s" % stats_w["levels"]
    n_narrow, _ = _check_pocket_block(2.5, "narrow")
    assert n_narrow == 0, \
        "narrow pocket admitted %d centres below the block top" % n_narrow
    print("PASS rough pocket-in-block: wide %d sub-top centre samples, "
          "narrow 0 (tool never enters)" % n_wide)


def test_rough_synth_pocket_repro():
    """R3 supervisor repro: connector/testdata/synth_pocket.step with James's
    data must produce a program with 0 hf-backstop / clcheck violations (the
    R2 islands admitted (-6.400, 23.508) at Z=4.381, 7.619 mm below the
    part hf)."""
    step = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "connector", "testdata",
        "synth_pocket.step")
    if not (HAVE_AREA and os.path.exists(step)):
        print("SKIP rough_synth_pocket_repro (no area or synth_pocket.step)")
        return
    import tempfile
    from opencamlib import ocl
    from engine import model
    from engine.rough import rough, actual_cutter
    from engine.probe_rough_clcheck import clcheck_moves
    stl = model.step_to_stl(step)
    surf = ocl.STLSurf()
    ocl.STLReader(stl, surf)
    with tempfile.TemporaryDirectory() as td:
        moves, stats = rough(surf, (-31.0, 31.0, -31.0, 31.0, -1.0, 12.4),
                            3.0, 3.0, leave=0.381, axial_leave=0.381,
                            stepdown=4.0, stepup=1.905, stepover=2.0 / 6.0,
                            tolerance=0.05, threads=4, stock_cell=0.5,
                            min_rest=0.5, corner_r=0.0, stl_path=stl,
                            stock_out=os.path.join(td, "stock.npy"))
        assert moves, "no moves"
        bad = clcheck_moves(surf, actual_cutter(3.0), moves, 0.381, ss=0.1,
                           tol=0.005)
        assert not bad, "synth_pocket clcheck: %d violations, worst move %d " \
            "at (%.2f, %.2f) Z=%.3f" % (len(bad), bad[0][0], bad[0][1],
                                        bad[0][2], bad[0][3])
        assert stats.get("clcheck_violations", 0) == 0
        # R5: no rapid may pass through uncut stock (engine's own model)
        n_bad, worst = _rapids_clear_stock(moves, os.path.join(td, "stock.npy"),
                                           3.0, 1.0)
        assert n_bad == 0, "synth_pocket rapids through stock: %d, worst %s" \
            % (n_bad, worst)
        assert stats.get("n_rapid_bumps", 0) > 0, \
            "no rapid heights were lifted by the live-stock check - the " \
            "R5 verification never engaged"
    print("PASS rough synth_pocket repro: %d moves, backstop + clcheck 0, "
          "rapids clear live stock (%d lifted)" % (len(moves), stats.get(
              "n_rapid_bumps", 0)))


def _rapids_clear_stock(moves, stock_npy, tool_r, margin=1.0, pad=1.0):
    """R5 check with the ENGINE's own stock model (verify/zmap.py is NOT
    used): every G0 must sit >= margin above max(stock top within
    tool_r + pad of the swept path) in the final stock heightfield that
    rough() exported (--stock-out). The final model is a LOWER bound on the
    live model at emit time (stock only shrinks), so a violation here means
    the rapid definitely passed through material that was never cut.
    Returns (n_violations, worst_desc)."""
    import json
    import numpy as np
    A = np.load(stock_npy)
    with open(os.path.splitext(stock_npy)[0] + ".json") as fh:
        meta = json.load(fh)
    x0, y0, cell = meta["x0"], meta["y0"], meta["cell"]
    ny, nx = A.shape
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    R = tool_r + pad
    k = int(math.ceil(R / cell))
    prev = (moves[0]["x"], moves[0]["y"], moves[0]["z"])
    n_bad = 0
    worst = None
    for mv in moves:
        cur = (mv.get("x", prev[0]), mv.get("y", prev[1]), mv.get("z", prev[2]))
        if mv["g"] == 0:
            L = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            n = max(1, int(L / (0.5 * cell)) + 1)
            for t in range(1, n + 1):          # skip start: validated before
                sx = prev[0] + (cur[0] - prev[0]) * t / n
                sy = prev[1] + (cur[1] - prev[1]) * t / n
                i0 = int(math.floor((sx - x0) / cell))
                j0 = int(math.floor((sy - y0) / cell))
                ilo, ihi = max(0, i0 - k), min(nx, i0 + k + 1)
                jlo, jhi = max(0, j0 - k), min(ny, j0 + k + 1)
                if ilo >= ihi or jlo >= jhi:
                    continue                   # outside tracked grid
                win = A[jlo:jhi, ilo:ihi]
                d = np.hypot(xs[ilo:ihi][None, :] - sx,
                            ys[jlo:jhi][:, None] - sy)
                m = (d <= R) & np.isfinite(win)
                if not m.any():
                    continue
                mx = float(win[m].max())
                if cur[2] < mx + margin - 1e-3:
                    n_bad += 1
                    desc = ("(%s) (%.3f, %.3f) Z%.3f over stock %.3f"
                          % (mv.get("line", "?"), sx, sy, cur[2], mx))
                    if worst is None or (mx + margin - cur[2]) > worst[1]:
                        worst = (desc, mx + margin - cur[2])
        prev = cur
    return n_bad, (worst[0] if worst else None)


def _two_level_stl(path, half=14.0, z_hi=8.0, z_lo=5.0):
    """ASCII STL: block +-half x, +-half y, 0..z_hi with the half y<0 milled
    down to a shelf at z_lo (single step wall at y=0) - two machining
    levels, so roughing links must climb over the step."""
    h, t, s = half, z_hi, z_lo

    def quad(a, b, c, d):
        return [(a, b, c), (a, c, d)]

    tris = []
    tris += quad((-h, -h, 0), (-h, h, 0), (h, h, 0), (h, -h, 0))   # bottom
    tris += quad((h, -h, 0), (h, h, 0), (h, h, t), (h, -h, t))     # +X wall
    tris += quad((-h, -h, 0), (-h, -h, t), (-h, h, t), (-h, h, 0))  # -X wall
    tris += quad((-h, h, 0), (-h, h, t), (h, h, t), (h, h, 0))     # +Y wall
    tris += quad((-h, -h, 0), (-h, -h, s), (h, -h, s), (h, -h, 0))  # -Y wall
    tris += quad((-h, -h, s), (-h, 0, s), (h, 0, s), (h, -h, s))   # shelf
    tris += quad((-h, 0, s), (-h, h, t), (h, h, t), (h, 0, s))      # top
    tris += quad((-h, 0, s), (-h, 0, t), (-h, h, t), (-h, h, s))    # -X step
    tris += quad((h, 0, s), (h, 0, t), (h, h, t), (h, h, s))        # +X step
    tris += quad((-h, 0, s), (-h, 0, t), (h, 0, t), (h, 0, s))      # step
    with open(path, "w") as fh:
        fh.write("solid two_level\n")
        for a, b, c in tris:
            fh.write(" facet normal 0 0 0\n  outer loop\n")
            for p in (a, b, c):
                fh.write("   vertex %.4f %.4f %.4f\n" % p)
            fh.write("  endloop\n endfacet\n")
        fh.write("endsolid two_level\n")
    return path


def test_rough_rapids_clear_stock():
    """R5: roughing rapids must clear the LIVE stock. Two-level synthetic
    part (shelf 5 / top 8): the step stands above the lower level's lift
    plane, so straight-over-it traverses must be lifted to a verified
    height; no G0 may sit within margin of uncut stock (engine's own
    --stock-out heightfield as the check, no verify/zmap import)."""
    if not HAVE_AREA:
        print("SKIP rough_rapids_clear_stock (no area)")
        return
    import tempfile
    from opencamlib import ocl
    from engine.rough import rough, actual_cutter
    from engine.probe_rough_clcheck import clcheck_moves
    with tempfile.TemporaryDirectory() as td:
        stl = _two_level_stl(os.path.join(td, "two_level.stl"))
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        moves, stats = rough(surf, (-14.2, 14.2, -14.2, 14.2, -1.0, 8.0),
                            3.0, 5.0, leave=0.381, axial_leave=0.381,
                            stepdown=4.0, stepup=1.905, stepover=2.0 / 6.0,
                            tolerance=0.05, threads=4, stock_cell=0.5,
                            min_rest=0.5, corner_r=0.0, stl_path=stl,
                            stock_out=os.path.join(td, "stock.npy"))
        assert moves, "no moves"
        bad = clcheck_moves(surf, actual_cutter(3.0), moves, 0.381, ss=0.1,
                           tol=0.005)
        assert not bad, "two-level clcheck: %d violations, worst move %d" % (
            len(bad), bad[0][0] if bad else -1)
        assert stats.get("n_rapid_bumps", 0) > 0, \
            "step-up/lift rapids never verified against the step - no " \
            "height was lifted"
        n_bad, worst = _rapids_clear_stock(moves, os.path.join(td, "stock.npy"),
                                           3.0, 1.0)
        assert n_bad == 0, "two-level rapids through stock: %d, worst %s" \
            % (n_bad, worst)
    print("PASS rough rapids clear stock: two-level %d moves, %d rapids "
          "lifted to verified heights" % (len(moves), stats["n_rapid_bumps"]))


def _main():
    fails = 0
    for fn in (test_adaptive2d_offset_convention, test_plan_levels,
               test_plan_levels_cutting_data, test_allowance_violation,
               test_decimate, test_gcode_emit,
               test_stock_mill_and_region, test_stock_bull_footprint,
               test_stock_contours, test_stock_links_and_stepups,
               test_island_clear_fn, test_allowance_violation_containment,
               test_rough_without_hf_safe, test_rough_testblock_r2,
               test_islands_grid_edge_parity, test_rough_pocket_in_block,
               test_rough_synth_pocket_repro, test_rough_rapids_clear_stock):
        try:
            fn()
        except AssertionError as e:
            fails += 1
            print("FAIL %s: %s" % (fn.__name__, e))
    print("%d failure(s)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_main())
