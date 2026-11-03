"""LVA call site (panel follow-up, mutant ML): helix_entry passes rough()'s
own rapid_margin to _lva_start - never a literal - so the start height keeps
the same margin R5 and every link use. Spied on the BS1d scene with a
distinctive rapid_margin (1.5): every call must carry 1.5. Runnable directly or under pytest from VibeCAD python."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)


def test_lva_call_site_passes_rapid_margin():
    from opencamlib import ocl
    from engine import rough as rmod
    from engine.test_engine import _box_tris as bt, _write_stl
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    seen, orig = [], rmod._lva_start

    def spy(stock, cx, cy, r, s, z, tool_r, margin, holder):
        seen.append(margin)
        return orig(stock, cx, cy, r, s, z, tool_r, margin, holder)
    rmod._lva_start = spy
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "lva_cs.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            _m, st = rmod.rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0),
                                6.343, 0.0, leave=0.381, axial_leave=0.381,
                                stepdown=19.05, stepup=1.905, tolerance=0.05,
                                threads=4, stock_cell=0.5, min_rest=0.5,
                                corner_r=0.0, stl_path=stl, rapid_margin=1.5,
                                side_entry_holder=(25.0, 71.6))
    finally:
        rmod._lva_start = orig
    assert seen, "_lva_start never called"
    assert set(seen) == {1.5}, sorted(set(seen))
    print("PASS lva call site: %d calls, margin %r, g0 %d"
          % (len(seen), sorted(set(seen)), st["lva"]["g0"]))


if __name__ == "__main__":
    test_lva_call_site_passes_rapid_margin()
