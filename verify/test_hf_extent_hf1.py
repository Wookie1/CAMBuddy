"""HF1: the judge grid holds the whole footprint of every centre the engine
can legally emit. Engine centres may pass a stock face by up to tool_r, so a
footprint centred at stock edge + tool_r must lie inside the grid that
heightfield.py builds from its default margin (no MARGIN / --margin given)."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("FreeCAD", types.ModuleType("FreeCAD"))
sys.modules.setdefault("Part", types.ModuleType("Part"))
import heightfield  # noqa: E402
from hf_extent import grid_extent  # noqa: E402


def _default_margin(monkeypatch, tool_r):
    monkeypatch.delenv("MARGIN", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "heightfield.py", "in.step", "out.npy", "0.5",
        "--stock-box", "-20", "20", "-15", "15", "--tool-r", str(tool_r)])
    step, out, cell, pad, stock, tr, mg = heightfield.get_args()
    return cell, pad, stock, tr, heightfield.judge_margin(mg, tr)


def test_hf1_footprint_at_stock_edge_plus_r_fits(monkeypatch):
    for tool_r in (6.343, 9.525, 12.7):
        cell, pad, stock, tr, margin = _default_margin(monkeypatch,
                                                             tool_r)
        g = grid_extent((-10.0, 8.0, -6.0, 5.0), stock_box=stock, tool_r=tr,
                        margin=margin, pad=pad, cell=cell)["grid_bounds"]
        # centre at stock edge + tool_r; footprint reaches one more tool_r
        reach = 2.0 * tool_r
        assert g[0] <= stock[0] - reach and g[1] >= stock[1] + reach, \
            (tool_r, margin, g)
        assert g[2] <= stock[2] - reach and g[3] >= stock[3] + reach, \
            (tool_r, margin, g)


def test_hf1_explicit_margin_keeps_meaning(monkeypatch):
    monkeypatch.setenv("MARGIN", "5")
    monkeypatch.setattr(sys, "argv", [
        "heightfield.py", "in.step", "out.npy", "0.5", "--tool-r", "12.7"])
    assert heightfield.judge_margin(heightfield.get_args()[-1], 12.7) == 5.0
    monkeypatch.delenv("MARGIN")
    monkeypatch.setattr(sys, "argv", [
        "heightfield.py", "in.step", "out.npy", "--margin", "3",
        "--tool-r", "12.7"])
    assert heightfield.judge_margin(heightfield.get_args()[-1], 12.7) == 3.0
