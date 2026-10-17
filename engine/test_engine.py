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

from engine.rough import plan_levels, rect_loop, decimate  # noqa: E402
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
    print("PASS adaptive2d convention: boss clearance %.4f == tool_r+leave "
          "%.2f, stock edge reach %.4f" % (min(boss_d), off, min(edge_d)))


def test_plan_levels():
    zs = plan_levels(60.96, 24.8, 0.3, 1.9)
    assert abs(zs[-1] - 25.1) < 1e-9
    assert all(zs[i] > zs[i + 1] for i in range(len(zs) - 1))
    assert all(zs[i] - zs[i + 1] <= 1.9 + 1e-9 for i in range(len(zs) - 1))
    assert zs[0] < 60.96  # level flush with stock top removed (cuts nothing)
    print("PASS plan_levels: %d levels %.3f..%.3f" % (len(zs), zs[0], zs[-1]))


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


def _main():
    fails = 0
    for fn in (test_adaptive2d_offset_convention, test_plan_levels,
               test_decimate, test_gcode_emit):
        try:
            fn()
        except AssertionError as e:
            fails += 1
            print("FAIL %s: %s" % (fn.__name__, e))
    print("%d failure(s)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_main())
