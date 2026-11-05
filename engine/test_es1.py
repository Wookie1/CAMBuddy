"""ES1 (--exact-square / CAMBUDDY_EXACT_SQUARE, default OFF): the LVA disk
scan counts a stock cell iff its 0.5 mm square meets the helix's swept disk
r + R exactly, instead of dilating cell centres by cell*sqrt(2)/2. On
test_lva's synthetic field (helix about (0, 0), r + R = 9.513, cells centred
on .25 / .75):
(a) a tall cell whose centre (9.75, 0.25) lies outside the disk but whose
    square reaches 9.50 counts -> start 16.0;
(b) a tall cell whose centre (9.75, 1.25) is inside the old dilation band
    (9.83 <= 9.867) but whose square's nearest point is 9.552 does NOT count
    -> start 11.0 (with ES1 off the dilation counts it -> 16.0);
(c) the R5 column term and (d) the holder clamp still apply unchanged;
(e) OFF is the default and --exact-square parses.
Runnable directly or under pytest from VibeCAD python."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "engine"))
from engine import model  # noqa: E402,F401  (puts area on the path)
import test_lva as tl  # noqa: E402  (its synthetic field and constants)


def _zs(st, holder=(25.0, 71.6), exact=True):
    from engine.rough import _lva_start
    return _lva_start(st, 0.0, 0.0, tl.R_HX, tl.S, tl.Z, tl.TOOL_R, tl.MARGIN,
                      holder, exact_square=exact)


def test_es1_square_rule():
    a = tl._field(stock=[(9.6, 9.9, 0.1, 0.4, 15.0)])     # cell (9.75, 0.25)
    za = _zs(a)
    assert za is not None and abs(za - 16.0) < 1e-6, ("(a) overlap cell", za)
    b = tl._field(stock=[(9.6, 9.9, 1.1, 1.4, 15.0)])     # cell (9.75, 1.25)
    zb, zb_off = _zs(b), _zs(b, exact=False)
    assert zb is not None and abs(zb - 11.0) < 1e-6, ("(b) band-only cell", zb)
    assert abs(zb_off - 16.0) < 1e-6, ("(b) dilation still counts it", zb_off)
    # (c) R5 column term: part wall 6.3..8.8 mm from s -> 19.381 (test_lva)
    zc = _zs(tl._field([(-12.0, -9.5, -3.0, 3.0, 18.0)]))
    assert zc is not None and abs(zc - 19.381) < 1e-6, ("(c) R5 column term", zc)
    # (d) holder clamp: wall inside holder_r + 1 of s, stick-out 9 -> 17.381
    zd = _zs(tl._field([(13.0, 15.0, -3.0, 3.0, 25.0)]), holder=(20.0, 9.0))
    assert zd is not None and abs(zd - 17.381) < 1e-6, ("(d) holder clamp", zd)
    assert _zs(tl._field(), holder=None) is None
    print("PASS es1 rule: overlap cell counts (%.3f), band-only cell does not "
          "(%.3f; dilation %.3f), R5 %.3f, holder %.3f" % (za, zb, zb_off, zc,
                                                           zd))


class _Parsed(Exception):
    def __init__(self, ns):
        super().__init__("parsed")
        self.ns = ns


def test_es1_default_off_and_flag():
    import tempfile
    from opencamlib import ocl
    from engine.rough import rough
    from engine.test_engine import _box_tris as bt, _write_stl
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    old = os.environ.pop("CAMBUDDY_EXACT_SQUARE", None)
    out = {}
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "es1.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            for tag, flag in (("default", None), ("off", 0)):
                m, _st = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0),
                               6.343, 0.0, leave=0.381, axial_leave=0.381,
                               stepdown=19.05, stepup=1.905, tolerance=0.05,
                               threads=4, stock_cell=0.5, min_rest=0.5,
                               corner_r=0.0, stl_path=stl,
                               side_entry_holder=(25.0, 71.6),
                               exact_square=flag)
                out[tag] = json.dumps(m)
    finally:
        if old is not None:
            os.environ["CAMBUDDY_EXACT_SQUARE"] = old
    assert out["default"] == out["off"], "default != explicit off"
    import argparse
    from engine import cli
    orig = argparse.ArgumentParser.parse_args

    def grab(self, args=None, namespace=None):
        raise _Parsed(orig(self, args, namespace))
    argparse.ArgumentParser.parse_args = grab
    try:
        for argv, want in (([], None), (["--exact-square", "1"], 1)):
            try:
                cli.main(["rough", "--step", "x.step", "--stock", "0", "1",
                          "0", "1", "0", "1", "--tool", "flat:12.686",
                          "--out", os.devnull, "--floor", "0"] + argv)
            except _Parsed as e:
                assert e.ns.exact_square == want, (argv, e.ns.exact_square)
            else:
                raise AssertionError("parser not reached")
    finally:
        argparse.ArgumentParser.parse_args = orig
    print("PASS es1 default OFF (default == off); --exact-square parses")


if __name__ == "__main__":
    test_es1_square_rule()
    test_es1_default_off_and_flag()
