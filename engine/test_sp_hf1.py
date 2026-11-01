"""SP-HF1: engine.cli prepare builds its part heightfield over the STOCK box
plus --tool-r (+ heightfield.py's 5 mm margin), not just the part bbox, and
its sidecar records the real extent. Checked the way the rough consumes it:
StockField.set_part_from_other_grid (out-of-grid cells clamp to the grid's
edge) must see AIR (the part zmin floor) in the stock margin, never a copied
edge height. Runs the real prepare (freecadcmd) on synth_pocket (outer walls at full
height, so a copied edge cell is measurably NOT air); runnable
directly or under pytest from any python with VibeCAD installed."""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402
from engine.stock import StockField  # noqa: E402

TOOL_R = 6.343
MARGIN_MM = 8.0          # stock margin around the test block (each side)


def _prepare(td):
    r = subprocess.run(
        [model.python311(), "-m", "engine.cli", "prepare",
         "--step", os.path.join(ROOT, "connector", "testdata", "synth_pocket.step"),
         "--out-dir", td, "--stock-xy", str(MARGIN_MM), "--stock-top", "1",
         "--stock-bottom", "0", "--cell", "0.5", "--tool-r", str(TOOL_R)],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    with open(os.path.join(td, "prepare.json")) as fh:
        return json.load(fh)


def test_sp_hf1_prepare_hf_covers_stock_margin():
    if not os.path.exists(model.freecadcmd()):
        import pytest
        pytest.skip("VibeCAD freecadcmd missing")
    with tempfile.TemporaryDirectory() as td:
        prep = _prepare(td)
        stock, bbox = prep["stock"], prep["bbox"]
        part = np.load(prep["hf"])
        with open(prep["hf"][:-4] + ".json") as fh:
            meta = json.load(fh)
        x0, y0, cell = meta["x0"], meta["y0"], meta["cell"]
        ny, nx = part.shape
        # the rough's view: a cell in each stock margin strip (inside the
        # stock, outside the part bbox) is air, not a copied edge height
        sf = StockField(tuple(stock), cell=0.5)
        sf.set_part_from_other_grid(part, x0, y0, cell)
        zfloor = float(np.nanmin(part))
        top = float(np.nanmax(part))
        bad = []
        for (x, y) in ((stock[0] + 1.0, 0.0), (stock[1] - 1.0, 0.0),
                       (0.0, stock[2] + 1.0), (0.0, stock[3] - 1.0)):
            assert not (bbox[0] <= x <= bbox[1] and bbox[2] <= y <= bbox[3])
            i = int((x - sf.x0) / sf.cell)
            j = int((y - sf.y0) / sf.cell)
            v = float(sf.part[j, i])
            if v > zfloor + 1e-6:
                bad.append(((x, y), round(v, 4)))
        assert not bad, ("stock-margin cells read as part (copied edge "
                         "height, part top %.3f): %s" % (top, bad))
        # the grid covers stock + tool radius on every side
        assert x0 <= stock[0] - TOOL_R + 1e-9 and y0 <= stock[2] - TOOL_R + 1e-9
        assert x0 + nx * cell >= stock[1] + TOOL_R - 1e-9
        assert y0 + ny * cell >= stock[3] + TOOL_R - 1e-9
        # the sidecar records the real extent
        assert (meta["nx"], meta["ny"]) == (nx, ny)
        assert meta["stock_box"] == [round(v, 6) for v in stock[:4]] or \
            np.allclose(meta["stock_box"], stock[:4], atol=1e-6)
        assert abs(meta["tool_r"] - TOOL_R) < 1e-9
    print("PASS sp_hf1: hf covers stock+R (x0 %.3f y0 %.3f %dx%d), sidecar "
          "tool_r %.3f, margin cells are air" % (x0, y0, nx, ny,
                                                  meta["tool_r"]))


if __name__ == "__main__":
    test_sp_hf1_prepare_hf_covers_stock_margin()
