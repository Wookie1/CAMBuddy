"""SK1 judge-grid parity: with side entry on, the judge heightfield the
runner asks for (verify/hf_extent.grid_extent with the runner's MARGIN)
holds the footprint of the furthest SK1 column the engine can legally use,
for every tool. A column must sit inside the engine's tracked StockField
(engine/stock.py, the rough's default stock cell) AND have its whole
footprint (tool_r + rapid margin) past the face."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "verify"))

import runner as runner_mod  # noqa: E402
from engine.stock import StockField  # noqa: E402
from hf_extent import grid_extent  # noqa: E402

RAPID_MARGIN = 1.0     # engine/rough.py rough(rapid_margin=1.0)
STOCK_CELL = 0.5       # engine/rough.py rough(stock_cell=0.5)
BOXES = [(-127.365, 127.365, -70.85, 70.85),    # James's floor-0 stock
         (-20.1, 20.33, -11.07, 11.21)]         # widths off the cell grid


@pytest.mark.parametrize("tool_r", [3.175, 6.35, 9.525, 12.7])
@pytest.mark.parametrize("box", BOXES)
def test_furthest_sk1_column_fits_judge_grid(tool_r, box):
    sf = StockField(tuple(box) + (0.0, 25.0), cell=STOCK_CELL)
    gx1, gy1 = sf.x0 + sf.nx * sf.cell, sf.y0 + sf.ny * sf.cell
    # furthest legal column centre past each face (cell index < n)
    beyond = {"xneg": box[0] - sf.x0, "xpos": gx1 - box[1],
              "yneg": box[2] - sf.y0, "ypos": gy1 - box[3]}
    prep = {"bbox": [0, 0, 0, 0, 1.0, 2.0]}
    margin = float(runner_mod._judge_margin_env(prep, tool_r)["MARGIN"])
    assert margin >= max(5.0, tool_r)          # never below the default
    g = grid_extent((box[0] + 1, box[1] - 1, box[2] + 1, box[3] - 1),
                    stock_box=box, tool_r=tool_r, margin=margin,
                    cell=0.5)["grid_bounds"]
    reach = {"xneg": box[0] - g[0], "xpos": g[1] - box[1],
             "yneg": box[2] - g[2], "ypos": g[3] - box[3]}
    for f, b in beyond.items():
        if b < tool_r + RAPID_MARGIN:
            continue            # no legal column past this face for the tool
        assert b + tool_r <= reach[f] + 1e-9, \
            (f, tool_r, "column footprint %.3f past the face, judge grid "
             "%.3f" % (b + tool_r, reach[f]))


def test_side_entry_off_no_margin():
    assert runner_mod._judge_margin_env({"stock": [0] * 6}, 6.35) == {}


class _Stop(Exception):
    pass


def test_check_program_judge_grid_holds_sk1_columns(tmp_path, monkeypatch):
    """check_program judges programs our roughs posted (with SK1 columns):
    its judge heightfield gets the same MARGIN as the rough's own judge."""
    import json
    prog = tmp_path / "p.nc"
    prog.write_text("%\nO1\nT20 M06\nG0 X0. Y0. Z10.\nM30\n%\n")
    (tmp_path / "o.step").write_text("stub")   # hashed before the hf
    seen = {}

    def fake(self, argv, lo, hi, on_progress, json_out=None, extra_env=None):
        a = list(argv)
        if "engine.cli" in a and a[a.index("engine.cli") + 1] == "prepare":
            d = a[a.index("--out-dir") + 1]
            with open(os.path.join(d, "prepare.json"), "w") as fh:
                json.dump({"step": str(tmp_path / "o.step"),
                           "hf": str(tmp_path / "hf.npy"),
                           "stock": [-10, 10, -10, 10, 0, 5],
                           "bbox": [-9, 9, -9, 9, 1.0, 4.0]}, fh)
            return None
        if any(str(t).endswith("heightfield.py") for t in a):
            seen.update(extra_env or {})
            raise _Stop()
        return None

    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
    eng = runner_mod.EngineRun({"repo_root": REPO,
                                "engine_python": sys.executable},
                               str(tmp_path / "w"))
    with pytest.raises(_Stop):
        eng.run_check_program(str(prog), str(tmp_path / "m.step"),
                              {"orientation": "as_modeled", "stock_xy": 1.0,
                               "stock_top": 1.0, "stock_bottom": 0.0}, None)
    tool_r = float(seen["TOOL_R"])
    assert float(seen["MARGIN"]) == max(5.0, tool_r,
                                        runner_mod.SK1_REACH_MM), seen
