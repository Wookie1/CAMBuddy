"""M2: an SK1 air column / feed-in is used only if the tool's holder clears:
the holder nose (tip z + stick-out) stays 1 mm above the live stock within
the holder's radius + 1 mm along the descent and the whole feed-in. Unknown
holder or stick-out -> no side entry (fail closed). Runnable directly or
under pytest from VibeCAD python."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)
from engine import rough as roughmod  # noqa: E402
from engine.stock import StockField  # noqa: E402
from engine import test_sk1 as S  # noqa: E402

BOX = (0.0, 40.0, 0.0, 20.0, 0.0, 30.0)     # stock standing to Z 30


def _path(x0, x1, y=10.0):
    return [(x0 - (x0 - x1) * t / 8.0, y) for t in range(9)]


def test_m2_a_holder_limits_the_descent():
    """(a) a column 20 mm outside the +X face, feeding in to 10 mm outside
    it, at Z 10: a radius-27 holder at 15 mm stick-out sees the Z 30 stock
    (refused); the same holder clears at Z 20; a radius-5 holder sees no
    stock from there (the radius matters)."""
    sf = StockField(BOX, cell=0.5)
    pts = _path(60.0, 50.0)
    assert not roughmod.holder_clears(sf, pts, 10.0, 27.0, 15.0)
    assert roughmod.holder_clears(sf, pts, 20.0, 27.0, 15.0)
    assert roughmod.holder_clears(sf, pts, 10.0, 5.0, 15.0)
    print("PASS m2_a: refused at Z10, clears at Z20, radius matters")


def _sk1(holder):
    _m, st = S._synth_rough(side_entry_faces=S.ALL_FACES, flute_mm=S.FLUTE,
                            side_entry_holder=holder)
    return st


def test_m2_c_real_stickout_decides():
    """(c) the same holder at a short stick-out keeps fewer side entries
    than at a long one, every kept feed-in clears, and the skins it drops
    say why."""
    short, long_ = (27.0, 12.0), (27.0, 71.6)
    st_s, st_l = _sk1(short), _sk1(long_)
    n_s = len(st_s.get("sk1_feedin") or [])
    n_l = len(st_l.get("sk1_feedin") or [])
    assert n_l > 0 and n_s < n_l, (n_s, n_l)
    assert st_s["n_axial_plunge"] == 0 and st_l["n_axial_plunge"] == 0
    assert any(k.get("reason") == "holder would hit stock"
               for k in st_s["skin_skipped"]), st_s["skin_skipped"]
    print("PASS m2_c: stick-out 12 -> %d feed-ins, 71.6 -> %d" % (n_s, n_l))


def test_m2_d_unknown_holder_no_side_entry():
    """(d) no holder/stick-out known: no air column at all (fail closed);
    the ring skins are left standing with their warning, 0 plunges."""
    st = _sk1(None)
    assert not st.get("sk1_feedin"), st["sk1_feedin"][:3]
    assert st["n_axial_plunge"] == 0
    assert st["skin_skipped"]
    print("PASS m2_d: unknown holder -> 0 feed-ins, %d skins left"
          % len(st["skin_skipped"]))


if __name__ == "__main__":
    test_m2_a_holder_limits_the_descent()
    test_m2_c_real_stickout_decides()
    test_m2_d_unknown_holder_no_side_entry()
    print("PASS test_m2_holder")
