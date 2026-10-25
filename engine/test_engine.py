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



def _need(*paths):
    """A real-file fixture or tracked input is missing: FAIL (never skip) with the
    regenerate hint from fixtures/manifest.json."""
    import json as _json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        man = {f["path"]: f["regenerate"] for f in _json.load(
            open(os.path.join(root, "fixtures", "manifest.json")))["fixtures"]}
    except OSError:
        man = {}
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise AssertionError("missing fixture(s): " + "; ".join(
            "%s (regenerate: %s)" % (p, man.get(os.path.relpath(p, root),
                                               "tracked in git - restore it"))
            for p in missing))


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
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
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
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
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
TB_HF_01 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "out", "test_block_hf_0.1.npy")   # padded judge grid


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
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(TB_STL, TB_HF)
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


def test_rough_testblock_r4():
    """R4 (quality): pocket-corner reach on samples/test_block. In the four
    R6 corner zones of the Z27 pocket (30x22 at centre (12,-2)) a
    r 6.343 + 0.381 leave tool reaches everything except the crescent
    between the R6 corner arc and the tool arc. On the engine's own stock
    model every floor cell OUTSIDE the analytic crescent must end
    0.381 +- 0.05 mm high, and the material that stays standing must be
    ~the analytic crescent area (not the old margin-wide band)."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(TB_STL, TB_HF)
    import tempfile
    import json as _json
    import numpy as np
    from opencamlib import ocl
    from engine.rough import rough
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
        st = np.load(stock_out)
        with open(stock_out[:-4] + ".json") as fh:
            sm = _json.load(fh)
        sx0, sy0, scell = float(sm["x0"]), float(sm["y0"]), float(sm["cell"])
        X0, X1, Y0, Y1 = -3.0, 27.0, -13.0, 9.0     # pocket rect
        Rc, r_t, lv = 6.0, 6.343, 0.381
        R_eff = r_t + lv

        def dist_wall(x, y):
            d = np.minimum.reduce([x - X0, X1 - x, y - Y0, Y1 - y])
            for cx, cy, sx, sy in ((X0 + Rc, Y0 + Rc, -1, -1),
                                   (X1 - Rc, Y0 + Rc, 1, -1),
                                   (X1 - Rc, Y1 - Rc, 1, 1),
                                   (X0 + Rc, Y1 - Rc, -1, 1)):
                m = ((x - cx) * sx > 0) & ((y - cy) * sy > 0)
                d = np.where(m, np.minimum(d, Rc - np.hypot(x - cx, y - cy)), d)
            return d

        jj, ii = np.nonzero(np.isfinite(st))
        sxx = sx0 + (ii + 0.5) * scell
        syy = sy0 + (jj + 0.5) * scell
        h = st[jj, ii] - 27.0

        # analytic machinable set: legal centres C = {db >= R+leave+margin}.
        # Since Rc(6) < R+leave(6.724) the centre set is a SHARP rectangle
        # [X0+A, X1-A] x [Y0+A, Y1-A], A = R+leave+margin; a floor point is
        # machinable iff its distance to that rectangle is <= r_t. Points at
        # db >= leave but not machinable are the corner crescents.
        # margin (0.05) is what the engine's HARD gates physically permit:
        # the allowance post-check keeps every centre >= 0.025 mm outside the
        # refined forbidden loop, refinement rounds the loop outward by a few
        # microns and the ring's miter at the sharp centre-corner adds
        # ~eps*(sqrt2-1). Cells whose only centres sit inside that band
        # (reach margin < 0.05 mm at the R6 corners) count as crescent -
        # cutting them would require weakening a safety gate.
        ring_margin = 0.05
        A = R_eff + ring_margin

        def machinable(px, py):
            dx = np.maximum(np.maximum(X0 + A - px, px - (X1 - A)), 0.0)
            dy = np.maximum(np.maximum(Y0 + A - py, py - (Y1 - A)), 0.0)
            return np.hypot(dx, dy) <= r_t

        inside = (sxx > X0) & (sxx < X1) & (syy > Y0) & (syy < Y1)
        reach = inside & machinable(sxx, syy)
        bad_hi = reach & (h > 0.381 + 0.05)
        bad_lo = reach & (h < 0.381 - 0.05)
        # crescent area on a fine grid (margin-aware, matches what any legal
        # program can reach); ideal crescent uses margin 0 (centres exactly
        # at tool_r + leave from the walls).
        hq = 0.05
        gx = np.arange(X0 + hq / 2, X1, hq)
        gy = np.arange(Y0 + hq / 2, Y1, hq)
        GX, GY = np.meshgrid(gx, gy)
        dG = dist_wall(GX, GY)
        inQ = (GX > X0) & (GX < X1) & (GY > Y0) & (GY < Y1)
        cres_mm2 = float((inQ & ~machinable(GX, GY)).sum()) * hq * hq

        def mach_ideal(px, py):
            dx = np.maximum(np.maximum(X0 + R_eff - px, px - (X1 - R_eff)),
                           0.0)
            dy = np.maximum(np.maximum(Y0 + R_eff - py, py - (Y1 - R_eff)),
                           0.0)
            return np.hypot(dx, dy) <= r_t

        cres_ideal = float((inQ & ~mach_ideal(GX, GY)).sum()) * hq * hq
        left_mm2 = float((~reach & inside & (h > 0.381 + 0.05)).sum()) \
            * scell * scell
        # corner zone report (8x8 squares at the pocket corners)
        rep = []
        for ax0, ay0 in ((X0, Y0), (X1 - 8, Y0), (X0, Y1 - 8),
                         (X1 - 8, Y1 - 8)):
            zc = inside & (sxx >= ax0) & (sxx <= ax0 + 8) \
                & (syy >= ay0) & (syy <= ay0 + 8)
            rep.append("%.1f" % float((zc & ~reach).sum()) )
        assert not bad_hi.any(), \
            "%d pocket-floor cells outside the crescent end %.3f mm high " \
            "(want <= 0.431), worst at (%.2f, %.2f)" % (
                int(bad_hi.sum()), h[bad_hi].max(),
                sxx[bad_hi][int(np.argmax(h[bad_hi]))],
                syy[bad_hi][int(np.argmax(h[bad_hi]))])
        assert not bad_lo.any(), \
            "%d pocket-floor cells cut below axial leave (min %.3f)" % (
                int(bad_lo.sum()), h[bad_lo].min())
        assert abs(left_mm2 - cres_mm2) <= 0.15 * cres_mm2, \
            "leftover %.1f mm2 vs analytic crescent %.1f mm2" % (
                left_mm2, cres_mm2)
        print("PASS rough test-block R4: %d floor cells outside the crescent "
              "all end 0.381 +- 0.05 mm; leftover %.1f mm2 vs crescent %.1f "
              "mm2 (ideal %.1f); corner-zone rest cells [BL BR TL TR] = %s"
              % (int(reach.sum()), left_mm2, cres_mm2, cres_ideal, rep))


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


def test_rough_region_clipped_to_stock():
    """Task RS: the roughing cutting region must come from the --stock box
    (plus at most the tool radius for edge clean-up), never from the height-
    field grid bounds. Rough the test block with its normal --hf and with a
    copy of that hf padded by 20 mm of empty floor on every side (the
    supervisor's prepare grid was stock + tool radius + 5 mm and roughing cut
    over the whole grid: zmap outside_grid, 3,479 moves). Both outputs must
    keep every cutter-centre XY within stock +- tool radius (+0.01), and the
    cut length must differ by < 1 %."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(TB_STL, TB_HF)
    import json as _json
    import numpy as np
    from opencamlib import ocl
    from engine.rough import rough
    surf = ocl.STLSurf()
    ocl.STLReader(TB_STL, surf)
    part = np.load(TB_HF)
    with open(TB_HF[:-4] + ".json") as fh:
        meta = _json.load(fh)
    hx0, hy0, hcell = float(meta["x0"]), float(meta["y0"]), float(meta["cell"])
    stock_box = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
    tool_r = 6.343
    kw = dict(leave=0.381, axial_leave=0.381, stepdown=19.05, stepover=0.16,
              stl_path=TB_STL, workers=None, threads=4, stock_cell=0.5,
              final_zmin=20.381)

    def centres_outside(moves):
        lo_x, hi_x = stock_box[0] - tool_r - 0.01, stock_box[1] + tool_r + 0.01
        lo_y, hi_y = stock_box[2] - tool_r - 0.01, stock_box[3] + tool_r + 0.01
        return [(m["x"], m["y"], m["z"]) for m in moves if m["g"] == 1
                and not (lo_x <= m["x"] <= hi_x and lo_y <= m["y"] <= hi_y)]

    moves_a, stats_a = rough(surf, stock_box, tool_r, 20.0,
                            part_hf=(part, hx0, hy0, hcell), **kw)
    # pad the hf grid by 20 mm of empty floor (zmin) on every side
    pad_mm, fill = 20.0, float(meta.get("zmin", 0.0))
    k = int(round(pad_mm / hcell))
    padded = np.full((part.shape[0] + 2 * k, part.shape[1] + 2 * k), fill,
                    dtype=part.dtype)
    padded[k:k + part.shape[0], k:k + part.shape[1]] = part
    moves_b, stats_b = rough(surf, stock_box, tool_r, 20.0,
                            part_hf=(padded, hx0 - pad_mm, hy0 - pad_mm,
                                    hcell), **kw)
    bad_a = centres_outside(moves_a)
    assert not bad_a, "normal --hf: %d cutter centres outside stock +- tool_r" \
        " (first at %.2f, %.2f Z=%.3f)" % (len(bad_a), bad_a[0][0],
                                           bad_a[0][1], bad_a[0][2])
    bad_b = centres_outside(moves_b)
    assert not bad_b, "padded --hf: %d cutter centres outside stock +- tool_r" \
        " (first at %.2f, %.2f Z=%.3f)" % (len(bad_b), bad_b[0][0],
                                           bad_b[0][1], bad_b[0][2])
    la, lb = stats_a["cut_len"], stats_b["cut_len"]
    assert la > 0 and lb > 0
    rel = abs(la - lb) / max(la, lb)
    assert rel < 0.01, "cut length differs by %.2f%% between normal and " \
        "padded --hf (%.1f vs %.1f mm)" % (100.0 * rel, la, lb)
    print("PASS rough region clipped to stock: normal %d moves / %.1f mm, "
          "padded %d moves / %.1f mm, all centres within stock +- tool_r"
          % (len(moves_a), la, len(moves_b), lb))


