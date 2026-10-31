"""SP-HF1b: engine.cli prepare builds the ENGINE's part grid with an explicit
5 mm margin (stock + --tool-r + 5, the 8569fdc grid), independent of
heightfield.py's larger judge default (max(5, tool_r)): a different grid
re-aligns the cells the rough plans on. Everything the rough tracks past
that grid (StockField reaches 8 mm + one cell past the stock, where SK1
columns may sit) clamps to the grid's edge row, which is air. Runs the
real prepare (freecadcmd) on synth_pocket; runnable directly or under
pytest from VibeCAD python."""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "verify"))
from engine import model  # noqa: E402
from engine.stock import StockField  # noqa: E402
from hf_extent import grid_extent  # noqa: E402

STOCK_XY = 8.0


def _prepare(td, tool_r):
    r = subprocess.run(
        [model.python311(), "-m", "engine.cli", "prepare",
         "--step", os.path.join(ROOT, "connector", "testdata",
                                "synth_pocket.step"),
         "--out-dir", td, "--stock-xy", str(STOCK_XY), "--stock-top", "1",
         "--stock-bottom", "0", "--cell", "0.5", "--tool-r", str(tool_r)],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    with open(os.path.join(td, "prepare.json")) as fh:
        return json.load(fh)


def test_sp_hf1b_engine_grid_is_stock_plus_r_plus_5():
    if not os.path.exists(model.freecadcmd()):
        import pytest
        pytest.skip("VibeCAD freecadcmd missing")
    for tool_r in (6.343, 3.175):
        with tempfile.TemporaryDirectory() as td:
            prep = _prepare(td, tool_r)
            part = np.load(prep["hf"])
            with open(prep["hf"][:-4] + ".json") as fh:
                meta = json.load(fh)
            ext = grid_extent(prep["bbox"][:4], stock_box=prep["stock"][:4],
                              tool_r=tool_r, margin=5.0, cell=0.5)
            assert meta["margin"] == 5.0, meta["margin"]
            assert (meta["nx"], meta["ny"]) == (ext["nx"], ext["ny"]), \
                (tool_r, meta["nx"], meta["ny"], ext["nx"], ext["ny"])
            assert abs(meta["x0"] - ext["x0"]) < 1e-9
            # the rough's view past the stock, out to everything it tracks
            # (SK1 columns included): air, never a copied part height
            stock = prep["stock"]
            sf = StockField(tuple(stock), cell=0.5)
            sf.set_part_from_other_grid(part, meta["x0"], meta["y0"],
                                        meta["cell"])
            zfloor = float(np.nanmin(part))
            outside = ~sf.inb
            assert np.all(sf.part[outside] <= zfloor + 1e-9), \
                (tool_r, float(sf.part[outside].max()), zfloor)
            gx1 = meta["x0"] + meta["nx"] * meta["cell"]
            reach = (sf.x0 + sf.nx * sf.cell) - stock[1]
            print("PASS sp_hf1b R %.3f: grid %dx%d (margin 5), engine "
                  "tracks %.2f past the stock (grid edge %.2f past it): "
                  "all air" % (tool_r, meta["nx"], meta["ny"], reach,
                               gx1 - stock[1]))


if __name__ == "__main__":
    test_sp_hf1b_engine_grid_is_stock_plus_r_plus_5()
