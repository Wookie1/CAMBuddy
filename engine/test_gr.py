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
    parses;
(g) wiring, on a two-pocket scene: relinks through the link-fallback site,
    fewer helices than OFF, relinks emitted as G1 feeds at Z (the clip
    re-entry and a2d LinkNotClear sites do not relink there).
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
    # GR's own no-shear rule: a thin shear (one stock row 6.40 mm from the
    # corridor, inside the strip reach, width < 2.438) passes the deep-link
    # verdict but must be refused by _gr_no_shear
    from engine.rough import _gr_no_shear, _dense_line as _dl
    from engine.stock import StockField
    st = StockField((-30.0, 30.0, -30.0, 30.0, 0.0, 20.0), cell=0.5)
    st.top[:] = Z
    st.set_tool(R)
    for x in range(-8, 9):
        st.top[st._cj(-6.25), st._ci(x * 0.5)] = Z + 3.0
    cor = [(round(a, 4), round(b, 4)) for (a, b) in _dl((-5.0, 0.15), (5.0, 0.15))]
    assert _case(raise_cells=[(x * 0.5, -6.25, 3.0) for x in range(-8, 9)],
                 yc=0.15) is True, "thin shear must pass the deep-link verdict"
    assert _gr_no_shear(st, cor, Z, R) is False, "GR must refuse any shear"
    st.top[:] = Z
    assert _gr_no_shear(st, cor, Z, R) is True
    print("PASS gr verdict: clean relinks; island, corridor, stock at Z and "
          "wide shear each refuse; GR refuses a thin shear the deep links allow")


def _twopock(flag):
    """Two pockets joined at both ends of a centre wall gap (one 2.286 mm
    level): Adaptive2d links between them lift, and clip breaks re-enter."""
    from opencamlib import ocl
    from engine.rough import rough
    from engine.test_engine import _box_tris as bt, _write_stl
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-2, 2, -25, -4, 0, 14)
            + bt(-2, 2, 4, 25, 0, 14))
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "gr2.stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        return rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0), 6.343, 0.0,
                     leave=0.381, axial_leave=0.381, stepdown=19.05,
                     stepup=1.905, tolerance=0.05, threads=4, stock_cell=0.5,
                     min_rest=0.5, corner_r=0.0, stl_path=stl,
                     side_entry_holder=(25.0, 71.6), gap_relink=flag)


def _helices(moves):
    """descent runs of >= 4 descending feed moves right after a G0"""
    n, i = 0, 1
    while i < len(moves):
        if moves[i - 1]["g"] == 0 and moves[i]["g"] == 1 and \
                moves[i]["z"] < moves[i - 1]["z"] - 1e-6:
            j = i
            while j + 1 < len(moves) and moves[j + 1]["g"] == 1 and \
                    moves[j + 1]["z"] < moves[j]["z"] - 1e-6:
                j += 1
            n += (j - i + 1) >= 4
            i = j + 1
        else:
            i += 1
    return n


def test_gr_wiring_two_pocket():
    """(g) wiring: on the two-pocket scene GR relinks through the link
    fallback site (pinned, so unwiring it turns this red); the program has
    fewer G0 moves than OFF (no more helices); every logged relink is G1
    feeds at the level Z ending on its end point at the cutting feed. The
    clip re-entry relinks here all shear some stock, so the no-shear rule
    refuses them, and the a2d LinkNotClear site does not fire: both are
    uncovered by this scene."""
    m_on, s_on = _twopock(1)
    m_off, _s = _twopock(0)
    g = s_on["gr"]
    assert g["relinked"] >= 1, g
    assert g["by_site"]["link_fallback"] >= 1, ("site not relinking", g)
    h_on, h_off = _helices(m_on), _helices(m_off)
    g0_on = sum(1 for mv in m_on if mv["g"] == 0)
    g0_off = sum(1 for mv in m_off if mv["g"] == 0)
    # with the no-shear rule the relinks here replace retract + traverse
    # rapids (the following re-entries are unchanged): fewer G0 moves
    assert g0_on < g0_off and h_on <= h_off, (g0_on, g0_off, h_on, h_off)
    cut = max(mv.get("f") or 0 for mv in m_on if mv["g"] == 1)
    for x0, y0, x1, y1, zl, _site in g["log"]:
        hit = [k for k, mv in enumerate(m_on)
               if mv["g"] == 1 and abs(mv["x"] - x1) < 1e-4
               and abs(mv["y"] - y1) < 1e-4 and abs(mv["z"] - zl) < 1e-6
               and mv.get("f") == cut]
        assert hit, ("relink end not emitted as a feed at Z", x1, y1, zl)
        k = hit[0]
        back = [mv for mv in m_on[max(0, k - 400):k]
                if abs(mv["x"] - x0) < 1e-4 and abs(mv["y"] - y0) < 1e-4
                and abs(mv["z"] - zl) < 1e-6]
        assert back, ("relink start not at depth before its end", x0, y0, zl)
    print("PASS gr wiring: %d relinks %s, G0 %d vs %d, helices %d vs %d, %d "
          "logged relinks are G1 feeds at Z" % (g["relinked"], g["by_site"],
                                                g0_on, g0_off, h_on, h_off,
                                                len(g["log"])))


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
    test_gr_wiring_two_pocket()