def test_islands_grid_edge_parity():
    """R3 regression: when the forbidden region F reaches the CL grid border
    (grid does not cover the outer CL jump), level_islands must still EXCLUDE
    cutter centres next to the pocket walls - silently dropping the open
    circuit flipped even-odd parity and admitted them (synth_pocket failure:
    centre at (-6.4, 23.508), 0.39 mm from the wall, at Z=4.381)."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
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
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
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
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(step)
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
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
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
               test_rough_testblock_r4,
               test_rough_region_clipped_to_stock,
               test_islands_grid_edge_parity, test_rough_pocket_in_block,
               test_rough_synth_pocket_repro, test_rough_rapids_clear_stock,
               test_rough_rt_entries, test_rapid_swept_clear_catches_diagonal_climb,
               test_se2_side_entries_only_through_cleared,
               test_hr1_rings_after_a2d,
               test_dt1_nn_order_ties_stable,
               test_dt1_synthetic_rough_twice_identical,
               test_hb1v2_flat_floor_circle_after_helix,
               test_bs1a_straight_channel,
               test_bs1a_lshaped_channel,
               test_bs1a3_no_band_after_a2d,
               test_stl_cache_keyed_by_content,
               test_rr1a_rough_cli_refuses_ball,
               test_bs1a4b_failed_region_lightest,
               test_bs1a4b_windows_align_zmap,
               test_bs1a4c_backed_credit,
               test_bs1a4c_fix_no_post_entry_helix,
               test_bs1a4c2_band_chord_cl_checked,
               test_bs1a4d_credit0_lightest_option,
               test_bs1a4d_credit_real_bore,
               test_bs1a4d2b_centred_entry_bore,
               test_bs1a4d4_credit_entry_matches_prediction,
               test_bs1a4d4_entry_pinned_to_stored_start,
               test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load):
        try:
            fn()
        except AssertionError as e:
            fails += 1
            print("FAIL %s: %s" % (fn.__name__, e))
    print("%d failure(s)" % fails)
    return 1 if fails else 0



def test_stl_cache_keyed_by_content():
    """Two different STEP files with the same name must never share a cached STL
    (connector runs all name their part model.step)."""
    import tempfile, shutil
    from engine import model
    here = os.path.dirname(os.path.abspath(__file__))
    a = os.path.join(here, "testdata_synth_pocket.step")
    b = os.path.join(os.path.dirname(here), "samples", "test_block.step")
    _need(a, b)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out")
        for src, sub in ((a, "r1"), (b, "r2")):
            os.makedirs(os.path.join(td, sub))
            shutil.copy(src, os.path.join(td, sub, "model.step"))
        s1 = model.step_to_stl(os.path.join(td, "r1", "model.step"), out_dir=out)
        s2 = model.step_to_stl(os.path.join(td, "r2", "model.step"), out_dir=out)
        assert s1 != s2, "same-name different-content STEPs shared a cached STL"
        assert model.step_to_stl(os.path.join(td, "r1", "model.step"), out_dir=out) == s1
    print("PASS stl cache keyed by content")


def test_rough_rt_entries():
    """Task RT: no axial plunges, short feed descents (G0 does the air),
    per-level region/clip-break stats, and zmap's report-only axial_plunges
    stays 0 on the same program."""
    step = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "connector", "testdata",
        "synth_pocket.step")
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(step)
    import subprocess
    import tempfile
    import numpy as np
    from opencamlib import ocl
    from engine import model
    from engine.gcode import moves_to_gcode
    from engine.rough import rough, build_part_hf
    from engine.stock import StockField
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    stl = model.step_to_stl(step)
    surf = ocl.STLSurf()
    ocl.STLReader(stl, surf)
    stock_box = (-31.0, 31.0, -31.0, 31.0, -1.0, 12.4)
    tool_r = 3.0
    with tempfile.TemporaryDirectory() as td:
        moves, stats = rough(surf, stock_box, tool_r, 3.0, leave=0.381,
                            axial_leave=0.381, stepdown=4.0, stepup=1.905,
                            stepover=2.0 / 6.0, tolerance=0.05, threads=4,
                            stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                            stl_path=stl)
        # engine enforcement + per-level stats (RT item 4)
        assert stats["n_axial_plunge"] == 0, "engine counted axial plunges"
        assert stats["levels"], "no levels planned"
        for lvl in stats["levels"]:
            assert "n_regions" in lvl and "n_clip_breaks" in lvl, \
                "level stats missing regions/clip breaks: %s" % lvl
        # replay: every straight vertical G1 descent is short (air travels
        # at G0) and removes NO stock under the flat bottom disk
        sf = StockField(stock_box, cell=0.5)
        hf = build_part_hf(surf, sf.x0, sf.y0, sf.cell, sf.nx, sf.ny,
                           threads=4, drop_z=-1.0)
        sf.set_part_from_other_grid(hf, sf.x0, sf.y0, sf.cell, fill=-1e9)
        r_ax = tool_r - 0.5          # flat disk minus one quantisation cell
        k_ax = int(math.ceil(r_ax / 0.5))
        offs = [(dj, di) for dj in range(-k_ax, k_ax + 1)
                for di in range(-k_ax, k_ax + 1) if dj * dj + di * di <= 36]
        prev = None
        n_plane, n_axial = 0, 0
        max_dz = 0.0
        clearance = stock_box[5] + 2.0
        for mv in moves:
            cur = (mv["x"], mv["y"], mv["z"])
            if prev is not None:
                if mv["g"] == 1 and abs(cur[0] - prev[0]) < 1e-9 \
                        and abs(cur[1] - prev[1]) < 1e-9 and cur[2] < prev[2]:
                    dz = prev[2] - cur[2]
                    max_dz = max(max_dz, dz)
                    # RT item 1: air travels at G0 - no feed descent may
                    # start at the clearance plane any more
                    if prev[2] >= clearance - 0.05:
                        n_plane += 1
                    i0 = int(math.floor((cur[0] - sf.x0) / 0.5))
                    j0 = int(math.floor((cur[1] - sf.y0) / 0.5))
                    mx = -np.inf
                    for dj, di in offs:
                        a, b = i0 + di, j0 + dj
                        if 0 <= a < sf.nx and 0 <= b < sf.ny:
                            d = math.hypot(sf.x0 + (a + 0.5) * 0.5 - cur[0],
                                         sf.y0 + (b + 0.5) * 0.5 - cur[1])
                            if d <= r_ax:
                                mx = max(mx, float(sf.top[b, a]))
                    if mx > cur[2] + 0.05:
                        n_axial += 1
                    sf.mill_segment(prev[0], prev[1], cur[0], cur[1], cur[2],
                                   tool_r)
                elif mv["g"] == 1:
                    sf.mill_segment(prev[0], prev[1], cur[0], cur[1],
                                   min(prev[2], cur[2]), tool_r)
            prev = cur
        assert n_axial == 0, "%d straight feed-downs cut stock axially" % n_axial
        assert n_plane == 0, "%d vertical feed descents start at the " \
            "clearance plane (max descent %.2f mm)" % (n_plane, max_dz)
        # zmap (the judge): report-only axial_plunges present and 0
        ngc = os.path.join(td, "rt.ngc")
        with open(ngc, "w") as fh:
            fh.write(moves_to_gcode(moves, spindle_rpm=7500))
        hf_p = os.path.join(td, "part_hf.npy")
        # judge grid = stock + tool_r + 5 mm of empty floor (the connector's
        # prepare convention): footprints of legitimate centres at the stock
        # edge must stay inside the measured grid, or outside_grid fires for
        # moves that are fully inside the working envelope.
        pad = tool_r + 5.0
        kpad = int(math.ceil(pad / 0.5))
        raw = np.where(np.isfinite(hf), hf, np.nan)
        padded = np.full((raw.shape[0] + 2 * kpad, raw.shape[1] + 2 * kpad),
                        np.nan, dtype=raw.dtype)
        padded[kpad:kpad + raw.shape[0], kpad:kpad + raw.shape[1]] = raw
        np.save(hf_p, padded)
        import json as _json
        with open(hf_p[:-4] + ".json", "w") as fh:
            _json.dump({"x0": sf.x0 - kpad * 0.5, "y0": sf.y0 - kpad * 0.5,
                       "cell": 0.5, "tess_tol": 0.01}, fh)
        rj = os.path.join(td, "zmap.json")
        rr = subprocess.run(
            [sys.executable, os.path.join(repo, "verify", "zmap.py"), ngc,
             "--part", hf_p, "--tool", "flat", "--dia", "6.0",
             "--stock", *[str(v) for v in stock_box],
             "--out-json", rj], capture_output=True, text=True, cwd=repo)
        assert rr.returncode == 0, "zmap failed: %s | %s" % (rr.stdout[-600:], rr.stderr[-600:])
        rep = _json.load(open(rj))
        assert rep["gouges"]["count"] == 0
        assert rep["rapid_collisions"]["count"] == 0
        assert rep["outside_grid"]["count"] == 0, \
            "zmap outside_grid: %s" % rep["outside_grid"]["first_line"]
        assert rep["axial_plunges"]["count"] == 0, \
            "zmap axial_plunges: %s" % rep["axial_plunges"]["flags"][:3]
    print("PASS rough rt entries: axial 0 (engine + zmap), all vertical "
          "feed descents short, per-level region/clip stats present")


def test_rapid_swept_clear_catches_diagonal_climb():
    """Must-fail: a diagonal G0 climbing out of a slot through the stock wall
    clears at its END height but not along its length; the swept check rejects
    it, and rise-then-traverse (vertical up, then across at height) passes."""
    from engine.rough import rapid_swept_clear
    sf = StockField(SB, cell=0.5)                 # stock top 10
    sf.mill_path([(-15.0, 10.0), (-5.0, 10.0)], 4.0, SR)   # slot floor at 4
    p0 = (-10.0, 10.0, 4.0)                       # tool in the slot
    p1 = (-10.0, 18.0, 11.5)                      # above the wall, 8 mm over
    assert not rapid_swept_clear(sf, p0, p1, SR + 1.0, 1.0), \
        "diagonal climb through the slot wall must fail the swept check"
    rise = (p0[0], p0[1], p1[2])
    assert rapid_swept_clear(sf, rise, p1, SR + 1.0, 1.0), \
        "the traverse at height after a vertical rise must pass"
    print("PASS rapid swept check catches a diagonal climb")


def _two_floor_pocket_stl(path, half=16.0, ztop=12.0, pk=13.0, dx=-3.0,
                          z_deep=6.0, z_shelf=8.0):
    """ASCII STL: block +-half, 0..ztop with pocket +-pk whose floor steps
    from z_deep (x < dx) up to a shelf at z_shelf (vertical step wall at
    x = dx). The shelf level's region can only be approached sideways from
    the deep floor THROUGH the standing step wall."""
    h, t, w = half, ztop, pk

    def quad(a, b, c, d):
        return [(a, b, c), (a, c, d)]

    tris = []
    tris += quad((-h, -h, 0), (-h, h, 0), (h, h, 0), (h, -h, 0))
    tris += quad((h, -h, 0), (h, h, 0), (h, h, t), (h, -h, t))
    tris += quad((-h, -h, 0), (-h, -h, t), (-h, h, t), (-h, h, 0))
    tris += quad((-h, h, 0), (-h, h, t), (h, h, t), (h, h, 0))
    tris += quad((-h, -h, 0), (-h, -h, t), (h, -h, t), (h, -h, 0))
    tris += quad((-h, -h, t), (h, -h, t), (w, -w, t), (-w, -w, t))
    tris += quad((h, -h, t), (h, h, t), (w, w, t), (w, -w, t))
    tris += quad((h, h, t), (-h, h, t), (-w, w, t), (w, w, t))
    tris += quad((-h, h, t), (-h, -h, t), (-w, -w, t), (-w, w, t))
    tris += quad((dx, -w, z_shelf), (w, -w, z_shelf), (w, w, z_shelf),
                 (dx, w, z_shelf))                                        # shelf
    tris += quad((-w, -w, z_deep), (dx, -w, z_deep), (dx, w, z_deep),
                 (-w, w, z_deep))                                       # deep
    tris += quad((dx, -w, z_deep), (dx, w, z_deep), (dx, w, z_shelf),
                 (dx, -w, z_shelf))                                      # step
    tris += quad((-w, -w, z_deep), (-w, w, z_deep), (-w, w, t),
                 (-w, -w, t))
    tris += quad((w, -w, z_shelf), (w, w, z_shelf), (w, w, t),
                 (w, -w, t))
    tris += quad((-w, w, z_deep), (dx, w, z_deep), (dx, w, t), (-w, w, t))
    tris += quad((-w, -w, z_deep), (-w, -w, t), (dx, -w, t),
                 (dx, -w, z_deep))
    tris += quad((dx, w, z_shelf), (w, w, z_shelf), (w, w, t), (dx, w, t))
    tris += quad((dx, -w, z_shelf), (dx, -w, t), (w, -w, t),
                 (w, -w, z_shelf))
    with open(path, "w") as fh:
        fh.write("solid two_floor_pocket\n")
        for a, b, c in tris:
            fh.write(" facet normal 0 0 0\n  outer loop\n")
            for p in (a, b, c):
                fh.write("   vertex %.4f %.4f %.4f\n" % p)
            fh.write("  endloop\n endfacet\n")
        fh.write("endsolid two_floor_pocket\n")
    return path


def test_se2_side_entries_only_through_cleared():
    """SE2: a side entry is used ONLY if the whole sideways feed-in (column
    -> region start, swept by tool_r) runs through material already cleared
    at that level (live stock top <= Z + AXIAL_FLOOR); otherwise helix."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import tempfile
    import json as _json
    import numpy as np
    from opencamlib import ocl
    from engine.rough import rough, AXIAL_FLOOR
    assert AXIAL_FLOOR == 0.2, "engine AXIAL_FLOOR must equal verify's (0.2)"
    # (a) standing wall: the shelf level's only side approach crosses the
    # step wall still standing above Z -> helix entries, no side entry.
    with tempfile.TemporaryDirectory() as td:
        stl = _two_floor_pocket_stl(os.path.join(td, "tf.stl"))
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        moves, stats = rough(surf, (-16.2, 16.2, -16.2, 16.2, -1.0, 12.4),
                            3.0, 6.0, leave=0.381, axial_leave=0.381,
                            stepdown=19.05, stepup=1.905, stepover=2.0 / 6.0,
                            tolerance=0.05, threads=4, stock_cell=0.5,
                            min_rest=0.5, corner_r=0.0)
        assert stats["n_axial_plunge"] == 0
        assert stats["n_side_entries"] == 0, \
            "side entry fed in across the standing step wall: %d" % \
            stats["n_side_entries"]
        assert stats["entry_feed_mm"] > 0.0, "entries did not descend by feed"
    # (b) cleared approach: on the test block the level regions are entered
    # across floors already milled at/below Z -> side entries must be used.
    _need(TB_STL, TB_HF)
    surf = ocl.STLSurf()
    ocl.STLReader(TB_STL, surf)
    hf = np.load(TB_HF)
    meta = _json.load(open(TB_HF[:-4] + ".json"))
    moves, stats = rough(surf, (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0),
                         6.343, 20.0, leave=0.381, axial_leave=0.381,
                         stepdown=19.05, final_zmin=20.381, stepover=0.16,
                         tolerance=0.05, threads=4, stock_cell=0.5,
                         min_rest=1.0, corner_r=0.0, stl_path=TB_STL,
                         part_hf=(hf, float(meta["x0"]), float(meta["y0"]),
                                 float(meta["cell"])))
    assert stats["n_axial_plunge"] == 0
    assert stats["n_side_entries"] > 0, \
        "regions with cleared side approaches did not side-enter"
    print("PASS SE2 side entries: standing-wall part 0 side (helix), test "
          "block %d side through cleared feed-ins" % stats["n_side_entries"])


