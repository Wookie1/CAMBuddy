"""LVA (lever A, --air-descent-g0): a helix entry G0s down its column to
_lva_start() instead of spiralling at ramp feed from the link plane.
(a) _lva_start on synthetic StockField grids, values known analytically:
    open column -> column top + margin; a PART wall inside the helix's swept
    disk (outside the tool disk at the G0 column) lifts the start over it; a
    wall inside the holder radius (outside the helix disk) lifts it to the
    holder-safe height; unknown holder -> None (today's start);
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


def _field(walls=()):
    """Stock cleared to Z10 over the box; part = the given walls
    (x0, x1, y0, y1, top), -inf elsewhere."""
    from engine.stock import StockField
    st = StockField((-50.0, 50.0, -50.0, 50.0, 0.0, 20.0), cell=0.5)
    st.top = np.where(st.inb, 10.0, -np.inf)
    xs = st.x0 + (np.arange(st.nx) + 0.5) * st.cell
    ys = st.y0 + (np.arange(st.ny) + 0.5) * st.cell
    part = np.full((st.ny, st.nx), -np.inf)
    for (x0, x1, y0, y1, zt) in walls:
        m = ((xs >= x0) & (xs <= x1))[None, :] & \
            ((ys >= y0) & (ys <= y1))[:, None]
        part[m] = zt
        st.top[m] = np.maximum(st.top[m], zt)
    st.part = part
    return st


def _start(st, holder=(25.0, 71.6)):
    from engine.rough import _lva_start
    return _lva_start(st, 0.0, 0.0, R_HX, S, Z, TOOL_R, MARGIN, holder)


def test_lva_start_values():
    # open column: top Z10 everywhere -> 10 + margin
    zs = _start(_field())
    assert abs(zs - 11.0) < 1e-6, zs
    # part wall 9.5..12 mm from the centre: inside r + R + margin (10.51),
    # 12.67 mm from the G0 column s (outside its tool disk) -> over the wall
    wall = (9.5, 12.0, -3.0, 3.0, 18.0)
    zs_w = _start(_field([wall]))
    assert zs_w is not None and abs(zs_w - 19.0) < 1e-6, "part wall in the helix disk: %r" % zs_w
    # holder: wall 13..15 mm from the centre (outside the helix disk), 16.2
    # from s (inside holder_r + 1 = 21), top 25; stick-out 9 -> nose >= 1 mm
    # over it: zs >= 25 - 9 + 1 = 17
    hwall = (13.0, 15.0, -3.0, 3.0, 25.0)
    zs_h = _start(_field([hwall]), holder=(20.0, 9.0))
    assert zs_h is not None and abs(zs_h - 17.0) < 1e-6, "holder wall: %r" % zs_h
    # the same wall with the long stick-out does not bind
    zs_l = _start(_field([hwall]), holder=(20.0, 71.6))
    assert zs_l is not None and abs(zs_l - 11.0) < 1e-6, zs_l
    assert _start(_field(), holder=None) is None
    print("PASS lva start: open %.3f, part wall %.3f, holder %.3f (long "
          "stick-out %.3f), unknown holder None" % (zs, zs_w, zs_h, zs_l))


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
