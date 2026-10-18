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


def test_plan_levels_fusion_settings():
    """Task F: stepdown 19.05, axial leave, explicit final ZMIN matching
    Fusion, flat-area levels at floor + axial leave."""
    floors = [42.463, 42.545, 39.908, 39.224, 34.925, 24.765]
    zs = plan_levels(60.96, 24.765, 0.381, 19.05, flat_floors=floors,
                    axial_leave=0.381, final_zmin=24.95)
    assert abs(zs[-1] - 24.95) < 1e-9, "final level must match Fusion ZMIN"
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
    print("PASS plan_levels fusion settings: levels %r" % (zs,))


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
    big = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
    v2 = allowance_violation([(6.277, 50.0)], [big], 6.35, 0.3)
    assert v2 is not None and abs(v2[2] - 6.277) < 1e-9
    assert allowance_violation([(6.63, 50.0)], [big], 6.35, 0.3) is None
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
    """Link clearance follows the model; step-up level plan matches the
    Fusion pattern (big level, climb grid, floor, climb grid)."""
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
    Points within `req` of the loop fail, points farther away pass."""
    from engine.rough import island_clear_fn
    sq = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    f = island_clear_fn([sq], 2.0)
    out = f([(5.0, 5.0), (12.05, 5.0), (11.0, 5.0), (5.0, -1.9)])
    assert isinstance(out, list) and len(out) == 4
    assert out == [True, True, False, False], out
    # empty island set -> everything clear
    g = island_clear_fn([], 2.0)
    assert all(g([(0.0, 0.0), (99.0, 99.0)]))
    print("PASS island_clear_fn list semantics")


def _main():
    fails = 0
    for fn in (test_adaptive2d_offset_convention, test_plan_levels,
               test_plan_levels_fusion_settings, test_allowance_violation,
               test_decimate, test_gcode_emit,
               test_stock_mill_and_region, test_stock_bull_footprint,
               test_stock_contours, test_stock_links_and_stepups,
               test_island_clear_fn):
        try:
            fn()
        except AssertionError as e:
            fails += 1
            print("FAIL %s: %s" % (fn.__name__, e))
    print("%d failure(s)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_main())
