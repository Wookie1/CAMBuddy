"""GR (--gap-relink), default OFF. The at-depth relink verdict _gr_link_ok
is exactly the deep-link checks; each one is shown to refuse on its own:
(a) all checks pass -> relink allowed;
(b) one island-illegal sample (isl_ok3) -> refused;
(c) one segment crossing the level's forbidden loops (corridor_ok) -> refused;
(d) one stock cell 0.5 mm above Z on the line (link_clear at Z; thin, so
    the strip measure stays under the bar) -> refused;
(e) stock just outside the tool radius on both sides (link_clear passes, the
    strip measure reaches R + 0.75 cell and reads a full-width shear) ->
    refused;
(f) OFF is the default (no "gr" stats key, default == off), --gap-relink
    parses.
The link_clear at Z + lift check cannot fail alone while link_clear at Z
passes (heights are monotone), so it has no separate case.
Runnable directly or under pytest from VibeCAD python."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)

R, Z, LIFT = 6.343, 10.0, 1.9


def _case(isl=None, cor=None, raise_cells=(), yc=0.0):
    from engine.rough import _gr_link_ok, _dense_line
    from engine.stock import StockField
    st = StockField((-30.0, 30.0, -30.0, 30.0, 0.0, 20.0), cell=0.5)
    st.top[:] = Z
    st.set_tool(R)
    for (x, y, h) in raise_cells:
        st.top[st._cj(y), st._ci(x)] = Z + h
    corridor = [(round(a, 4), round(b, 4))
                for (a, b) in _dense_line((-5.0, yc), (5.0, yc))]
    isl_ok3 = isl or (lambda pts: [True] * len(pts))
    corridor_ok = cor or (lambda a, b: True)
    return _gr_link_ok(corridor, Z, LIFT, isl_ok3, corridor_ok, st, R)


def test_gr_link_ok_each_check():
    assert _case() is True, "(a) a clean corridor must relink"
    assert _case(isl=lambda pts: [True] * (len(pts) - 1) + [False]) is False, \
        "(b) an island-illegal sample must refuse"
    assert _case(cor=lambda a, b: not (a[0] < 0.0 <= b[0])) is False, \
        "(c) a segment over the forbidden loops must refuse"
    assert _case(raise_cells=[(0.0, 0.0, 0.5)]) is False, \
        "(d) stock above Z on the line must refuse"
    # corridor at y 0.15: stock rows with cell centres at y 6.75 and -6.25
    # sit 6.60 / 6.40 mm from it - outside R (link_clear passes) but inside
    # the strip measure's R + 0.75 cell reach, 13 mm apart
    side = [(x * 0.5, y, 3.0) for x in range(-8, 9) for y in (6.75, -6.25)]
    from engine.rough import _strip_engage  # noqa: F401  (the measure)
    assert _case(raise_cells=side, yc=0.15) is False, \
        "(e) a wide shear just outside R must refuse"
    print("PASS gr verdict: clean relinks; island, corridor, stock at Z and "
          "wide shear each refuse")


class _Parsed(Exception):
    def __init__(self, ns):
        super().__init__("parsed")
        self.ns = ns


def _bs1d(**kw):
    from opencamlib import ocl
    from engine.rough import rough
    from engine.test_engine import _box_tris as bt, _write_stl
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "gr.stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        return rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0), 6.343, 0.0,
                     leave=0.381, axial_leave=0.381, stepdown=19.05,
                     stepup=1.905, tolerance=0.05, threads=4, stock_cell=0.5,
                     min_rest=0.5, corner_r=0.0, stl_path=stl,
                     side_entry_holder=(25.0, 71.6), **kw)


def test_gr_default_off_and_flag():
    old = os.environ.pop("ENGINE_GAP_RELINK", None)
    try:
        m_def, s_def = _bs1d()
        m_off, s_off = _bs1d(gap_relink=0)
    finally:
        if old is not None:
            os.environ["ENGINE_GAP_RELINK"] = old
    assert "gr" not in s_def and "gr" not in s_off
    assert json.dumps(m_def) == json.dumps(m_off), "default != explicit off"
    import argparse
    from engine import cli
    orig = argparse.ArgumentParser.parse_args

    def grab(self, args=None, namespace=None):
        raise _Parsed(orig(self, args, namespace))
    argparse.ArgumentParser.parse_args = grab
    try:
        for argv, want in (([], None), (["--gap-relink", "1"], 1)):
            try:
                cli.main(["rough", "--step", "x.step", "--stock", "0", "1",
                          "0", "1", "0", "1", "--tool", "flat:12.686",
                          "--out", os.devnull, "--floor", "0"] + argv)
            except _Parsed as e:
                assert e.ns.gap_relink == want, (argv, e.ns.gap_relink)
            else:
                raise AssertionError("parser not reached")
    finally:
        argparse.ArgumentParser.parse_args = orig
    print("PASS gr default OFF (no gr key, default == off); --gap-relink "
          "parses")


if __name__ == "__main__":
    test_gr_link_ok_each_check()
    test_gr_default_off_and_flag()