def test_hr1_rings_after_a2d():
    """Task HR1: per level, ALL hug-ring regions must be emitted AFTER that
    level's Adaptive2d regions. Synthetic part: slab 40x32 (top Z6) with a
    cross-wall (x -1..1, top Z12) splitting the territory into a left and a
    right pocket, plus a boss (x -14..-8, y -4..4, top Z12) inside the left
    pocket. On main's code the NN travel order slots the boss's hug ring(s)
    between the two a2d regions, so the ring cuts full width at the full
    stepdown instead of skimming. Assert on the EMITTED moves: assign every
    horizontal cutting move at a level Z to the region whose cutting path
    contains it (a2d vs hug ring, captured by wrapping _run_a2d/hug_regions),
    and require every ring move at Z to follow the last a2d move at that Z."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import tempfile
    from opencamlib import ocl
    import engine.rough as R
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "hr1_synth.stl")
        # slab 40x32 top Z6; central wall (top Z12) whose grown forbidden
        # band reaches within 0.6 mm of the stock edge in Y - too narrow for
        # any tool centre -> the machining territory splits into a left and a
        # right lobe (two a2d regions per level); two fins fused to the wall
        # (top Z12) give the wall ring extra runs to interleave with a2d.
        _write_stl(stl, _box_tris(-20.0, 20.0, -16.0, 16.0, 0.0, 6.0)
                   + _box_tris(-1.0, 1.0, -16.0, 16.0, 6.0, 12.0)
                   + _box_tris(-8.0, -1.0, -4.0, 4.0, 6.0, 12.0)
                   + _box_tris(1.0, 8.0, -4.0, 4.0, 6.0, 12.0))
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        cap = []
        orig_a2d, orig_hug = R._run_a2d, R.hug_regions

        def w_a2d(*a, **k):
            res = orig_a2d(*a, **k)
            cap.append([("a2d", r) for r in res])
            return res

        def w_hug(*a, **k):
            res = orig_hug(*a, **k)
            cap[-1].extend(("ring", r) for r in res)
            return res
        R._run_a2d, R.hug_regions = w_a2d, w_hug
        try:
            moves, stats = R.rough(surf, (-24.0, 24.0, -20.0, 20.0, 6.0, 16.0),
                                  3.0, 6.0, leave=0.381, axial_leave=0.381,
                                  stepdown=4.0, stepup=10.0, stepover=2.0 / 6.0,
                                  tolerance=0.05, threads=4, stock_cell=0.5,
                                  min_rest=0.5, corner_r=0.0, stl_path=stl)
        finally:
            R._run_a2d, R.hug_regions = orig_a2d, orig_hug
        zs = [lv["z"] for lv in stats["levels"] if not lv.get("skipped")]
        segs = [s for s in cap if s]
        assert len(segs) == len(zs), \
            "captured region segments %d != emitted levels %d" % (len(segs), len(zs))
        n_both = 0
        for z, seg in zip(zs, segs):
            kind_of = {}
            dup = set()
            for kind, res in seg:
                for (kk, pp) in res["paths"]:
                    if kk != "cutting":
                        continue
                    for (x, y) in pp:
                        p = (round(x, 4), round(y, 4))
                        if p in kind_of and kind_of[p] != kind:
                            dup.add(p)
                        kind_of.setdefault(p, kind)
            seq = []
            for mv in moves:
                if mv["g"] != 1 or mv["z"] is None or abs(mv["z"] - z) > 1e-3:
                    continue
                k2 = kind_of.get((round(mv["x"], 4), round(mv["y"], 4)))
                if k2 is None or (round(mv["x"], 4), round(mv["y"], 4)) in dup:
                    continue
                if not seq or seq[-1] != k2:
                    seq.append(k2)
            if "ring" in seq and "a2d" in seq:
                n_both += 1
                assert "a2d" not in seq[seq.index("ring"):], \
                    "level Z=%.3f: hug-ring cutting moves do not follow all a2d " \
                    "cutting moves (emitted order %s)" % (z, seq[:16])
        assert n_both >= 1, \
            "no level had both a2d and hug-ring cutting moves: test vacuous"
    print("PASS hr1 rings after a2d: %d level(s) with ring+a2d moves, every "
          "ring follows all a2d at its Z" % n_both)


def test_dt1_nn_order_ties_stable():
    """Task DT1: a tie in the NN travel order must be broken by a stable
    key (region index, then coordinates), NEVER by candidate iteration
    order. Synthetic equal-distance regions: pa=(0,5) and pb=(0,-5) are
    exactly 5 mm from pos (0,0). Main's inline loop took the FIRST minimum
    in list order, so swapping two tied entry candidates changed the rapid
    target - reproduced here with a copy of main's loop (the test fails if
    ties resolve by iteration order). _nn_order must return the same order
    and end position regardless of candidate/phase list order."""
    import math as _m
    from engine.rough import _nn_order
    pa, pb, far = (0.0, 5.0), (0.0, -5.0), (50.0, 0.0)
    # entry-point tie inside one region: same set, opposite list order
    o1, e1 = _nn_order([0], [[pa, pb]], (0.0, 0.0))
    o2, e2 = _nn_order([0], [[pb, pa]], (0.0, 0.0))
    assert o1 == o2 == [0] and e1 == e2 == pb, \
        "entry tie not resolved by (dist,x,y): %s vs %s" % (e1, e2)
    # region tie: same result whatever order the phase enumerates in
    r1, _ = _nn_order([0, 1], [[pa], [pb]], (0.0, 0.0))
    r2, _ = _nn_order([1, 0], [[pa], [pb]], (0.0, 0.0))
    assert r1 == r2 == [0, 1], \
        "region tie not resolved by lowest index: %s vs %s" % (r1, r2)

    def _main_nn(phase, cand, pos):  # main's pre-DT1 loop, verbatim
        out = []
        remaining = list(phase)
        while remaining:
            k = remaining[0] if pos is None else min(remaining, key=lambda k:
                min(_m.dist(pos, p) for p in cand[k]))
            out.append(k)
            remaining.remove(k)
            pos = min(cand[k], key=lambda p: _m.dist(pos, p)) \
                if pos is not None else cand[k][0]
        return out, pos
    m1, me1 = _main_nn([0], [[pa, pb]], (0.0, 0.0))
    m2, me2 = _main_nn([0], [[pb, pa]], (0.0, 0.0))
    assert me1 != me2, \
        "test vacuous: main's loop did not exhibit the iteration-order tie"
    print("PASS dt1 nn tie stability: ties resolve by (dist, index/x/y); "
          "main's loop resolved the same tie by list order (%s vs %s)"
          % (me1, me2))


def test_dt1_synthetic_rough_twice_identical():
    """Task DT1: same code + same inputs -> identical emitted move lists.
    Small synthetic part (hr1 slab: 40x32 top Z6, central wall + two fins)
    roughed TWICE in-process on fresh state; the move lists must compare
    equal element for element (rapids included)."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import tempfile
    from opencamlib import ocl
    import engine.rough as R
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "dt1_synth.stl")
        _write_stl(stl, _box_tris(-20.0, 20.0, -16.0, 16.0, 0.0, 6.0)
                   + _box_tris(-1.0, 1.0, -16.0, 16.0, 6.0, 12.0)
                   + _box_tris(-8.0, -1.0, -4.0, 4.0, 6.0, 12.0)
                   + _box_tris(1.0, 8.0, -4.0, 4.0, 6.0, 12.0))
        outs = []
        for _run in range(2):
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            mv, _st = R.rough(surf, (-24.0, 24.0, -20.0, 20.0, 6.0, 16.0),
                              3.0, 6.0, leave=0.381, axial_leave=0.381,
                              stepdown=4.0, stepup=10.0, stepover=2.0 / 6.0,
                              tolerance=0.05, threads=4, stock_cell=0.5,
                              min_rest=0.5, corner_r=0.0, stl_path=stl)
            assert mv, "no moves"
            outs.append(repr(mv))
        assert outs[0] == outs[1], \
            "synthetic rough: two in-process runs emitted different moves"
    print("PASS dt1 twice-identical synthetic rough: 2 runs emitted "
          "identical move lists (%d chars of moves)" % len(outs[0]))


def test_hb1v2_flat_floor_circle_after_helix():
    """HB1v2: after EVERY helix entry the next emitted moves are ONE full flat
    circle at the helix bottom Z - same centre and radius as the helix, at the
    ramp feed - before any cutting-feed move. On main's code the move right
    after the helix is the return feed at the cutting feed, so this fails."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import tempfile
    import numpy as np
    from opencamlib import ocl
    from engine.rough import rough
    CUT, RAMP = 3429.0, 1270.0
    with tempfile.TemporaryDirectory() as td:
        stl = _two_floor_pocket_stl(os.path.join(td, "hb1v2.stl"))
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        moves, stats = rough(surf, (-16.2, 16.2, -16.2, 16.2, -1.0, 12.4),
                            3.0, 6.0, leave=0.381, axial_leave=0.381,
                            stepdown=19.05, stepup=1.905, stepover=2.0 / 6.0,
                            tolerance=0.05, threads=4, stock_cell=0.5,
                            min_rest=0.5, corner_r=0.0)

    def fit(pts):
        A = np.array([[p[0], p[1], 1.0] for p in pts])
        b = np.array([-(p[0] ** 2 + p[1] ** 2) for p in pts])
        s, *_ = np.linalg.lstsq(A, b, rcond=None)
        cx, cy = -s[0] / 2.0, -s[1] / 2.0
        return cx, cy, math.sqrt(s[2] + cx * cx + cy * cy)

    n_helix = 0
    i = 0
    while i + 1 < len(moves):
        a, b = moves[i], moves[i + 1]
        if (a["g"] == 1 and b["g"] == 1 and a.get("f") == RAMP
                and b.get("f") == RAMP and a["z"] is not None
                and b["z"] is not None and b["z"] < a["z"] - 1e-9):
            j = i + 1
            while (j + 1 < len(moves) and moves[j + 1]["g"] == 1
                   and moves[j + 1].get("f") == RAMP
                   and moves[j + 1]["z"] is not None
                   and moves[j]["z"] is not None
                   and moves[j + 1]["z"] < moves[j]["z"] - 1e-9):
                j += 1
            helix = [m for m in moves[i:j + 1]]
            i = j + 1
            hx, hy, hr = fit([(m["x"], m["y"]) for m in helix])
            if hr < 0.2:  # degenerate micro-bore: no floor circle required
                continue
            n_helix += 1
            zb = helix[-1]["z"]
            circ = []
            for m in moves[i:]:
                if (m["g"] == 1 and m.get("f") == RAMP
                        and m["z"] is not None and abs(m["z"] - zb) < 1e-6):
                    circ.append(m)
                else:
                    break
            assert circ, \
                "helix at (%.2f,%.2f) Z %.3f: no ramp-feed floor circle after " \
                "the helix bottom (next move f=%r)" % (hx, hy, zb,
                                                      moves[i].get("f"))
            cx, cy, cr = fit([(m["x"], m["y"]) for m in circ])
            assert abs(cx - hx) < 0.05 and abs(cy - hy) < 0.05 \
                and abs(cr - hr) < 0.05, \
                "floor circle centre/radius (%.3f,%.3f,r=%.3f) != helix " \
                "(%.3f,%.3f,r=%.3f)" % (cx, cy, cr, hx, hy, hr)
            pts = [(m["x"], m["y"]) for m in helix[-1:]] + \
                  [(m["x"], m["y"]) for m in circ]
            sweep = 0.0
            for (p, q) in zip(pts, pts[1:]):
                da = math.atan2(q[1] - cy, q[0] - cx) \
                    - math.atan2(p[1] - cy, p[0] - cx)
                sweep += (da - 2 * math.pi) if da > math.pi else \
                    ((da + 2 * math.pi) if da < -math.pi else da)
            assert sweep >= 2 * math.pi - 1.0 and len(circ) >= 8, \
                "floor circle at Z %.3f is not one full turn (%.2f rad, %d " \
                "moves)" % (zb, sweep, len(circ))
            nxt = moves[i + len(circ)]
            assert nxt["g"] == 1 and nxt.get("f") == CUT, \
                "floor circle must be followed by the cutting-feed return"
        else:
            i += 1
    assert n_helix >= 1, "no helix entry emitted on the synthetic part: vacuous"
    print("PASS hb1v2 floor circle: %d helix entry/entries each followed by "
          "one full flat circle at the helix bottom Z, ramp feed" % n_helix)


def _bs1a_channel_case(name, tris, in_channel):
    """BS1a shared driver: rough a synthetic 19 mm-wide, 18 mm-deep channel
    with walls on both sides (stock top Z18, floor Z0, flat 12.686), judge
    with verify/zmap.py --ae2-dump and require ZERO full-width windows at
    CUTTING feed inside the channel plus 0 gouges / rapid collisions / axial
    plunges / outside_grid (CL-legality of every new point is additionally
    enforced inside rough(): allowance, hf backstop, CLCHECK)."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import subprocess
    import tempfile
    import json as _json
    import numpy as np
    from opencamlib import ocl
    from engine.gcode import moves_to_gcode
    from engine.rough import rough, build_part_hf
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    stock_box = (-40.0, 40.0, -30.0, 30.0, -1.0, 18.0)
    tool_r = 6.343
    dia = 2.0 * tool_r
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, name + ".stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        moves, stats = rough(surf, stock_box, tool_r, 0.0, leave=0.381,
                            axial_leave=0.381, stepdown=19.05, stepup=1.905,
                            tolerance=0.05, threads=4, stock_cell=0.5,
                            min_rest=0.5, corner_r=0.0, stl_path=stl)
        assert stats.get("n_band_regions", 0) >= 1, \
            "no trochoidal channel-clear region was planned: the residue " \
            "channel was not recognised (main's code has no band step)"
        ngc = os.path.join(td, name + ".ngc")
        with open(ngc, "w") as fh:
            fh.write(moves_to_gcode(moves, spindle_rpm=7500))
        hf = build_part_hf(surf, -40.0, -30.0, 0.5, 160, 120, threads=4,
                           drop_z=-1.0)
        hf_p = os.path.join(td, "part_hf.npy")
        pad = int(math.ceil((tool_r + 5.0) / 0.5))
        padded = np.full((hf.shape[0] + 2 * pad, hf.shape[1] + 2 * pad),
                        np.nan, dtype=hf.dtype)
        padded[pad:pad + hf.shape[0], pad:pad + hf.shape[1]] = hf
        np.save(hf_p, padded)
        with open(hf_p[:-4] + ".json", "w") as fh:
            _json.dump({"x0": -40.0 - pad * 0.5, "y0": -30.0 - pad * 0.5,
                       "cell": 0.5, "tess_tol": 0.01}, fh)
        rj = os.path.join(td, "zmap.json")
        dj = os.path.join(td, "ae2.json")
        rr = subprocess.run(
            [sys.executable, os.path.join(repo, "verify", "zmap.py"), ngc,
             "--part", hf_p, "--tool", "flat", "--dia", "%.3f" % dia,
             "--stock", *[str(v) for v in stock_box],
             "--engage-max", "2.438", "--ae2-dump", dj, "--out-json", rj],
            capture_output=True, text=True, cwd=repo)
        assert rr.returncode == 0, "zmap failed: %s | %s" % (
            rr.stdout[-800:], rr.stderr[-600:])
        rep = _json.load(open(rj))
        assert rep["gouges"]["count"] == 0, "zmap gouges: %s" % rep["gouges"]
        assert rep["rapid_collisions"]["count"] == 0
        assert rep["axial_plunges"]["count"] == 0, \
            "zmap axial_plunges: %s" % rep["axial_plunges"]["flags"][:3]
        assert rep["outside_grid"]["count"] == 0
        cut_feed = rep["engagement"]["ae2_cutting_feed"]
        wins = _json.load(open(dj))
        fw = [w for w in wins
              if w["ae_eff"] >= 0.9 * dia and w["a"] > 0.5
              and w.get("feed") is not None
              and abs(w["feed"] - cut_feed) < 1e-6
              and in_channel(w["x"], w["y"])]
        assert not fw, "%d full-width window(s) at cutting feed in the " \
            "channel: %s" % (len(fw), [(w["line"], w["x"], w["y"], w["z"],
                                       round(w["ae_eff"], 2), round(w["a"], 2))
                                      for w in fw[:6]])
    return stats


