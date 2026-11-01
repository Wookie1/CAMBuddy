"""SP4-DIAG: the BS1d StartPointNotFound diagnostic (per-outer "alone"
re-runs that only fill stats["a2d_dropped_outers"]) runs in a spawn pool;
the result must equal the serial path exactly - same a2d_spnf, same dropped
outers in the same order, same program. Uses test_bs1d_a2d_drop_counted's
scene (one fully StartPointNotFound outer). Runnable directly or under
pytest from VibeCAD python."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)
from engine.gcode import moves_to_gcode  # noqa: E402
from engine.test_engine import _box_tris, _write_stl  # noqa: E402


def _run(serial):
    from opencamlib import ocl
    from engine.rough import rough
    bt = _box_tris
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    old = os.environ.pop("STEVECAM_NO_A2D_DIAG_POOL", None)
    if serial:
        os.environ["STEVECAM_NO_A2D_DIAG_POOL"] = "1"
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1d_drop.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            moves, stats = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0),
                                 6.343, 0.0, leave=0.381, axial_leave=0.381,
                                 stepdown=19.05, stepup=1.905, tolerance=0.05,
                                 threads=4, stock_cell=0.5, min_rest=0.5,
                                 corner_r=0.0, stl_path=stl)
    finally:
        os.environ.pop("STEVECAM_NO_A2D_DIAG_POOL", None)
        if old is not None:
            os.environ["STEVECAM_NO_A2D_DIAG_POOL"] = old
    return moves, stats


def test_sp4_diag_pool_equals_serial():
    m_p, s_p = _run(serial=False)
    m_s, s_s = _run(serial=True)
    assert s_p["a2d_spnf"] == s_s["a2d_spnf"] >= 1, \
        (s_p["a2d_spnf"], s_s["a2d_spnf"])
    assert s_p["a2d_dropped_outers"] == s_s["a2d_dropped_outers"], \
        (s_p["a2d_dropped_outers"], s_s["a2d_dropped_outers"])
    assert len(s_p["a2d_dropped_outers"]) == 1, s_p["a2d_dropped_outers"]
    assert moves_to_gcode(m_p) == moves_to_gcode(m_s)
    print("PASS sp4_diag: pooled == serial (spnf %d, %d dropped outer, "
          "%d moves)" % (s_p["a2d_spnf"], len(s_p["a2d_dropped_outers"]),
                         len(m_p)))


if __name__ == "__main__":
    test_sp4_diag_pool_equals_serial()
