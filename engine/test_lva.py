"""LVA (lever A, --air-descent-g0): a helix entry G0s down its column to
_lva_start() instead of spiralling at ramp feed from the link plane.
(a) _lva_start on synthetic StockField grids, values known analytically:
    open column -> column top + margin; a PART wall inside the helix's swept
    disk does NOT lift it (A1b: the helix circle is island-legal); STOCK
    standing in that disk does; part at the G0 column (R5 term) does; a wall
    inside the holder radius lifts it to the holder-safe height; unknown
    holder -> None (today's start);
(b) rough() on the BS1d scene: default == explicit off byte for byte.
Runnable directly or under pytest from VibeCAD python."""
import json
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)

TOOL_R, R_HX, MARGIN, Z = 6.343, 3.17, 1.0, 5.0
S = (-R_HX, 0.0)          # helix start point on the circle about (0, 0)


def _field(walls=(), stock=()):
    """Stock cleared to Z10 over the box. walls: PART features (x0, x1, y0,
    y1, top) - the stock over them stands at their top + 0.381 (the leave
    the rough keeps); stock: standing CUTTABLE stock blocks (no part)."""
    from engine.stock import StockField
    st = StockField((-50.0, 50.0, -50.0, 50.0, 0.0, 30.0), cell=0.5)
    st.top = np.where(st.inb, 10.0, -np.inf)
    xs = st.x0 + (np.arange(st.nx) + 0.5) * st.cell
    ys = st.y0 + (np.arange(st.ny) + 0.5) * st.cell
    part = np.full((st.ny, st.nx), -np.inf)
    box = lambda b: ((xs >= b[0]) & (xs <= b[1]))[None, :] & \
        ((ys >= b[2]) & (ys <= b[3]))[:, None]
    for w in walls:
        m = box(w)
        part[m] = w[4]
        st.top[m] = w[4] + 0.381
    for b in stock:
        m = box(b)
        st.top[m] = np.maximum(st.top[m], b[4])
    st.part = part
    return st


def _start(st, holder=(25.0, 71.6)):
    from engine.rough import _lva_start
    return _lva_start(st, 0.0, 0.0, R_HX, S, Z, TOOL_R, MARGIN, holder)


def test_lva_start_values():
    # open column: everything cleared to Z10 -> 10 + margin
    zs = _start(_field())
    assert zs is not None and abs(zs - 11.0) < 1e-6, zs
    # (A1b) a tall PART wall inside the helix's swept disk but outside the
    # tool disk at s: the island-legal helix cannot reach it, so the start
    # may go below its top (stays at the column floor + margin)
    wall = (9.5, 12.0, -3.0, 3.0, 18.0)
    zs_w = _start(_field([wall]))
    assert zs_w is not None and abs(zs_w - 11.0) < 1e-6, \
        "part wall in the helix disk: %r" % zs_w
    # STOCK standing in the helix disk above the column floor: the first
    # turns would side-cut it - the start stays margin over it
    blk = (9.5, 12.0, -3.0, 3.0, 15.0)
    zs_s = _start(_field(stock=[blk]))
    assert zs_s is not None and abs(zs_s - 16.0) < 1e-6, \
        "stock in the helix disk: %r" % zs_s
    # stock terrace sitting ON the part where the part stands above Z (part 8,
    # stock top 12, Z 5) inside the helix disk: island at Z, out of reach
    terr = _field([(9.5, 12.0, -3.0, 3.0, 8.0)])
    m = terr.part > -np.inf
    terr.top[m] = 12.0
    zs_t = _start(terr)
    assert zs_t is not None and abs(zs_t - 11.0) < 1e-6, \
        "stock on the part island: %r" % zs_t
    # a part wall within tool_r + margin of the G0 column s (R5 term):
    # x -12..-9.5 is 6.3..8.8 from s (-3.17, 0) -> inside 7.343
    wall_s = (-12.0, -9.5, -3.0, 3.0, 18.0)
    zs_r = _start(_field([wall_s]))
    assert zs_r is not None and abs(zs_r - 19.381) < 1e-6, \
        "part at the G0 column: %r" % zs_r
    # holder: wall 13..15 mm from the centre (outside the helix disk), 16.2
    # from s (inside holder_r + 1 = 21), top 25; stick-out 9 -> nose >= 1 mm
    # over its stock top 25.381: zs >= 25.381 - 9 + 1 = 17.381
    hwall = (13.0, 15.0, -3.0, 3.0, 25.0)
    zs_h = _start(_field([hwall]), holder=(20.0, 9.0))
    assert zs_h is not None and abs(zs_h - 17.381) < 1e-6, \
        "holder wall: %r" % zs_h
    zs_l = _start(_field([hwall]), holder=(20.0, 71.6))
    assert zs_l is not None and abs(zs_l - 11.0) < 1e-6, zs_l
    assert _start(_field(), holder=None) is None
    print("PASS lva start (A1b): open %.3f, part wall in helix disk %.3f, "
          "stock in helix disk %.3f, stock on the part island %.3f, part at "
          "the column %.3f, holder %.3f (long stick-out %.3f), unknown "
          "holder None" % (zs, zs_w, zs_s, zs_t, zs_r, zs_h, zs_l))


def test_lva_off_byte_identical():
    from opencamlib import ocl
    from engine.rough import rough
    from engine.test_engine import _box_tris, _write_stl
    bt = _box_tris
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    out = []
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "lva_off.stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        for flag in (None, 0):
            m, st = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0), 6.343,
                          0.0, leave=0.381, axial_leave=0.381, stepdown=19.05,
                          stepup=1.905, tolerance=0.05, threads=4,
                          stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                          stl_path=stl, side_entry_holder=(25.0, 71.6),
                          air_descent_g0=flag)
            assert st["lva"]["g0"] == 0, st["lva"]
            out.append(json.dumps(m))
    assert out[0] == out[1], "default != explicit off"
    print("PASS lva off: default == explicit off byte for byte")


if __name__ == "__main__":
    test_lva_start_values()
    test_lva_off_byte_identical()