def test_bs1a_straight_channel():
    """Task BS1a: a closed 19 mm-wide, 18 mm-deep channel (annular slot:
    central island + outer wall ring, 19 mm gap on every side) leaves the
    hug rings no thin option - on main's code the ring slots the whole channel
    cross-section at the full stepdown (full-width windows at cutting feed,
    a ~ 17.6 mm). The band step must clear it trochoidally first: ZE2 shows 0
    full-width windows at cutting feed in the channel. FAILS on main."""
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)      # floor
            + _box_tris(-40.0, -30.0, -30.0, 30.0, 0.0, 18.0)    # outer ring
            + _box_tris(30.0, 40.0, -30.0, 30.0, 0.0, 18.0)
            + _box_tris(-30.0, 30.0, -30.0, -25.0, 0.0, 18.0)
            + _box_tris(-30.0, 30.0, 25.0, 30.0, 0.0, 18.0)
            + _box_tris(-11.0, 11.0, -6.0, 6.0, 0.0, 18.0))       # island

    def in_channel(x, y):
        return (-32.0 < x < 32.0 and -27.0 < y < 27.0
                and not (-13.0 < x < 13.0 and -8.0 < y < 8.0))
    stats = _bs1a_channel_case("bs1a_straight", tris, in_channel)
    print("PASS bs1a straight channel: %d band region(s), %.1f mm trochoidal "
          "cut, 0 full-width windows at cutting feed in the channel"
          % (stats["n_band_regions"], stats["band_cut_len_mm"]))


def test_bs1a_lshaped_channel():
    """Task BS1a: same bar on an L-SHAPED 19 mm-wide, 18 mm-deep channel
    (blind ends): straight run along X, 90 deg corner, straight run along Y,
    walls live on both sides. FAILS on main (ring slots the channel)."""
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)       # floor
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)     # left wall
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)      # bottom wall
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)         # inner corner
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)         # right wall
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)        # upper-left
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0))        # top cap

    def in_channel(x, y):
        return ((-30.0 < x < 4.0 and -11.5 < y < 11.5)
                or (-11.5 < x < 11.5 and -4.0 < y < 30.0))
    stats = _bs1a_channel_case("bs1a_lshape", tris, in_channel)
    print("PASS bs1a L-shaped channel: %d band region(s), %.1f mm trochoidal "
          "cut, 0 full-width windows at cutting feed in the channel"
          % (stats["n_band_regions"], stats["band_cut_len_mm"]))


