"""TOOL-STICKOUT: tools.update sets a library tool's stickout_mm, so a tool
with no holder (James's T3, 12.7 mm bull r0.127) can be given the holder +
stick-out pair that zmap's holder check (resolve_holder) and HOLDER-PRECHECK
need. Before: tools.update had no stick-out field (reach_mm is a different
length and is not read by the holder check), so T3 could never pass.

    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_tool_stickout.py
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "verify"))

import catalog as catalog_mod  # noqa: E402
import connector as connector_mod  # noqa: E402
import toollib  # noqa: E402
import zmap  # noqa: E402
from test_holder_precheck import RUN_INPUTS, _run, conn  # noqa: E402,F401

T3 = "bull-12.700-r0.127"
FIX = {"holder": "BT30-ER32-70", "stickout_mm": 34.925}   # 1.375 in
T3_RUN = {"tool_type": "bull", "tool_diameter": 12.7, "corner_radius": 0.127,
          "tool_number": 3}


def _holder_of(home, number):
    """zmap's own holder resolution over the table a run hands it."""
    path = os.path.join(home, "effective.json")
    with open(path, "w") as fh:
        json.dump(toollib.effective_table(home, REPO), fh)
    return zmap.resolve_holder(tool_number=number, path=path)


def test_update_sets_stickout_and_zmap_accepts_the_tool(conn):
    c, mock, home, spawns = conn
    home = str(home)
    assert _holder_of(home, 3) is None   # as shipped: no holder, no stick-out
    upd = c.tool_action(catalog_mod.TOOLS_UPDATE,
                        {"tool_id": T3, "changes": dict(FIX)})
    assert upd["tool"]["stickout_mm"] == 34.925
    assert upd["tool"]["holder"] == "BT30-ER32-70"
    listed = c.tool_action(catalog_mod.TOOLS_LIST, {})["tools"]
    assert next(t for t in listed if t["tool_id"] == T3)["stickout_mm"] \
        == 34.925
    got = _holder_of(home, 3)
    print("TOOL-STICKOUT: resolve_holder(T3) after update = %r"
          % (got and got[1:],))
    assert got is not None and got[1:] == (34.925, "BT30-ER32-70")


@pytest.mark.parametrize("bad", [0, -1, "35"])
def test_bad_stickout_refused(conn, bad):
    c, mock, home, spawns = conn
    with pytest.raises(toollib.ToolLibError) as e:
        c.tool_action(catalog_mod.TOOLS_UPDATE,
                      {"tool_id": T3, "changes": {"stickout_mm": bad}})
    assert e.value.code == "invalid_field"
    assert e.value.detail["field"] == "stickout_mm"
