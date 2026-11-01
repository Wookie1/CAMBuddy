"""M1b: the vise-height guard checks every straight move along its whole
length below the part bottom, not just its end points: a diagonal move that
leaves the stock XY while already below min_z fails even when both of its
ends pass on their own. Runnable directly or under pytest from VibeCAD
python."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)
from engine import rough as roughmod  # noqa: E402

BOX = (-21.0, 21.0, -11.0, 11.0, -10.0, 0.4)
R, ZMIN = 6.343, -10.0
EDGE = 21.0 - R          # largest centre X with the footprint inside


def _check(moves):
    st = {}
    try:
        roughmod.vise_height_guard(moves, BOX, R, ZMIN, st)
    except RuntimeError as e:
        return str(e)
    return None


def test_m1b_crossing_segment_fails():
    """Outside the stock above the part bottom -> inside the stock below
    it, crossing min_z while still outside: both ends pass alone, the
    move does not."""
    moves = [{"g": 0, "x": 30.0, "y": 0.0, "z": -5.0},     # outside, above
             {"g": 1, "x": 10.0, "y": 0.0, "z": -15.0}]    # inside, below
    # the move crosses Z-10 at x = 20 > EDGE: outside the stock below min_z
    msg = _check(moves)
    assert msg and msg.startswith("rough vise-height guard FAILED: 1 move(s)"), msg
    assert "move 1 G1" in msg, msg
    print("PASS m1b crossing: %s" % msg)


def test_m1b_legit_moves_pass():
    """Descending outside but reaching min_z only after entering the
    stock, and a move wholly inside below min_z, both pass."""
    moves = [{"g": 0, "x": 30.0, "y": 0.0, "z": -5.0},
             {"g": 1, "x": EDGE - 1.0, "y": 0.0, "z": -9.0},   # above, enters
             {"g": 1, "x": 0.0, "y": 0.0, "z": -15.0},          # crosses inside
             {"g": 1, "x": -EDGE, "y": 5.0 - R, "z": -15.0}]    # inside, below
    assert _check(moves) is None
    print("PASS m1b legit: entering above min_z then descending inside passes")


if __name__ == "__main__":
    test_m1b_crossing_segment_fails()
    test_m1b_legit_moves_pass()
    print("PASS test_m1b_vise_segment")