def test_bs1a3_no_band_after_a2d():
    """Task BS1a3: an open 40 x 30 mm, 18 mm-deep pocket that Adaptive2d
    clears completely (the hug rings only skim the leave margin): judged on
    the LIVE stock AFTER this level's a2d passes, no ring window reaches full
    width (ae_eff >= 0.9 x D), so BS1a3 must emit ZERO band regions here.
    FAILS on c074148, which ran the channel check on the stock as it stood at
    the START of the level - pre-a2d, every ring looked like a full-width
    channel and got trochoided."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import tempfile
    from opencamlib import ocl
    import engine.rough as R
    from engine.rough import rough
    orig_hug = R.hug_regions
    seen = []

    def _spy(*a, **k):
        res = orig_hug(*a, **k)
        seen.append(sum(1 for r in res for kp in r["paths"]
                        if kp[0] == "cutting"))
        return res
    R.hug_regions = _spy
    stock_box = (-40.0, 40.0, -30.0, 30.0, -1.0, 18.0)
    tris = (_box_tris(-20.0, 20.0, -15.0, 15.0, -1.0, 0.0)     # pocket floor
            + _box_tris(-40.0, -20.0, -30.0, 30.0, 0.0, 18.0)   # surrounding
            + _box_tris(20.0, 40.0, -30.0, 30.0, 0.0, 18.0)
            + _box_tris(-20.0, 20.0, -30.0, -15.0, 0.0, 18.0)
            + _box_tris(-20.0, 20.0, 15.0, 30.0, 0.0, 18.0))
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "bs1a3_pocket.stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        try:
            moves, stats = rough(surf, stock_box, 6.343, 0.0, leave=0.381,
                                axial_leave=0.381, stepdown=19.05,
                                stepup=1.905, tolerance=0.05, threads=4,
                                stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                                stl_path=stl)
        finally:
            R.hug_regions = orig_hug
        assert sum(seen) > 0, "no hug-ring paths were planned: the level " \
            "residue the check judges is missing (vacuous test)"
        assert sum(l.get("n_regions", 0) for l in stats["levels"]) > 0, \
            "no regions at all: the pocket was never machined"
        assert stats.get("n_band_regions", 0) == 0, \
            "%d band region(s) in a pocket a2d clears - the channel check is " \
            "still judging pre-a2d / non-full-width stock (blocked: %s)" \
            % (stats["n_band_regions"], stats.get("band_blocked", [])[:4])
    print("PASS bs1a3 no-band-after-a2d: pocket fully cleared by a2d, "
          "0 band regions emitted")


def test_rr1a_rough_cli_refuses_ball():
    """RR1a: `rough --tool ball:...` fails CLOSED - nonzero exit, clear
    refusal on stderr, NO program written, before any work (the step file
    is never even loaded). flat still roughs end to end."""
    import subprocess
    import tempfile
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    step = os.path.join(repo, "connector", "testdata", "synth_pocket.step")
    _need(step)
    stock = ["-31", "31", "-31", "31", "-1", "12.4"]
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "rough.ngc")
        r = subprocess.run(
            [sys.executable, "-m", "engine.cli", "rough", "--step",
             os.path.join(td, "never-parsed.step"), "--stock", *stock,
             "--tool", "ball:9.525", "--out", out],
            capture_output=True, text=True, cwd=repo)
        assert r.returncode != 0, "ball rough exited 0: %s" % r.stdout[-400:]
        assert "refused" in r.stderr and "ball" in r.stderr, \
            "no clear ball refusal on stderr: %r" % r.stderr[-400:]
        assert not os.path.exists(out), "ball rough wrote a program"
        # bull without a corner would silently run flat too - refused
        r = subprocess.run(
            [sys.executable, "-m", "engine.cli", "rough", "--step",
             os.path.join(td, "never-parsed.step"), "--stock", *stock,
             "--tool", "bull:12.7", "--out", out],
            capture_output=True, text=True, cwd=repo)
        assert r.returncode != 0 and "corner" in r.stderr, \
            "bull without corner not refused: %r" % r.stderr[-400:]
        assert not os.path.exists(out), "refused rough wrote a program"
        # flat still works (same tiny pocket as test_rough_rt_entries)
        r = subprocess.run(
            [sys.executable, "-m", "engine.cli", "rough", "--step", step,
             "--stock", *stock, "--tool", "flat:6.0", "--out", out,
             "--floor", "3.0", "--stepdown", "4.0", "--workers", "2"],
            capture_output=True, text=True, cwd=repo)
        assert r.returncode == 0, "flat rough failed: %s | %s" % (
            r.stdout[-500:], r.stderr[-500:])
        text = open(out).read()
        assert "G1" in text and len(text) > 1000, "flat program not written"
    print("PASS rr1a rough cli: ball and corner-less bull refused (no "
          "program), flat still roughs (%d bytes)" % len(text))


def test_bs1a4b_failed_region_lightest():
    """Task BS1a4b: on samples/test_block (James's cutting data) exactly one
    band region fails its gate at every shrink level. It must take the
    LIGHTEST measured option among {each shrink level, dropping it to the
    ring} - fewest full-width windows at cutting feed, then lowest max ae,
    then shortest travel over 2.44 mm - and the decision is NEVER silent:
    the region is listed in stats["failed_region_emitted"] with place, Z,
    area, option and engine max ae. On this part the trochoid (zmap 8.47)
    is lighter than the full-width ring slot (zmap 12.6) that would inherit
    its stock, so the trochoid is kept and FW at cutting feed on the padded
    0.1 judge grid stays at main's level (0). FAILS on e5e783e: there the
    stat does not exist (ungated emit happens silently)."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(TB_STL, TB_HF_01)
    import subprocess
    import tempfile
    import json as _json
    from opencamlib import ocl
    from engine.gcode import moves_to_gcode
    from engine.rough import rough
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    stock_box = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
    tool_r = 6.343
    dia = 2.0 * tool_r
    surf = ocl.STLSurf()
    ocl.STLReader(TB_STL, surf)
    moves, stats = rough(surf, stock_box, tool_r, 20.0, leave=0.381,
                         axial_leave=0.381, stepdown=19.05, stepover=0.16,
                         stl_path=TB_STL, workers=None, threads=4,
                         stock_cell=0.5, final_zmin=20.381)
    fre = stats.get("failed_region_emitted")
    assert fre is not None, \
        "stats has no failed_region_emitted: a gate-failing region was " \
        "emitted silently (main's fall-through)"
    assert len(fre) >= 1, \
        "expected the ungated test-block region in failed_region_emitted, " \
        "got %r" % (fre,)
    for e in fre:
        assert set(("x", "y", "z", "area", "option", "max_ae")) <= set(e), \
            "failed_region_emitted entry lacks fields: %r" % (e,)
        assert e["option"] != "drop_ring", \
            "the ungated region must keep its trochoid (zmap 8.47) instead " \
            "of handing its stock to the full-width ring slot (zmap 12.6):" \
            " %r" % (e,)
    with tempfile.TemporaryDirectory() as td:
        ngc = os.path.join(td, "tb.ngc")
        with open(ngc, "w") as fh:
            fh.write(moves_to_gcode(moves, spindle_rpm=7500))
        rj = os.path.join(td, "zmap.json")
        dj = os.path.join(td, "ae2.json")
        rr = subprocess.run(
            [sys.executable, os.path.join(repo, "verify", "zmap.py"), ngc,
             "--part", TB_HF_01, "--tool", "flat", "--dia", "%.3f" % dia,
             "--stock", *[str(v) for v in stock_box],
             "--engage-max", "2.438", "--ae2-dump", dj, "--out-json", rj],
            capture_output=True, text=True, cwd=repo)
        assert rr.returncode == 0, "zmap failed: %s | %s" % (
            rr.stdout[-800:], rr.stderr[-600:])
        rep = _json.load(open(rj))
        wins = _json.load(open(dj))
        cut_feed = rep["engagement"]["ae2_cutting_feed"]
        fw = [w for w in wins
              if w["ae_eff"] >= 0.9 * dia and w["a"] > 0.5
              and w.get("feed") is not None
              and abs(w["feed"] - cut_feed) < 1e-6]
        assert not fw, "FW at cutting feed rose to %d (main: 0): %s" % (
            len(fw), [(w["x"], w["y"], round(w["ae_eff"], 2))
                     for w in fw[:6]])
    print("PASS bs1a4b failed region: %d ungated region(s) recorded %s, "
          "0 full-width windows at cutting feed" % (
              len(fre), [(e["x"], e["y"], e["z"], e["area"], e["option"],
                         e["max_ae"]) for e in fre]))


def test_bs1a4b_windows_align_zmap():
    """Task BS1a4b alignment proof: replay the SAME emitted band moves on
    samples/test_block through engine band._simulate and through zmap's AE2
    engagement measure (--ae2-dump, on the 0.5 mm grid - the same cell the
    engine stock model uses, so quantisation cannot fake a difference): the
    window boundaries (closing move index within the region) must be identical
    and the max per-window ae difference is reported BOTH ways. FAILS on
    e5e783e: its first window is zero-length (the whole first-move disk), so
    every engine boundary closes one move late."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(TB_STL, TB_HF)
    import subprocess
    import tempfile
    import json as _json
    from opencamlib import ocl
    import engine.band as B
    from engine.gcode import moves_to_gcode
    from engine.rough import rough
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    replay = []
    _orig_sim = B._simulate
    _orig_cr = B.channel_regions

    def cr_spy(rings, stock, isl_ok3, z, tool_r, leave, cell, stats=None):
        res = _orig_cr(rings, stock, isl_ok3, z, tool_r, leave, cell, stats)
        for r in res:                # replay the EMITTED moves, live stock
            pts = [tuple(q) for q in r["paths"][0][1]]
            e = []
            w = _orig_sim(pts, stock, z, tool_r, cell, r.get("credit") or 0.0,
                          e)
            idxs = []
            k = 0
            tot = 0.0
            prev = (pts[0][0], pts[0][1])
            for j, p in enumerate(pts[1:], start=1):
                tot += math.dist(prev, (p[0], p[1]))
                prev = (p[0], p[1])
                if k < len(e) and tot >= e[k] - 1e-9:
                    idxs.append(j)
                    k += 1
            replay.append({"z": round(z, 3), "start": tuple(r["start"]),
                          "pts": pts, "wins": w, "ends": e, "idxs": idxs})
        return res

    B.channel_regions = cr_spy
    try:
        stock_box = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
        tool_r = 6.343
        dia = 2.0 * tool_r
        surf = ocl.STLSurf()
        ocl.STLReader(TB_STL, surf)
        moves, stats = rough(surf, stock_box, tool_r, 20.0, leave=0.381,
                             axial_leave=0.381, stepdown=19.05, stepover=0.16,
                             stl_path=TB_STL, workers=None, threads=4,
                             stock_cell=0.5, final_zmin=20.381)
    finally:
        B.channel_regions = _orig_cr
    assert replay, "no band regions emitted on the test block"
    with tempfile.TemporaryDirectory() as td:
        ngc = os.path.join(td, "tb.ngc")
        with open(ngc, "w") as fh:
            fh.write(moves_to_gcode(moves, spindle_rpm=7500))
        # pad the 0.5 mm hf like the judge grid: edge values, tool_r + 5 mm
        import numpy as _np
        hf = _np.load(TB_HF)
        with open(TB_HF[:-4] + ".json") as fh:
            meta = _json.load(fh)
        pad = int(math.ceil((tool_r + 5.0) / float(meta["cell"])))
        hf_p = os.path.join(td, "part_hf_0.5_padded.npy")
        _np.save(hf_p, _np.pad(hf, pad, mode="edge"))
        with open(hf_p[:-4] + ".json", "w") as fh:
            _json.dump({"x0": float(meta["x0"]) - pad * float(meta["cell"]),
                       "y0": float(meta["y0"]) - pad * float(meta["cell"]),
                       "cell": float(meta["cell"]),
                       "tess_tol": meta.get("tess_tol", 0.01)}, fh)
        rj = os.path.join(td, "zmap.json")
        dj = os.path.join(td, "ae2.json")
        rr = subprocess.run(
            [sys.executable, os.path.join(repo, "verify", "zmap.py"), ngc,
             "--part", hf_p, "--tool", "flat", "--dia", "%.3f" % dia,
             "--stock", *[str(v) for v in stock_box],
             "--engage-max", "2.438", "--ae2-dump", dj, "--out-json", rj],
            capture_output=True, text=True, cwd=repo)
        assert rr.returncode == 0, "zmap failed: %s | %s" % (
            rr.stdout[-800:], rr.stderr[-600:])
        wins = _json.load(open(dj))
    worst_ez = -9.0          # max (engine - zmap) over all windows
    worst_ze = -9.0          # max (zmap - engine) over all windows
    n_cmp = 0
    for reg in replay:
        pts = reg["pts"]
        i0 = None
        for i in range(len(moves) - len(pts)):
            m = moves[i]
            if (m["g"] == 1 and abs(m["x"] - pts[0][0]) < 1e-6
                    and abs(m["y"] - pts[0][1]) < 1e-6):
                if all(moves[i + k]["g"] == 1
                       and abs(moves[i + k]["x"] - pts[k][0]) < 1e-6
                       and abs(moves[i + k]["y"] - pts[k][1]) < 1e-6
                       for k in range(min(len(pts), 40))):
                    i0 = i
                    break
        assert i0 is not None, \
            "emitted region %s not found in the moves" % (reg["start"],)
        lo = 7 + i0   # moves[i0] ENDS at pts[0]; the region's own feed
        # moves are lines lo+1.. (an earlier link move is not the region)
        zw = sorted([w for w in wins if w["line"] >= lo + 1
                     and w["end_line"] <= 7 + i0 + len(pts) - 1],
                    key=lambda w: w["line"])
        assert len(reg["wins"]) == len(zw), \
            "window count differs for region %s: engine %d vs zmap %d" % (
                reg["start"], len(reg["wins"]), len(zw))
        zidx = [w["end_line"] - lo for w in zw]
        assert zidx == reg["idxs"], \
            "window boundaries differ for region %s: zmap %s vs engine %s" % (
                reg["start"], zidx[:8], reg["idxs"][:8])
        diffs = []
        for k, w in enumerate(zw):
            elen = reg["ends"][k] - (reg["ends"][k - 1] if k else 0.0)
            diffs.append(reg["wins"][k] / elen - w["ae_eff"])
        worst_ez = max(worst_ez, max(diffs))
        worst_ze = max(worst_ze, -min(diffs))
        n_cmp += 1
    assert n_cmp == len(replay), "some region could not be compared"
    # BS1a4c finding: with the honest entry credit (entry_credit, replayed
    # here at the region's carried credit) the entry-bore under-read of
    # BS1a4b (3.865 mm at k=1) is GONE - the residual under-read (~1.5 mm,
    # max window 0.25..1.49 mm) is the engine's cell-centre disk sampling on
    # the 0.5 mm grid vs zmap's replay, spread over light-load windows along
    # the trochoid, plus one credit-geometry window at the start (the credit
    # disk about the start point vs the emitted helix's stadium). Boundaries
    # stay identical (asserted above). The 0.15 mm bar is therefore NOT met
    # by the credit port alone; per the brief's STOP rule both directions are
    # reported, not asserted (see BS1a4_RESULTS.md section 10).
    print("bs1a4b max diff both ways: engine-zmap %+.3f mm, zmap-engine "
          "%.3f mm" % (worst_ez, worst_ze))
    print("PASS bs1a4b alignment: %d region(s), window boundaries identical;"
          " max engine-zmap %+.3f mm, max zmap-engine %.3f mm" % (
              n_cmp, worst_ez, worst_ze))


def test_bs1a4c_fix_no_post_entry_helix():
    """BS1a4c-fix (supervisor): a credited band start that is not backed at
    emit must never get a helix emitted AFTER enter_at (the tool is already
    at depth there): the L-shaped channel must rough without a CLCHECK
    refusal (no sample below CL + axial_leave) and record no 'ladder_helix'
    fallback. FAILS on a29696d (CLCHECK: 18 mm below CL at X-4.208 Y-0.704)."""
    from opencamlib import ocl
    import tempfile
    from engine.rough import rough
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0))
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "bs1a4c_fix.stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        try:
            _m, stats = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 18.0),
                              6.343, 0.0, leave=0.381, axial_leave=0.381,
                              stepdown=19.05, stepup=1.905, tolerance=0.05,
                              threads=4, stock_cell=0.5, min_rest=0.5,
                              corner_r=0.0, stl_path=stl)
        except RuntimeError as e:
            raise AssertionError("rough refused on CL (a backing move gouged): %s"
                                 % str(e)[:200])
    acts = [f[3] for f in stats.get("credit_fallback", [])]
    assert "ladder_helix" not in acts, "post-entry helix emitted: %s" % acts
    assert stats.get("clcheck_violations", 0) == 0, stats.get("clcheck_violations")
    print("PASS bs1a4c-fix: L channel roughs CL-clean, fallbacks %s" % acts)


def test_bs1a4c_backed_credit():
    """Task BS1a4c: honest (backed) entry credit. channel_regions plans its
    ZE2 replays with entry_credit - tool_r ONLY where standing stock under
    the start disk forces a helix descent at emit time, else 0 (never the
    synthetic 1.3 x tool_r pre-clear) - and every band region carries that
    credit; rough.py backs it at emit time (ladder helix, else credit-0
    re-check against the gates, else not emitted) and records every fallback
    in stats["credit_fallback"]. Assert here: the stat exists, every emitted
    band region carries an honest credit (0 or tool_r) equal to
    entry_credit on the LIVE planning stock, and every recorded fallback is
    one of the three backed actions. FAILS on e5e783e: there the stat does
    not exist and regions carry no credit (the sim pre-clears 1.3 x tool_r
    unconditionally)."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(TB_STL)
    from opencamlib import ocl
    import engine.band as B
    from engine.rough import rough
    captured = []

    def cr_spy(rings, stock, isl_ok3, z, tool_r, leave, cell, stats=None):
        res = _orig_cr(rings, stock, isl_ok3, z, tool_r, leave, cell, stats)
        for r in res:
            assert "credit" in r, \
                "band region carries no honest entry credit: the planning " \
                "sim still assumes the synthetic 1.3 x tool_r entry bore"
            assert -1e-9 <= r["credit"] <= tool_r + 1e-9, \
                "credit %r exceeds the disk an emitted helix can bore " \
                "(tool_r = %r)" % (r["credit"], tool_r)
            assert abs(r["credit"] - B.entry_credit(stock, r["start"], z,
                                                    tool_r)) < 1e-9, \
                "region credit %r != entry_credit on the live stock at %s" % (
                    r["credit"], r["start"])
            captured.append((round(z, 3), tuple(r["start"]), r["credit"]))
        return res

    _orig_cr = B.channel_regions
    B.channel_regions = cr_spy
    try:
        stock_box = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
        tool_r = 6.343
        surf = ocl.STLSurf()
        ocl.STLReader(TB_STL, surf)
        moves, stats = rough(surf, stock_box, tool_r, 20.0, leave=0.381,
                             axial_leave=0.381, stepdown=19.05, stepover=0.16,
                             stl_path=TB_STL, workers=None, threads=4,
                             stock_cell=0.5, final_zmin=20.381)
    finally:
        B.channel_regions = _orig_cr
    assert "credit_fallback" in stats, \
        "stats has no credit_fallback: emit does not back entry credits"
    assert captured, "no band regions emitted on the test block"
    for f in stats["credit_fallback"]:
        assert f[3] in ("ladder_helix", "replan0_ok", "replan0_drop"), \
            "unknown credit fallback action: %r" % (f,)
    print("PASS bs1a4c backed credit: %d region(s) %s, fallbacks %s" % (
        len(captured), captured, stats["credit_fallback"]))



def test_bs1a4c2_band_chord_cl_checked():
    """Task BS1a4c-2: every emitted band cutting chord is CL-checked
    SEGMENT-SAMPLED (every <= 0.25 mm, the way validate_exact samples
    segments), not only its points; a discontinuous trochoid is split at the
    jump into separate regions joined through enter_at's CL-checked ladder,
    and a piece with no legal join is rejected AND listed in
    stats["failed_region_emitted"]. FAILS on 351ce50: with honest credit both
    L-channel regions fail every shrink level and the chosen shrunk path
    carries a 5.4 mm straight chord across the part that reaches CLCHECK
    (bad moves 2068/2107, 18 mm below CL)."""
    import math
    import os
    from opencamlib import ocl
    import tempfile
    import engine.band as B
    from engine.rough import rough
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)       # floor
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)     # left wall
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)      # bottom wall
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)          # inner crn
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)          # right wall
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)         # upr-left
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0))         # top cap
    jumps = []

    def cr_spy(rings, stock, isl_ok3, z, tool_r, leave, cell, stats=None):
        res = _orig_cr(rings, stock, isl_ok3, z, tool_r, leave, cell, stats)
        for r in res:
            for (kind, pts) in r["paths"]:
                if kind != "cutting":
                    continue
                for a, b in zip(pts[:-1], pts[1:]):
                    d = math.dist(a, b)
                    n = max(1, int(math.ceil(d / 0.25)))
                    if not all(isl_ok3([(a[0] + (b[0] - a[0]) * t / n,
                                          a[1] + (b[1] - a[1]) * t / n)
                                         for t in range(n + 1)])):
                        jumps.append((round(z, 3), a, b, round(d, 2)))
        return res

    _orig_cr = B.channel_regions
    B.channel_regions = cr_spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1a4c2.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            try:
                _m, stats = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0,
                                         18.0), 6.343, 0.0, leave=0.381,
                                 axial_leave=0.381, stepdown=19.05,
                                 stepup=1.905, tolerance=0.05, threads=4,
                                 stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                                 stl_path=stl)
            except RuntimeError as e:
                raise AssertionError(
                    "rough refused on CL (an unsegment-checked chord gouged):"
                    " %s" % str(e)[:200])
    finally:
        B.channel_regions = _orig_cr
    assert not jumps, "emitted band chord fails the segment-sampled CL check" \
                      " (or an unsplit jump): %s" % jumps[:4]
    assert stats.get("clcheck_violations", 0) == 0, stats.get(
        "clcheck_violations")
    assert "failed_region_emitted" in stats, "no failed_region_emitted list"
    print("PASS bs1a4c-2: every emitted band chord CL-checked at 0.25 mm; "
          "%d band region(s), %d listed failed piece(s)" % (
              stats.get("n_band_regions", 0),
              len(stats["failed_region_emitted"])))


