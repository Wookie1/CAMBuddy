"""SP-P3E: the rough CLI's Adaptive2d tolerance default is
ROUGH_A2D_TOLERANCE (0.1), and an explicit --tolerance 0.05 still
reproduces the old default on the test block (byte-identical program to a
run whose default is 0.05). Runs in-process with VibeCAD python; also
pytest-compatible under any python that can import `area`."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model, cli  # noqa: E402,F401  (model: VibeCAD lib path)
from engine import rough as R  # noqa: E402

TB = ["rough", "--step", os.path.join(ROOT, "samples", "test_block.step"),
      "--stock", "-50", "50", "-40", "40", "0", "38", "--tool", "flat:12.686",
      "--floor", "20", "--leave", "0.381", "--final-zmin", "20.381",
      "--stepdown", "19.05", "--optimal-load-mm", "2.032"]


class _Seen(Exception):
    pass


def test_sp_p3e_default_is_0p1():
    assert cli.ROUGH_A2D_TOLERANCE == 0.1
    seen = {}
    orig = R.rough

    def spy(*a, **k):
        seen["tolerance"] = k.get("tolerance")
        raise _Seen()
    R.rough = spy
    try:
        with tempfile.TemporaryDirectory() as td:
            cli.main(TB + ["--out", os.path.join(td, "x.nc")])
    except _Seen:
        pass
    finally:
        R.rough = orig
    assert seen.get("tolerance") == 0.1, seen
    print("PASS sp_p3e: CLI default tolerance reaches rough() as 0.1")


def test_sp_p3e_explicit_0p05_is_old_default():
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "explicit.nc"), os.path.join(td, "old.nc")
        cli.main(TB + ["--tolerance", "0.05", "--out", a])
        old = cli.ROUGH_A2D_TOLERANCE
        cli.ROUGH_A2D_TOLERANCE = 0.05      # the pre-SP-P3E default
        try:
            cli.main(TB + ["--out", b])
        finally:
            cli.ROUGH_A2D_TOLERANCE = old
        with open(a, "rb") as fa, open(b, "rb") as fb:
            assert fa.read() == fb.read(), \
                "explicit --tolerance 0.05 differs from the 0.05 default"
    print("PASS sp_p3e: explicit --tolerance 0.05 == old 0.05 default (TB)")


if __name__ == "__main__":
    test_sp_p3e_default_is_0p1()
    test_sp_p3e_explicit_0p05_is_old_default()
