"""SP4-DIAG: with ONE outer, the BS1d StartPointNotFound verdict comes from
the primary Adaptive2d run - its "alone" re-run would be the same Execute
on the same inputs. The verdict must equal an explicit alone re-run's, and
the stats must list the dropped outer as before. Uses
test_bs1d_a2d_drop_counted's scene (one fully StartPointNotFound outer).
Runnable directly or under pytest from VibeCAD python."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)
from engine import rough as R  # noqa: E402
from engine.test_engine import _box_tris, _write_stl  # noqa: E402


def test_sp4_diag_single_outer_verdict_from_primary():
    from opencamlib import ocl
    bt = _box_tris
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    seen = []
    real = R._run_a2d

    def spy(outers, holes, islands, *rest):
        out = real(outers, holes, islands, *rest)
        if len(outers) == 1:
            seen.append((outers, holes, islands, rest[:6]))
        return out

    R._run_a2d = spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1d_drop.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            _m, stats = R.rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0),
                                6.343, 0.0, leave=0.381, axial_leave=0.381,
                                stepdown=19.05, stepup=1.905, tolerance=0.05,
                                threads=4, stock_cell=0.5, min_rest=0.5,
                                corner_r=0.0, stl_path=stl)
    finally:
        R._run_a2d = real
    assert stats["a2d_spnf"] >= 1 and len(stats["a2d_dropped_outers"]) == 1, \
        (stats["a2d_spnf"], stats["a2d_dropped_outers"])
    assert seen, "no single-outer level"
    for outers, holes, islands, prm in seen:
        o = outers[0]
        primary = R._a2d_new(*prm).Execute(list(outers),
                                           list(outers) + holes + islands, [],
                                           lambda tp: False)
        alone = R._a2d_new(*prm).Execute([o], [o] + holes + islands, [],
                                         lambda tp: False)
        assert R._results_dropped(primary) == R._results_dropped(alone)
    print("PASS sp4_diag: %d single-outer level(s), primary verdict == alone "
          "re-run, %d dropped outer" % (len(seen),
                                         len(stats["a2d_dropped_outers"])))


if __name__ == "__main__":
    test_sp4_diag_single_outer_verdict_from_primary()