def test_bs1a4d_credit0_lightest_option():
    """Task BS1a4d (a0): a credited band region that fails the credit-0
    re-check at emit is NOT silently dropped - it takes Fix 1's lightest
    option (the shrink ladder re-simulated at credit 0 on the LIVE stock vs
    drop-to-ring, same ranking) and is listed in
    stats["failed_region_emitted"] with place, Z, area, option and engine max
    ae; the program still passes CLCHECK. The unbacked credit is forced
    honestly: every single-point stock.link_clear([q,q], z) - the backing
    check itself - reports False, i.e. no emitted move backed the credit.
    FAILS on 22cdff7: there the real-bore planning credit (which proposes the
    region that fails its credit-0 re-check at emit) does not exist, so no
    credit-0 failure ever fires in this scene (every re-check passes at
    credit 0) - vacuous there; and any credit-0 failure 22cdff7 did hit was
    an unconditional drop, never listed in failed_region_emitted."""
    from opencamlib import ocl
    import tempfile
    import engine.band as B
    from engine.rough import rough
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0))
    _orig_cr = B.channel_regions

    def cr_spy(rings, stock, isl_ok3, z, tool_r, leave, cell, stats=None,
               **kw):
        res = _orig_cr(rings, stock, isl_ok3, z, tool_r, leave, cell, stats,
                       **kw)
        if not getattr(stock, "_bs1a4d_forced", False):
            stock._bs1a4d_forced = True
            lc0 = stock.link_clear

            def lc(pts, h, eps=0.05):
                if abs(h - z) <= 1e-6 and len(set(pts)) == 1:
                    return False   # the credit-backing single-point check
                return lc0(pts, h, eps)
            stock.link_clear = lc
        return res

    B.channel_regions = cr_spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1a4d_a0.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            try:
                _m, stats = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0,
                                         18.0), 6.343, 0.0, leave=0.381,
                                 axial_leave=0.381, stepdown=19.05,
                                 stepup=1.905, tolerance=0.05, threads=4,
                                 stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                                 stl_path=stl)
            except RuntimeError as e:
                raise AssertionError(
                    "rough refused on CL (a credit-0 fallback move gouged):"
                    " %s" % str(e)[:200])
    finally:
        B.channel_regions = _orig_cr
    acts = [f[3] for f in stats.get("credit_fallback", [])]
    bad = [f for f in stats.get("credit_fallback", [])
           if f[3].startswith("replan0_") and f[3] != "replan0_ok"]
    assert bad, \
        "no credit-0 FAILING re-check fired - scenario vacuous: %s" % (acts,)
    fre = stats.get("failed_region_emitted", [])
    for f in stats["credit_fallback"]:
        if f[3].startswith("replan0_") and f[3] != "replan0_ok":
            assert any(abs(e["x"] - f[0]) < 1.5 and abs(e["y"] - f[1]) < 1.5
                      and abs(e["z"] - f[2]) < 1e-6 for e in fre), \
                "credit-0 failure %r was silently dropped - not listed in " \
                "failed_region_emitted: %s" % (f, fre)
            e = [e for e in fre if abs(e["x"] - f[0]) < 1.5
                 and abs(e["y"] - f[1]) < 1.5 and abs(e["z"] - f[2]) < 1e-6][0]
            assert e["option"] != "drop_ring" and f[3] == "replan0_" + e["option"], \
                "credit-0 failure %r not EMITTED as its lightest option: %s" % (f, e)
            cut = [m for m in _m if m["g"] == 1 and m.get("z") is not None
                   and abs(m["z"] - f[2]) < 1e-6
                   and math.dist((m["x"], m["y"]), (f[0], f[1])) < 1.0]
            assert cut, "credit-0 failure %r: no cut emitted at its start" % (f,)
    assert stats.get("clcheck_violations", 0) == 0, stats.get(
        "clcheck_violations")
    print("PASS bs1a4d(a0): credit-0 failures %s, listed %s" % (
        [a for a in acts if a.startswith("replan0_")],
        [(e["x"], e["y"], e["z"], e["option"], e["max_ae"]) for e in fre]))


def test_bs1a4d5_splitbore_failed_recheck_not_emitted_at_load():
    """BS1a4d5 (supervisor): a credited split piece whose real-bore emit
    re-check FAILS its gate is never emitted at the failing load: it goes
    through the re-check's own shrink ladder (like plan0_split) and is listed
    in failed_region_emitted at its lightest option (or dropped to the ring).
    The L scene of test_bs1a4d_credit_real_bore has plan0_splitbore pieces;
    the test forces each one's real-bore re-check (the band._simulate call at
    emit with the piece start and its stored bore) to read 0.75 mm over
    AE_SPIKE. FAILS when the engine keeps the piece instead
    (plan0_splitbore_keep): the message gives the measured overload in mm."""
    import tempfile
    from opencamlib import ocl
    import engine.band as B
    from engine.rough import rough
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0))
    split, forced = {}, {}
    _orig_cr, _orig_sim = B.channel_regions, B._simulate
    over = B.AE_SPIKE + 0.75

    def cr_spy(rings, stock, isl_ok3, z, tool_r, leave, cell, stats=None,
               **kw):
        res = _orig_cr(rings, stock, isl_ok3, z, tool_r, leave, cell, stats,
                       **kw)
        for r in res:
            if r.get("replan0") == 2:
                split[(round(z, 3), round(r["start"][0], 4),
                       round(r["start"][1], 4))] = tuple(r["bore"][2:])
        return res

    def sim_spy(path, stock, z, tool_r, cell, bore_r, ends=None, **kw):
        w = _orig_sim(path, stock, z, tool_r, cell, bore_r, ends, **kw)
        key = (round(z, 3), round(path[0][0], 4), round(path[0][1], 4))
        bxy = kw.get("bore_xy")
        if bxy and key in split and max(abs(a - b) for a, b in
                                        zip(bxy, split[key])) < 1e-9:
            forced[key] = over          # the emit-time real-bore re-check
            return list(w) + [over]
        return w

    B._simulate = sim_spy
    B.channel_regions = cr_spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1a4d5.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            moves, stats = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0,
                                        18.0), 6.343, 0.0, leave=0.381,
                                axial_leave=0.381, stepdown=19.05,
                                stepup=1.905, tolerance=0.05, threads=4,
                                stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                                stl_path=stl)
    finally:
        B.channel_regions = _orig_cr
        B._simulate = _orig_sim
    assert split, "no plan0_splitbore piece on the L scene: vacuous"
    assert forced, "no real-bore re-check reached at emit: vacuous"
    acts = {(z, round(x, 4), round(y, 4)): a
            for (x, y, z, a) in stats["credit_fallback"]}
    fre = {(f["z"], round(f["x"], 4), round(f["y"], 4))
           for f in stats["failed_region_emitted"]}
    for key, ae in forced.items():
        act = acts.get(key)
        assert act is not None and act.startswith("replan0_") \
            and act != "replan0_ok", \
            "split piece %r emitted at the failing load (act %r): re-check " \
            "measured %.3f mm > AE_SPIKE %.2f, overload %.3f mm" % (
                key, act, ae, B.AE_SPIKE, ae - B.AE_SPIKE)
        assert key in fre, "failed split piece %r not in " \
            "failed_region_emitted (act %r)" % (key, act)
    print("PASS bs1a4d5 splitbore fail path: %d forced re-check(s), acts %s"
          % (len(forced), sorted({acts[k] for k in forced})))


def test_bs1a4d_credit_real_bore():
    """Task BS1a4d (c): at a helix-entered band start the planning sim's
    credit is the REAL bore footprint - the cutter disk swept along the
    emitted helix path plus its floor circle - not a tool_r disk centred on
    the path start: every cell the emitted entry clears is credited, and the
    credit is centred on the helix centre (offset from the start), covering
    far more than the start disk. FAILS on 22cdff7: there the credit is a
    tool_r disk about path[0] (bore_xy None) and hundreds of cells cleared by
    the emitted helix are re-counted as fresh loop cut."""
    import math
    import tempfile
    from opencamlib import ocl
    import engine.band as B
    from engine.rough import rough
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0))
    caps, sims, helixes = [], [], []
    _orig_cr, _orig_sim = B.channel_regions, B._simulate
    import engine.rough as R
    _orig_hm = R._helix_moves

    def hm_spy(cx, cy, sx, sy, z_top, z_bot, feed, r, angle_deg=2.0):
        mv = _orig_hm(cx, cy, sx, sy, z_top, z_bot, feed, r, angle_deg)
        helixes.append((cx, cy, r, z_bot))   # the EXACT emitted bore
        return mv

    def sim_spy(path, stock, z, tool_r, cell, bore_r, ends=None, **kw):
        # forward in the CALLER's form: on 22cdff7 the engine never passes
        # bore_xy, so base is called through its OLD signature there and this
        # test FAILS BY ASSERTION below, not with a TypeError.
        w = _orig_sim(path, stock, z, tool_r, cell, bore_r, ends, **kw)
        sims.append((round(z, 3), tuple(path[0]), bore_r,
                     tuple(kw["bore_xy"]) if kw.get("bore_xy") else None))
        return w

    def cr_spy(rings, stock, isl_ok3, z, tool_r, leave, cell, stats=None,
               **kw):
        snap = stock.top.copy()
        res = _orig_cr(rings, stock, isl_ok3, z, tool_r, leave, cell, stats,
                       **kw)
        for r in res:
            caps.append({"z": round(z, 3), "q": tuple(r["start"]),
                        "credit": r.get("credit") or 0.0, "snap": snap,
                        "x0": stock.x0, "y0": stock.y0, "cell": stock.cell})
        return res

    B._simulate = sim_spy
    B.channel_regions = cr_spy
    R._helix_moves = hm_spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1a4d_c.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            moves, stats = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0,
                                        18.0), 6.343, 0.0, leave=0.381,
                                axial_leave=0.381, stepdown=19.05,
                                stepup=1.905, tolerance=0.05, threads=4,
                                stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                                stl_path=stl)
    finally:
        B.channel_regions = _orig_cr
        B._simulate = _orig_sim
        R._helix_moves = _orig_hm

    def entry_pts(q, z):
        # the bore that matters for pre-crediting: cutter-disk sweep AT Z -
        # the HB1v2 floor circle (ramp feed, z == Z) plus the landing point.
        idx = next((i for i, mv in enumerate(moves) if mv.get("g") == 1
                    and abs((mv.get("z") or 9e9) - z) < 1e-6
                    and mv.get("x") is not None
                    and abs(mv["x"] - q[0]) < 1e-4
                    and abs(mv["y"] - q[1]) < 1e-4), None)
        if idx is None:
            return None
        pts, j = [q], idx - 1
        while j >= 0 and moves[j].get("g") == 1 \
                and abs(moves[j].get("f", 0) - 1270.0) < 1e-6 \
                and moves[j].get("x") is not None \
                and abs(moves[j]["z"] - z) < 1e-6:
            pts.append((moves[j]["x"], moves[j]["y"]))
            j -= 1
        return pts if len(pts) > 9 else None   # floor circle at Z + landing

    def cells(cap, pts, rad):
        out, c = set(), cap["cell"]
        k = int(math.ceil(rad / c))
        offs = [(di, dj) for dj in range(-k, k + 1)
                for di in range(-k, k + 1)
                if (di * di + dj * dj) * c * c <= rad * rad]
        for (px, py) in pts:
            i0 = int(math.floor((px - cap["x0"]) / c))
            j0 = int(math.floor((py - cap["y0"]) / c))
            for di, dj in offs:
                a, b = i0 + di, j0 + dj
                if 0 <= a < cap["snap"].shape[1] \
                        and 0 <= b < cap["snap"].shape[0] \
                        and cap["snap"][b, a] > cap["z"] + 0.05:
                    out.add((a, b))
        return out

    checked = 0
    for cap in caps:
        if cap["credit"] <= 1e-9:
            continue
        pts = entry_pts(cap["q"], cap["z"])
        if pts is None:
            continue                      # entry without an emitted helix
        # BS1a4d5 matcher: pair the cap with the planning or re-check sim
        # whose bore_xy IS its emitted helix (centre 1e-6, r 1e-6) - the
        # emitted helix captured exactly at _helix_moves, identified by its
        # own floor-circle run. No proximity matching.
        own = [h for h in helixes if abs(h[3] - cap["z"]) < 1e-6
               and all(abs(math.dist(p, (h[0], h[1])) - h[2]) < 1.5e-4
                       for p in pts[1:])]
        assert len(own) == 1, \
            "entry bore run at (%.4f,%.4f)@Z%.3f matches %d emitted helices" \
            % (cap["q"][0], cap["q"][1], cap["z"], len(own))
        hb = own[0]
        sim = next((s for s in sims if s[0] == cap["z"] and s[3] is not None
                    and math.dist(s[3][:2], hb[:2]) <= 1e-6
                    and abs(s[3][2] - hb[2]) <= 1e-6), None)
        if sim is None:
            near = min((s for s in sims if s[0] == cap["z"]
                        and s[3] is not None),
                       key=lambda s: math.dist(s[3][:2], hb[:2]),
                       default=None)
            raise AssertionError(
                "credited split cap (%.4f,%.4f)@Z%.3f emitted helix centre "
                "(%.4f,%.4f) r %.4f has NO planning or re-check sim with "
                "that bore: nearest planned bore centre (%.4f,%.4f) r %.4f, "
                "planning-vs-emitted bore offset %.4f mm" % (
                    cap["q"][0], cap["q"][1], cap["z"], hb[0], hb[1], hb[2],
                    near[3][0] if near else -1.0,
                    near[3][1] if near else -1.0,
                    near[3][2] if near else -1.0,
                    math.dist(near[3][:2], hb[:2]) if near else -1.0))
        assert sim[3] is not None, \
            "credited plan sim pre-cleared a disk about the path START " \
            "(%r), not the real helix-centred bore" % (sim,)
        credited = cells(cap, [sim[3][:2]], sim[2])
        credited |= cells(cap, [cap["q"]], 6.343)   # return-feed landing disk
        cleared = cells(cap, pts, 6.343)
        # BS1a4d6 (b): the "extra > 100" bound below was written for emitted
        # bores at the smallest helix tier (0.3 x tool_r = 1.9029 ~ 1.903); a
        # SMALLER emitted bore legitimately credits (about) the start disk, so
        # there the bound is scoped away and replaced: the credited area must
        # equal the emitted bore's OWN sim footprint - disk(helix centre,
        # r + tool_r) plus the landing disk - within the grid tolerance.
        if hb[2] < 0.3 * 6.343 - 1e-9:
            foot = cells(cap, [hb[:2]], hb[2] + 6.343)
            foot |= cells(cap, [cap["q"]], 6.343)
            assert len(credited ^ foot) <= 4, \
                "small-bore credit != the emitted bore's own footprint: " \
                "credited %d cells, emitted-helix footprint %d cells, area " \
                "difference %d > grid tolerance 4 at (%.3f,%.3f) r %.4f" % (
                    len(credited), len(foot), len(credited ^ foot),
                    cap["q"][0], cap["q"][1], hb[2])
        assert len(cleared - credited) <= 20, \
            "%d cell(s) cleared by the emitted entry are not credited at " \
            "(%.3f,%.3f) (bound 20 = return-feed stadium between helix end " \
            "and landing, not modelled at plan time)" % (
                len(cleared - credited), cap["q"][0], cap["q"][1])
        assert len(credited - cleared) <= 30, \
            "credit exceeds the swept floor-circle bore by %d cells (grid " \
            "chord sliver bound 30) at (%.3f,%.3f)" % (
                len(credited - cleared), cap["q"][0], cap["q"][1])
        start_disk = cells(cap, [cap["q"]], 6.343)
        if hb[2] >= 0.3 * 6.343 - 1e-9:   # BS1a4d6 (b): kept for r >= min_helix_r
            assert len(credited - start_disk) > 100, \
                "credit is still (about) the tool_r start disk: extra %d" % \
                len(credited - start_disk)
        checked += 1
    assert checked >= 1, "no helix-entered credited region was checked"
    print("PASS bs1a4d(c): %d helix-entered region(s) - credited cells cover "
          "the swept helix + floor-circle bore exactly (offset centre)"
          % checked)


