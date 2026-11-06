"""RAPID-A (--rapid-box / CAMBUDDY_RAPID_BOX, default OFF): an XY rapid's
verified height covers the rectangle its start and end span swept by the
tool disk (+ rapid_margin), not only the straight corridor - an
independent-axes control (lnc5800) may run it along any path inside that
rectangle.
(a) StockField.box_top_max reads material within pad of the rectangle, also
    off the straight corridor, and not material beyond pad of its corners;
(b) on the "L-island" scene (an L-shaped wall, two blocks and a tall post on
    one pocket floor) zmap's dogleg metric (verify/, report-only) finds XY
    rapids whose rectangle crosses stock or part above the tip with the flag
    OFF, and none with it ON; every rapid is still clear (rapid_collisions
    0) and the box rule is counted in stats;
(c) OFF is the default (no rapid_box stats key), the flag parses.
The panel's known sites (the traverse (-21.4625, 11.1896) ->
(-17.5188, 25.3958) at Z31.381 after a vertical lift, STEVE's full-depth
request) need STEVE's own stock file; they are proved on that request in
the proof, not here.
Runnable directly or under pytest from VibeCAD python."""
import json
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)

R = 6.343
BOX = (-40.0, 40.0, -30.0, 30.0, -1.0, 20.0)
_RUN = {}


def _scene_tris():
    from engine.test_engine import _box_tris as bt
    return (bt(-40, 40, -30, 30, -1, 0) + bt(-20, -5, -20, -5, 0, 20)
            + bt(-20, 15, -20, -14, 0, 20) + bt(5, 20, 5, 20, 0, 12)
            + bt(-25, -15, 10, 22, 0, 18))


def _surf(td):
    from opencamlib import ocl
    from engine.test_engine import _write_stl
    stl = os.path.join(td, "rapid_a.stl")
    _write_stl(stl, _scene_tris())
    surf = ocl.STLSurf()
    ocl.STLReader(stl, surf)
    return surf, stl


def _run(flag):
    if flag in _RUN:
        return _RUN[flag]
    from engine.rough import rough
    with tempfile.TemporaryDirectory() as td:
        surf, stl = _surf(td)
        _RUN[flag] = rough(surf, BOX, R, 0.0, leave=0.381, axial_leave=0.381,
                           stepdown=19.05, stepup=1.905, tolerance=0.05,
                           threads=4, stock_cell=0.5, min_rest=0.5,
                           corner_r=0.0, stl_path=stl,
                           side_entry_holder=(25.0, 71.6), rapid_box=flag)
    return _RUN[flag]


def _judge(moves):
    """zmap (verify/) with the dogleg report, on the scene's part grid"""
    from verify import zmap
    from engine.rough import build_part_hf
    with tempfile.TemporaryDirectory() as td:
        surf, _stl = _surf(td)
        cell, x0, y0 = 0.5, -50.0, -40.0
        p = build_part_hf(surf, x0, y0, cell, 200, 160, threads=4,
                          drop_z=-2.0)
    part = np.where(np.isfinite(p), p, -np.inf)
    lines = ["G21 G90"]
    for mv in moves:
        w = ["G0" if mv["g"] == 0 else "G1"]
        w += ["%s%.4f" % (k.upper(), mv[k]) for k in ("x", "y", "z")
              if mv.get(k) is not None]
        if mv["g"] == 1 and mv.get("f"):
            w.append("F%.1f" % mv["f"])
        lines.append(" ".join(w))
    res = zmap.simulate(zmap.parse_gcode("\n".join(lines) + "\n"), part,
                        cell, x0, y0, BOX, tool="flat", dia=2 * R,
                        dogleg=True)
    return res["rapid_collisions"]


def test_box_top_max_reads_the_swept_rectangle():
    """(a)"""
    from engine.stock import StockField
    st = StockField((-20.0, 20.0, -20.0, 20.0, 0.0, 30.0), cell=0.5)
    st.top[:] = np.where(st.inb, 10.0, -np.inf)
    st.top[st._cj(8.0), st._ci(-8.0)] = 25.0   # the rectangle's corner
    off = 0.9 * (R + 1.0)                      # within the square inflation,
    st.top[st._cj(8.0 + off), st._ci(-8.0 - off)] = 40.0   # beyond R + 1
    corridor = st.link_top_max([(-8.0, -8.0), (8.0, 8.0)], R + 1.0)
    box = st.box_top_max(-8.0, -8.0, 8.0, 8.0, R + 1.0)
    assert abs(corridor - 10.0) < 1e-9, corridor
    assert abs(box - 25.0) < 1e-9, box
    print("PASS rapid-a box_top_max: corridor %.1f, swept rectangle %.1f "
          "(corner-diagonal 40 excluded)" % (corridor, box))


def test_rapid_a_clears_the_dogleg():
    """(b)"""
    m_off, s_off = _run(0)
    m_on, s_on = _run(1)
    r_off, r_on = _judge(m_off), _judge(m_on)
    d_off, d_on = r_off["dogleg"], r_on["dogleg"]
    assert d_off["count"] >= 1, ("the scene lost its dogleg rapids", d_off)
    assert d_on["count"] == 0, ("ON leaves dogleg rapids", d_on)
    assert r_off["count"] == 0 and r_on["count"] == 0, (r_off["count"],
                                                        r_on["count"])
    assert s_on.get("rapid_box", 0) >= 1 and "rapid_box" not in s_off, \
        (s_on.get("rapid_box"), s_off.get("rapid_box"))
    print("PASS rapid-a L-island: dogleg OFF %d (max over %.3f, first %s) "
          "-> ON 0; rapids clear; %d rapids raised by the box"
          % (d_off["count"], d_off["max_over_mm"], d_off["moves"][0],
             s_on["rapid_box"]))


class _Parsed(Exception):
    def __init__(self, ns):
        super().__init__("parsed")
        self.ns = ns


def test_rapid_a_default_off_and_flag():
    """(c)"""
    old = os.environ.pop("CAMBUDDY_RAPID_BOX", None)
    try:
        m_def, s_def = _run(None)
    finally:
        if old is not None:
            os.environ["CAMBUDDY_RAPID_BOX"] = old
    m_off, _s = _run(0)
    assert "rapid_box" not in s_def
    assert json.dumps(m_def) == json.dumps(m_off), "default != OFF"
    import argparse
    from engine import cli
    orig = argparse.ArgumentParser.parse_args

    def grab(self, args=None, namespace=None):
        raise _Parsed(orig(self, args, namespace))
    argparse.ArgumentParser.parse_args = grab
    try:
        for argv, want in (([], None), (["--rapid-box", "1"], 1)):
            try:
                cli.main(["rough", "--step", "x.step", "--stock", "0", "1",
                          "0", "1", "0", "1", "--tool", "flat:12.686",
                          "--out", os.devnull, "--floor", "0"] + argv)
            except _Parsed as e:
                assert e.ns.rapid_box == want, (argv, e.ns.rapid_box)
            else:
                raise AssertionError("parser not reached")
    finally:
        argparse.ArgumentParser.parse_args = orig
    print("PASS rapid-a default OFF (no rapid_box key, default == off); "
          "--rapid-box parses")


if __name__ == "__main__":
    test_box_top_max_reads_the_swept_rectangle()
    test_rapid_a_clears_the_dogleg()
    test_rapid_a_default_off_and_flag()
