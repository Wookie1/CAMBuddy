"""SKN: a thin stock skin (material within tool_r inside a stock face) whose
only entry is a 'wide' straight plunge is left standing with a warning
instead of failing the run; thick stock never is. Runs the real prepare
(freecadcmd) + engine.cli rough on box_off_centre (40 x 20 x 10 mm, the
connector E2E box); runnable directly or under pytest from VibeCAD python."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402
from engine import cli, rough as roughmod  # noqa: E402
from engine.stock import StockField  # noqa: E402

BOX = os.path.join(ROOT, "connector", "testdata", "box_off_centre.step")
TOOL_R = 6.343


def _rough(td, stock_xy, stock_top):
    """prepare + rough with the E2E box cutting data; returns (stats,
    stderr text) or raises the engine's RuntimeError."""
    r = subprocess.run(
        [model.python311(), "-m", "engine.cli", "prepare", "--step", BOX,
         "--out-dir", td, "--stock-xy", str(stock_xy), "--stock-top",
         str(stock_top), "--stock-bottom", "0", "--cell", "0.5",
         "--tool-r", str(TOOL_R)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    with open(os.path.join(td, "prepare.json")) as fh:
        prep = json.load(fh)
    stats_p = os.path.join(td, "stats.json")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        cli.main(["rough", "--step", prep["model"] if "model" in prep
                  else os.path.join(td, "model.step"),
                  "--stock", *["%.4f" % v for v in prep["stock"]],
                  "--tool", "flat:12.6860:0.0000",
                  "--out", os.path.join(td, "rough.nc"),
                  "--floor", "%.4f" % (prep["bbox"][4] + 3.0),
                  "--leave", "0.381", "--stepdown", "4.0",
                  "--optimal-load-mm", "2.0", "--stepup", "1.905",
                  "--hf", prep["hf"], "--min-rest", "0.5",
                  "--cut-feed", "3429", "--ramp-feed", "1270",
                  "--spindle", "7500", "--post", "lnc", "--program", "1",
                  "--tool-number", "13", "--stats-json", stats_p,
                  "--metric", "--load-limit"])
    with open(stats_p) as fh:
        return json.load(fh), err.getvalue(), prep


def _skip_if_no_freecad():
    if not os.path.exists(model.freecadcmd()):
        import pytest
        pytest.skip("VibeCAD freecadcmd missing")


def _check_skins(skins, prep):
    assert skins
    for s in skins:
        assert s["faces"] and s["area_mm2"] > 0
        assert 0 < s["max_thickness_mm"] <= TOOL_R
        assert s["z"] < prep["bbox"][5]      # side skins only


def test_skn_a_exterior_box_is_nothing_to_cut():
    """(a) stock = bbox + 1 mm: every region is a skin; no moves (the
    connector reports nothing_to_cut), each skin warned."""
    _skip_if_no_freecad()
    with tempfile.TemporaryDirectory() as td:
        stats, err, prep = _rough(td, 1.0, 0.4)
        assert stats["n_moves"] == 0, stats["n_moves"]
        _check_skins(stats["skin_skipped"], prep)
        assert err.count("WARNING: thin skin") == len(stats["skin_skipped"])
    print("PASS skn_a: %d skins, 0 moves" % len(stats["skin_skipped"]))


def test_skn_b_thick_material_is_never_a_skin():
    """(b) the thickness bound: the same region shape over a band thicker
    than tool_r is NOT a skin (None -> today's behaviour), a band within
    tool_r is."""
    box = (0.0, 40.0, 0.0, 20.0, 0.0, 10.0)
    for t, skin in ((1.0, True), (TOOL_R - 0.5, True), (8.0, False)):
        # the passes a region clearing a t-thick band along -Y plans:
        # centres from outside the face in to t - tool_r - leave
        yi = t - TOOL_R - 0.381
        res = {"paths": [("cutting", [(5.0, -4.0), (35.0, -4.0),
                                      (35.0, yi), (5.0, yi)])]}
        sf = StockField(box, cell=0.5)
        ys = sf.y0 + (np.arange(sf.ny) + 0.5) * sf.cell
        sf.top[(ys > t)[:, None] & sf.inb] = 2.0   # part side: below z
        band = roughmod._skin_band(res, sf, box, TOOL_R, 5.0)
        if skin:
            assert band is not None and "yneg" in band["faces"], (t, band)
            assert band["max_thickness_mm"] <= TOOL_R
        else:
            assert band is None, (t, band)


def test_skn_b_non_skin_still_fails_the_plunge_gate():
    """(b) end to end: when the region is judged NOT a skin, the entry is
    exactly today's - the wide plunge is counted and the run fails."""
    _skip_if_no_freecad()
    real = roughmod._skin_band
    roughmod._skin_band = lambda *a, **k: None
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                _rough(td, 1.0, 0.4)
            except RuntimeError as e:
                assert "rough axial-plunge FAILED" in str(e), e
            else:
                raise AssertionError("non-skin wide plunge did not fail")
    finally:
        roughmod._skin_band = real


def test_skn_c_mixed_cuts_real_region_skips_skin():
    """(c) 1 mm sides + 5 mm over the top: the top layer is cut, only the
    side skins are left standing (warned)."""
    _skip_if_no_freecad()
    with tempfile.TemporaryDirectory() as td:
        stats, err, prep = _rough(td, 1.0, 5.0)
        assert stats["n_moves"] > 0
        _check_skins(stats["skin_skipped"], prep)
        top = prep["bbox"][5]
        cut_above = [lv for lv in stats["levels"]
                     if lv["z"] > top and lv.get("n_regions", 0) > 0]
        assert cut_above, stats["levels"]
        assert err.count("WARNING: thin skin") == len(stats["skin_skipped"])
    print("PASS skn_c: top cut on %d level(s), %d side skins left"
          % (len(cut_above), len(stats["skin_skipped"])))


if __name__ == "__main__":
    test_skn_a_exterior_box_is_nothing_to_cut()
    test_skn_b_thick_material_is_never_a_skin()
    test_skn_b_non_skin_still_fails_the_plunge_gate()
    test_skn_c_mixed_cuts_real_region_skips_skin()
    print("PASS test_skn")