def test_bs1a4d2b_centred_entry_bore():
    """Task BS1a4d2b: a band channel region's entry bores AT its trochoid
    start (centred helix). On the test block and the L-channel scenes, every
    credited band entry that bores (helix + HB1v2 floor circle emitted for
    it) has NO fresh stock under its start disk at the cut Z: 0 cells
    standing above Z + 0.05 inside disk(start, tool_r) that the entry did
    not sweep (cells cleared earlier at <= Z do not count), and the bore
    circle passes through the start (centre within r of it). An entry
    without its own bore must either find the disk already clear at emit or
    be listed in credit_fallback - never silent.
    FAILS on 2c8e11d: the main-tier bore centre sits d >= 1.5 mm from the
    start, so the start disk pokes past the bore edge - 43 fresh cells stand
    under the test-block region's start disk."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    _need(TB_STL)
    import tempfile
    from opencamlib import ocl
    import engine.band as B
    from engine.rough import rough
    tool_r = 6.343
    k_off = int(math.ceil(tool_r / 0.5))
    offs = [(di, dj) for dj in range(-k_off, k_off + 1)
            for di in range(-k_off, k_off + 1)
            if (di * di + dj * dj) * 0.25 <= tool_r * tool_r]
    l_tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)
              + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)
              + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)
              + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)
              + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)
              + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)
              + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0))

    def run_scene(name, stl_src, box, kw):
        caps = []
        _orig_cr = B.channel_regions

        def cr_spy(rings, stock, isl_ok3, z, tr_, leave, cell, stats=None,
                   **k2):
            res = _orig_cr(rings, stock, isl_ok3, z, tr_, leave, cell, stats,
                          **k2)
            for r in res:
                if (r.get("credit") or 0.0) > 1e-9:
                    caps.append({"z": z, "q": tuple(r["start"]),
                                "snap": stock.top.copy(), "x0": stock.x0,
                                "y0": stock.y0, "cell": cell})
            return res

        B.channel_regions = cr_spy
        try:
            with tempfile.TemporaryDirectory() as td:
                stl = stl_src or os.path.join(td, "%s.stl" % name)
                if stl_src is None:
                    _write_stl(stl, l_tris)
                surf = ocl.STLSurf()
                ocl.STLReader(stl, surf)
                try:
                    mv, st = rough(surf, box, tool_r, **kw)
                except RuntimeError as e:
                    raise AssertionError("%s: rough refused: %s"
                                       % (name, str(e)[:160]))
        finally:
            B.channel_regions = _orig_cr
        checked, nlink, seen = [], 0, set()
        fb = st.get("credit_fallback", [])
        for cap in caps:
            q, z = cap["q"], cap["z"]
            key = (round(z, 3), round(q[0], 2), round(q[1], 2))
            if key in seen:
                continue
            seen.add(key)
            cands = [i for i, m in enumerate(mv) if m["g"] == 1
                     and m["x"] is not None and m["z"] is not None
                     and abs(m["z"] - z) < 1e-6
                     and math.dist((m["x"], m["y"]), q) < 1e-4]
            if not cands:
                continue          # dropped region (listed by BS1a4d/-f tests)
            # the entry's OWN bore = the contiguous ramp-feed run ending just
            # before the return link (helix segments + HB1v2 floor circle;
            # links and cutting paths run at cutting feed and break the run).
            fz, own, idx = [], False, cands[0]
            for i in cands:
                run_fz, run_own = [], False
                for m in reversed(mv[:i]):
                    if m["g"] != 1 or m["x"] is None \
                            or abs(m.get("f", 0.0) - 1270.0) > 1e-6:
                        break
                    if m["z"] > z + 0.05:
                        run_own = True
                    elif abs(m["z"] - z) <= 1e-6:
                        run_fz.append((m["x"], m["y"]))
                if run_own and len(run_fz) >= 4:
                    fz, own, idx = run_fz, True, i
                    break
            # cells standing above Z+0.05 under the start disk: plan-time
            # fresh stock minus everything a feed move at <= Z swept before
            # the entry's landing move (the landing / return link itself is
            # NOT credited - that bite is what this task removes).
            ci = int(math.floor((q[0] - cap["x0"]) / cap["cell"]))
            cj = int(math.floor((q[1] - cap["y0"]) / cap["cell"]))
            fresh = set()
            for di, dj in offs:
                a, b = ci + di, cj + dj
                if 0 <= a < cap["snap"].shape[1] \
                        and 0 <= b < cap["snap"].shape[0] \
                        and cap["snap"][b, a] > z + 0.05:
                    fresh.add((a, b))
            cleared = set()
            for m in mv[:idx]:          # everything swept at <= Z beforehand
                if m["g"] != 1 or m["x"] is None or m["z"] > z + 1e-6 \
                        or math.dist((m["x"], m["y"]), q) > tool_r + 0.5:
                    continue
                mi = int(math.floor((m["x"] - cap["x0"]) / cap["cell"]))
                mj = int(math.floor((m["y"] - cap["y0"]) / cap["cell"]))
                cleared.update((mi + di, mj + dj) for di, dj in offs)
            standing = fresh - cleared
            if not own:
                # entry without its own bore: the start disk must already be
                # clear, else the entry must be recorded in credit_fallback.
                if standing:
                    assert any(abs(f[0] - q[0]) < 1.5 and abs(f[1] - q[1]) < 1.5
                             and abs(f[2] - round(z, 3)) < 1e-6 for f in fb), \
                        "%s: credited entry (%.3f,%.3f)@Z%.3f reached its " \
                        "start through %d fresh cell(s) with no bore and no " \
                        "credit_fallback listing - silent emit" % (
                            name, q[0], q[1], z, len(standing))
                else:
                    nlink += 1          # disk already cleared at emit time
                continue
            checked.append(key)
            cx = sum(p[0] for p in fz) / len(fz)
            cy = sum(p[1] for p in fz) / len(fz)
            rad = sum(math.dist(p, (cx, cy)) for p in fz) / len(fz)
            assert not standing, \
                "%s: %d cell(s) stand above Z+0.05 under the start disk " \
                "(%.3f,%.3f)@Z%.3f after its entry bore (centre (%.2f,%.2f) " \
                "r %.2f): the start disk pokes past the swept bore" % (
                    name, len(standing), q[0], q[1], z, cx, cy, rad)
            assert math.dist((cx, cy), q) <= rad + 0.3, \
                "%s: entry bore at (%.3f,%.3f)@Z%.3f is not centred on the " \
                "start: centre (%.2f,%.2f) is %.2f mm away > r + 0.3" % (
                    name, q[0], q[1], z, cx, cy, math.dist((cx, cy), q))
        return checked, nlink, st

    chk_tb, nl_tb, st_tb = run_scene(
        "bs1a4d2b_tb", TB_STL, (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0),
        dict(floor_z=20.0, leave=0.381, axial_leave=0.381, stepdown=19.05,
             stepover=0.16, stl_path=TB_STL, workers=None, threads=4,
             stock_cell=0.5, final_zmin=20.381))
    chk_ls, nl_ls, st_ls = run_scene(
        "bs1a4d2b_lshape", None, (-40.0, 40.0, -30.0, 30.0, -1.0, 18.0),
        dict(floor_z=0.0, leave=0.381, axial_leave=0.381, stepdown=19.05,
             stepup=1.905, tolerance=0.05, threads=4, stock_cell=0.5,
             min_rest=0.5, corner_r=0.0))
    assert any(abs(k[0] - 27.381) < 1e-6
               and math.dist((k[1], k[2]), (6.276, -2.078)) < 1.0
               for k in chk_tb), \
        "test-block region (6.28,-2.08)@Z27.381 not helix-entered+checked: %s" \
        % (chk_tb,)
    assert any(abs(k[0] - 0.381) < 1e-6
               and math.dist((k[1], k[2]), (-18.724, 0.685)) < 1.0
               for k in chk_ls), \
        "the L-channel arm start (-18.72,0.69)@Z0.381 was not helix-entered" \
        "+checked: %s" % (chk_ls,)
    assert len(chk_tb) >= 1 and len(chk_ls) >= 2, \
        "too few centred-bore entries checked (TB %d, L %d): vacuous" % (
            len(chk_tb), len(chk_ls))
    print("PASS bs1a4d2b: centred entry bores - %d bore-entered region(s) "
          "checked on the test block (+%d link-backed), %d on the L channel "
          "(+%d link-backed); credit_fallback TB=%s LS=%s" % (
              len(chk_tb), nl_tb, len(chk_ls), nl_ls,
              [f[3] for f in st_tb.get("credit_fallback", [])],
              [f[3] for f in st_ls.get("credit_fallback", [])]))


def test_bs1a4d4_credit_entry_matches_prediction():
    """Task BS1a4d4: band entry credit and the emitted entry are ONE
    decision. Where the bore predictor (_bore_pred via band.bore_context)
    accepts a centred bore for a credited band start, channel_regions stores
    that exact bore in the region (res["bore"] = start x, start y, centre x,
    centre y, radius) and rough.py enters at exactly that stored start with
    exactly that stored bore - no re-search. A region whose start disk stands
    (credit > 0) but where NO centred bore fits gets the normal full-tier
    ladder (centred=False), never the centred-only ladder that failed closed
    on Core Front. Scene: the L channel plus an island box beside the
    vertical arm; the trochoid starts hugging the inner-corner block have
    credit > 0 with no centred bore that fits, while other credited regions
    get predicted bores. Assert: rough generates; every credited region with
    a stored bore that bored entered at exactly that stored centre (within
    1e-6, centres captured exactly at _helix_moves) and radius; no region
    without a stored bore used the centred-only ladder (its own bore circle
    never passes through the entry: centred bores have |centre dist - r| =
    0.05, normal tiers >= 0.17); clcheck and axial counts are 0.
    FAILS on 6793ad9: band.py:471 stores no bore at all (0 stored bores) and
    rough.py:2129 passes centred="credit" in res - always True for band
    regions - so every band entry takes the centred-only ladder (the two
    corner entries there exhaust all 96 centred candidates)."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import tempfile
    from opencamlib import ocl
    import engine.band as B
    import engine.rough as R
    from engine.rough import rough
    tool_r = 6.343
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)      # floor
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)    # left wall
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)     # bottom wall
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)        # inner crn
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)        # right wall
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)       # upr-left
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0)        # top cap
            + _box_tris(5.5, 9.5, 12.0, 16.0, 0.0, 18.0))        # island
    caps = []
    _orig_cr, _orig_hm = B.channel_regions, R._helix_moves

    def cr_spy(rings, stock, isl_ok3, z, tr_, leave, cell, stats=None, **kw):
        res = _orig_cr(rings, stock, isl_ok3, z, tr_, leave, cell, stats, **kw)
        for r in res:
            caps.append({"z": round(z, 3), "q": tuple(r["start"]),
                         "credit": r.get("credit") or 0.0,
                         "bore": r.get("bore")})
        return res

    helixes = []

    def hm_spy(cx, cy, sx, sy, z_top, z_bot, feed, r, angle_deg=2.0):
        mv = _orig_hm(cx, cy, sx, sy, z_top, z_bot, feed, r, angle_deg)
        helixes.append((cx, cy, r, z_bot))   # the EXACT emitted bore
        return mv

    B.channel_regions = cr_spy
    R._helix_moves = hm_spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1a4d4.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            try:
                moves, stats = rough(
                    surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 18.0), tool_r, 0.0,
                    leave=0.381, axial_leave=0.381, stepdown=19.05,
                    stepup=1.905, tolerance=0.05, threads=4, stock_cell=0.5,
                    min_rest=0.5, corner_r=0.0, stl_path=stl)
            except RuntimeError as e:
                raise AssertionError("rough refused: %s" % str(e)[:160])
    finally:
        B.channel_regions = _orig_cr
        R._helix_moves = _orig_hm

    def own_helix(q, z):
        """the helix event whose floor-circle run ends in this region's
        landing move (its own bore), or None if the entry did not bore."""
        idx = next((i for i, m in enumerate(moves) if m["g"] == 1
                    and m["x"] is not None and m["z"] is not None
                    and abs(m["z"] - z) < 1e-6
                    and math.dist((m["x"], m["y"]), q) < 1e-4), None)
        if idx is None:
            return None
        fz, j = [], idx - 1
        while j >= 0:
            m = moves[j]
            if m["g"] == 0:
                j -= 1
                continue
            if m["g"] == 1 and m["x"] is not None:
                if abs(m.get("f", 0.0) - 1270.0) < 1e-6:
                    if abs(m["z"] - z) <= 1e-6:
                        fz.append((m["x"], m["y"]))
                    elif m["z"] > z + 0.05:
                        pass               # helix descent above Z
                    else:
                        break
                else:
                    break                  # cutting feed / link: other's run
            j -= 1
        if len(fz) < 5:
            return None
        own = [h for h in helixes if abs(h[3] - z) < 1e-6
               and all(abs(math.dist(p, (h[0], h[1])) - h[2]) < 1.5e-4
                       for p in fz)]
        assert len(own) == 1, \
            "entry bore run at (%.3f,%.3f)@Z%.3f matches %d emitted helices" \
            % (q[0], q[1], z, len(own))
        return own[0]

    bored = [c for c in caps if c["bore"] is not None]
    assert bored, \
        "no band region carries the bore its planner accepted: the credit " \
        "and the emitted entry are still two separate decisions"
    n_bore_helix = n_nobore_helix = 0
    for c in caps:
        q, z = c["q"], c["z"]
        if c["bore"] is not None:
            b = c["bore"]
            assert math.dist(b[:2], q) < 1e-4, \
                "stored bore start (%.3f,%.3f) != region start (%.3f,%.3f)" \
                % (b[0], b[1], q[0], q[1])
            own = own_helix(q, z)
            if own is None:
                continue                   # link-backed entry (disk cleared)
            n_bore_helix += 1
            assert math.dist((own[0], own[1]), (b[2], b[3])) < 1e-6 \
                and abs(own[2] - b[4]) < 1e-9, \
                "credited region (%.3f,%.3f)@Z%.3f bored at (%.4f,%.4f) " \
                "r %.4f, not its stored bore centre (%.4f,%.4f) r %.4f: " \
                "the emit re-searched its own ladder" % (
                    q[0], q[1], z, own[0], own[1], own[2], b[2], b[3], b[4])
        else:   # BS1a4d4 (c): every region WITHOUT a stored bore (credit now 0)
            own = own_helix(q, z)
            if own is None:
                continue
            n_nobore_helix += 1
            d = math.dist(own[:2], q)
            assert abs(d - own[2]) > 0.12, \
                "region (%.3f,%.3f)@Z%.3f with no predicted bore entered " \
                "through a centred-only bore (centre %.3f mm from entry, " \
                "r %.3f: circle passes through the entry)" % (
                    q[0], q[1], z, d, own[2])
    assert n_bore_helix >= 1, \
        "no credited region bored with its stored bore: vacuous"
    assert n_nobore_helix >= 1, \
        "no credit-0 region needed a descent (no bore to deny it): vacuous"
    assert stats.get("clcheck_violations", 0) == 0, stats.get(
        "clcheck_violations")
    assert stats.get("n_axial_plunge", 0) == 0, stats.get("axial_pts")
    print("PASS bs1a4d4: %d credited region(s), %d stored bore(s), %d "
          "entered with exactly their stored bore, %d credit-0 descents all "
          "on the normal ladder; clcheck/axial 0" % (
              sum(1 for c in caps if c["credit"] > 1e-9), len(bored),
              n_bore_helix, n_nobore_helix))


