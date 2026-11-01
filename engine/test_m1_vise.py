"""M1 vise-height guard: with side entry on, no move (G0/G1, cutting, link,
entry) may have its tool footprint outside the stock XY below the part
bottom (side_entry_min_z) - the run fails, nothing is clamped or dropped.
(a) the real box scenes of test_sk1_height (floor at / below the part
bottom) scan every move with 0 offenders; (b) an injected move outside the
stock below the part bottom fails with the guard's message. Runnable
directly or under pytest from VibeCAD python."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)
from engine import rough as roughmod  # noqa: E402
from engine import test_sk1_height as H  # noqa: E402


def test_m1_a_box_scenes_zero_offenders():
    """(a) every move of the b (floor at the part bottom, skins cut by side
    entry) and c (floor 3 mm below it) scenes is scanned: 0 offenders."""
    H._skip_if_no_freecad()
    for sb, below in ((0, False), (3, True)):
        with tempfile.TemporaryDirectory() as td:
            stats, _err, zpart, _f = H._rough(td, sb, below)
            vg = stats["vise_guard"]
            assert vg["offenders"] == 0, vg
            assert vg["checked"] == stats["n_moves"] > 0, vg
            assert abs(vg["min_z"] - zpart) < 1e-6
    print("PASS m1_a: box scenes scanned, 0 offenders")


def test_m1_b_injected_move_fails():
    """(b) legit moves pass; one move outside the stock below the part
    bottom fails the run with the guard's message."""
    box, r, zmin = (-21.0, 21.0, -11.0, 11.0, -10.0, 0.4), 6.343, -10.0
    ok = [{"g": 0, "x": 0.0, "y": 0.0, "z": 5.0},
          {"g": 1, "x": 30.0, "y": 0.0, "z": -5.0},     # outside, above
          {"g": 1, "x": 0.0, "y": 0.0, "z": -12.0},     # inside, below
          {"g": 1, "x": 21.0 - r, "y": 0.0, "z": -12.0}]  # footprint at face
    st = {}
    roughmod.vise_height_guard(ok, box, r, zmin, st)
    assert st["vise_guard"]["offenders"] == 0
    bad = ok + [{"g": 1, "x": 21.0 - r + 0.01, "y": 0.0, "z": zmin - 1.0}]
    try:
        roughmod.vise_height_guard(bad, box, r, zmin, st)
    except RuntimeError as e:
        msg = str(e)
        assert msg.startswith("rough vise-height guard FAILED: 1 move(s) "
                              "outside the stock below the part bottom"), msg
        assert "move 4 G1 X14.667" in msg, msg
    else:
        raise AssertionError("injected move outside the stock below the "
                             "part bottom did not fail")
    print("PASS m1_b: %s" % msg)


if __name__ == "__main__":
    test_m1_a_box_scenes_zero_offenders()
    test_m1_b_injected_move_fails()
    print("PASS test_m1_vise")