def test_bs1a4d4_entry_pinned_to_stored_start():
    """Task BS1a4d4 (coordinator): the emitted band entry is the predicted
    start even when the emitter's own pick would differ. Core Front's
    fail-closed entry was chosen from [res["start"], first cutting point]
    nearest the previous position - not the point the predictor evaluated.
    Scene: the L channel + island of test_bs1a4d4_credit_entry_matches_
    prediction. A channel_regions spy moves every bored region's
    res["start"] to a DECOY - the far end of its own (legal) cutting path -
    so the emitter's nearest-to-prev pick is the decoy wherever that is
    closer; the stored bore (planned at the true start) is untouched.
    Assert: no emitted helix is a centred bore through a decoy (circle
    through the decoy, not through the stored start), and at least one
    region bored with exactly its stored centre (1e-6) and radius. FAILS
    with an emitter that ignores res["bore"] (no pin, no stored-bore
    branch): it enters at the decoy with a centred bore there."""
    assert HAVE_AREA, "area module missing: run the engine suite with VibeCAD python"
    import tempfile
    from opencamlib import ocl
    import engine.band as B
    import engine.rough as R
    from engine.rough import rough
    tool_r = 6.343
    tris = (_box_tris(-40.0, 40.0, -30.0, 30.0, -1.0, 0.0)
            + _box_tris(-40.0, -28.0, -30.0, 30.0, 0.0, 18.0)
            + _box_tris(-28.0, 40.0, -30.0, -9.5, 0.0, 18.0)
            + _box_tris(2.0, 40.0, -9.5, -2.0, 0.0, 18.0)
            + _box_tris(9.5, 40.0, -2.0, 30.0, 0.0, 18.0)
            + _box_tris(-40.0, -9.5, 9.5, 30.0, 0.0, 18.0)
            + _box_tris(-9.5, 9.5, 28.0, 30.0, 0.0, 18.0)
            + _box_tris(5.5, 9.5, 12.0, 16.0, 0.0, 18.0))
    decoys = []                    # (z, decoy xy, stored bore)
    _orig_cr, _orig_hm = B.channel_regions, R._helix_moves

    def cr_spy(rings, stock, isl_ok3, z, tr_, leave, cell, stats=None, **kw):
        res = _orig_cr(rings, stock, isl_ok3, z, tr_, leave, cell, stats, **kw)
        for r in res:
            b = r.get("bore")
            pts = r["paths"][0][1]
            if b and math.dist(pts[-1][:2], b[:2]) > 1.0:
                r["start"] = [pts[-1][0], pts[-1][1]]
                decoys.append((round(z, 4), tuple(pts[-1][:2]), b))
        return res

    helixes = []

    def hm_spy(cx, cy, sx, sy, z_top, z_bot, feed, r, angle_deg=2.0):
        helixes.append((cx, cy, r, z_bot))
        return _orig_hm(cx, cy, sx, sy, z_top, z_bot, feed, r, angle_deg)

    B.channel_regions = cr_spy
    R._helix_moves = hm_spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1a4d4_pin.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            try:
                moves, stats = rough(
                    surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 18.0), tool_r, 0.0,
                    leave=0.381, axial_leave=0.381, stepdown=19.05,
                    stepup=1.905, tolerance=0.05, threads=4, stock_cell=0.5,
                    min_rest=0.5, corner_r=0.0, stl_path=stl)
            except RuntimeError as e:
                raise AssertionError("rough refused: %s" % str(e)[:160])
    finally:
        B.channel_regions = _orig_cr
        R._helix_moves = _orig_hm
    assert decoys, "no bored band region to decoy: vacuous"
    n_exact = 0
    for (z, dxy, b) in decoys:
        at_z = [h for h in helixes if abs(h[3] - z) < 1e-6]
        for (cx, cy, r, _zb) in at_z:
            # the centred ladder's exact signature: centre = pick + (r - 0.05) u
            # (an off-centre normal-ladder bore of another region can pass
            # near a decoy, but not at exactly r - 0.05 from it)
            thru_decoy = abs(math.dist((cx, cy), dxy) - (r - 0.05)) < 1e-3
            thru_start = abs(math.dist((cx, cy), b[:2]) - (r - 0.05)) < 1e-3
            assert not (thru_decoy and not thru_start), \
                "band entry (%.3f,%.3f)@Z%.3f bored through the emitter's own " \
                "pick (%.3f,%.3f) with centre (%.4f,%.4f), not the stored start " \
                "and bore centre (%.4f,%.4f): entry re-chosen at emit" % (
                    b[0], b[1], z, dxy[0], dxy[1], cx, cy, b[2], b[3])
        if any(math.dist((cx, cy), b[2:4]) < 1e-6 and abs(r - b[4]) < 1e-9
               for (cx, cy, r, _zb) in at_z):
            n_exact += 1
    assert n_exact >= 1, "no decoyed region bored with its stored bore: vacuous"
    assert stats.get("clcheck_violations", 0) == 0
    assert stats.get("n_axial_plunge", 0) == 0
    print("PASS bs1a4d4 pin: %d decoyed region(s), %d bored with exactly "
          "their stored bore at the stored start; no entry re-chosen" % (
              len(decoys), n_exact))


def test_bs1a4d3_links_measured_as_cuts():
    """Task BS1a4d3 (e): a cutting-feed link that is not stock-clear on the
    cut-time stock at its Z is checked AS A CUT (band._simulate on the live
    stock at Z, credit 0); over SPIKE_MM 2.44 it is not emitted as a link -
    lift and re-entry through enter_at's ladder instead. Replay the emitted
    link moves of this open pocket (40 x 30, floor -1, stock top Z2.0,
    stepdown 1.5: links at the lower level cross the shelf the level above
    left) on pre-mill live-stock snapshots and require EVERY emitted flink /
    clip-bridge / flank-feed-in link to measure max window <= 2.44 mm.
    FAILS BY ASSERTION on d4ced08: there a flank feed-in at Z 0.381 (3.5 mm,
    past the descent column at (10.0, 5.4)) shears the shelf and measures
    4.00 mm > 2.44 with no window check at all."""
    import math
    import tempfile
    from opencamlib import ocl
    import engine.stock as S
    import engine.band as B
    from engine.rough import rough, AXIAL_FLOOR
    LIFT = 1.9                     # rough()'s default lift, unchanged here
    snaps, lcs = [], []
    orig_mp = S.StockField.mill_path
    orig_lc = S.StockField.link_clear

    def _snap(self):
        st = S.StockField.__new__(S.StockField)
        st.cell, st.x0, st.y0 = self.cell, self.x0, self.y0
        st.nx, st.ny = self.nx, self.ny
        st.top = self.top.copy()
        return st

    def spy_mp(self, pts, z, tool_r, corner_r=0.0):
        snaps.append((list(pts), z, tool_r, _snap(self)))
        return orig_mp(self, pts, z, tool_r, corner_r)

    def spy_lc(self, pts, h, eps=0.05):
        r = orig_lc(self, pts, h, eps)
        lcs.append((list(pts), h, r))
        return r

    def key(pts):
        return [(round(q[0], 4), round(q[1], 4)) for q in pts]

    def lc_ok(pts, h):
        kp = key(pts)
        return any(lok and abs(lh - h) <= 1e-6 and key(lp) == kp
                   for (lp, lh, lok) in lcs)

    def chord(pts):
        out, d0 = [pts[0]], None
        for a, b in zip(pts[1:], pts[2:]):
            d = math.dist(a, b)
            if not (1e-9 < d <= 0.55):
                break
            v = ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
            if d0 is None:
                d0, _ = v, out.append(a)
            elif v[0] * d0[0] + v[1] * d0[1] < 0.7071:
                break
            else:
                out.append(b)
        ln = sum(math.dist(out[i], out[i + 1]) for i in range(len(out) - 1))
        return out if len(out) >= 2 and ln <= 5.0 else None

    tris = (_box_tris(-20.0, 20.0, -15.0, 15.0, -1.0, 0.0)     # pocket floor
            + _box_tris(-40.0, -20.0, -30.0, 30.0, 0.0, 2.0)
            + _box_tris(20.0, 40.0, -30.0, 30.0, 0.0, 2.0)
            + _box_tris(-20.0, 20.0, -30.0, -15.0, 0.0, 2.0)
            + _box_tris(-20.0, 20.0, 15.0, 30.0, 0.0, 2.0))
    S.StockField.mill_path = spy_mp
    S.StockField.link_clear = spy_lc
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1a4d3.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            moves, stats = rough(
                surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 2.0), 6.343, 0.0,
                leave=0.381, axial_leave=0.381, stepdown=1.5, stepup=1.905,
                tolerance=0.05, threads=4, stock_cell=0.5, min_rest=0.5,
                corner_r=0.0, stl_path=stl)
    finally:
        S.StockField.mill_path = orig_mp
        S.StockField.link_clear = orig_lc
    # classify: dlink (stock-clear at Z - covered), flink (cleared only at
    # z+lift), flank feed-in (floor-checked at z+AXIAL_FLOOR), clip bridge
    # (run starting at the previous mill end, same Z, no stock check).
    cls = [None] * len(snaps)
    for k, (pts, z, tr, st) in enumerate(snaps):
        if len(pts) < 2:
            continue
        if lc_ok(pts, z):
            cls[k] = "dlink"
        elif lc_ok(pts, z + LIFT):
            cls[k] = "flink"
        elif lc_ok(pts, z + AXIAL_FLOOR):
            cls[k] = "feedin"
        elif k + 1 < len(snaps) and abs(snaps[k + 1][1] - z) <= 1e-6 and \
                key(pts[-1:]) == key(snaps[k + 1][0][:1]):
            cls[k] = "helixret"          # inside the swept bore: covered
    bad, nmeas = [], 0
    for k, (pts, z, tr, st) in enumerate(snaps):
        path = None
        if cls[k] in ("flink", "feedin"):
            path = pts
        elif cls[k] is None and k and abs(snaps[k - 1][1] - z) <= 1e-6 \
                and cls[k - 1] in (None, "bridge") and \
                key(snaps[k - 1][0][-1:]) == key(pts[:1]):
            path = chord(pts)          # the bridge chord only
            if path is not None:
                cls[k] = "bridge"
        if path is None or len(path) < 2:
            continue
        nmeas += 1
        wins = B._simulate([tuple(q[:2]) for q in path], st, z, tr,
                           st.cell, 0.0)
        mx = max(wins) if wins else 0.0
        if mx > 2.44 + 1e-9:
            bad.append((cls[k], round(z, 3), len(path), round(mx, 2),
                       (round(path[0][0], 2), round(path[0][1], 2))))
    assert nmeas >= 1, "no cutting-feed link was emitted/replayed: vacuous"
    assert not bad, \
        "cutting-feed link(s) cross stock at Z and measure over AE_SPIKE " \
        "2.44 (not checked as a cut): %s" % bad[:6]
    print("PASS bs1a4d3: %d cutting-feed link(s) replayed, all <= 2.44 mm; "
          "checked/converted flnk %s/%s brdg %s/%s fdin %s/%s" % (
              nmeas, stats.get("flnk_chk"), stats.get("flnk_cvt"),
              stats.get("brdg_chk"), stats.get("brdg_cvt"),
              stats.get("fdin_chk"), stats.get("fdin_cvt")))


if __name__ == "__main__":
    sys.exit(_main())
