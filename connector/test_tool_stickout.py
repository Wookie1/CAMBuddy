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
import runner as runner_mod  # noqa: E402
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


# ------------------------------- library fills the repo table's nulls ----

def test_precheck_and_geometry_pass_after_update(conn):
    """T3's repo row has holder/stickout null: the library may fill them
    (the engine and judges read the run's effective table), so T3 now
    reaches the engine. Before: tool_geometry_mismatch on holder."""
    c, mock, home, spawns = conn
    rep = _run(c, mock, 9401, **T3_RUN)
    assert rep["error"]["code"] == "tool_holder_missing" and not spawns
    c.tool_action(catalog_mod.TOOLS_UPDATE,
                  {"tool_id": T3, "changes": dict(FIX)})
    rep = _run(c, mock, 9402, **T3_RUN)
    print("TOOL-STICKOUT: T3 after update -> %r, engine spawns %d"
          % (rep["error"]["code"], len(spawns)))
    assert rep["error"]["code"] not in ("tool_holder_missing",
                                        "tool_geometry_mismatch"), rep["error"]
    assert len(spawns) >= 1, rep["error"]   # reached the engine


def test_holder_differing_from_repo_still_refused(conn):
    """T13's repo holder is BT30-ER32-70: a different library holder is a
    real difference and stays refused."""
    c, mock, home, spawns = conn
    c.tool_action(catalog_mod.TOOLS_UPDATE,
                  {"tool_id": "flat-12.686",
                   "changes": {"holder": "BT30-ER20-60"}})
    err = _run(c, mock, 9403)["error"]
    assert err["code"] == "tool_geometry_mismatch" and not spawns
    assert (err["field"], err["got"], err["allowed"]) == \
        ("holder", "BT30-ER20-60", "BT30-ER32-70")
    assert err["message"] == (
        "tool flat-12.686: the library has holder 'BT30-ER20-60' but the "
        "repo tool table tools/x7_tools.json has 'BT30-ER32-70'")


def test_diameter_differing_from_repo_still_refused(conn):
    """Only holder/stickout_mm may fill a null; geometry differences stay
    refused (here T3 also gets a holder + stick-out, so only dia differs)."""
    c, mock, home, spawns = conn
    c.tool_action(catalog_mod.TOOLS_UPDATE,
                  {"tool_id": T3, "changes": dict(FIX, dia_mm=12.0)})
    err = _run(c, mock, 9404, **dict(T3_RUN, tool_diameter=12.0))["error"]
    assert err["code"] == "tool_geometry_mismatch" and not spawns, err
    assert (err["field"], err["got"], err["allowed"]) == \
        ("diameter_mm", 12.0, 12.7)


@pytest.mark.parametrize("key", ["flute_mm", "diameter_mm"])
def test_library_may_not_fill_a_null_geometry_field(tmp_path, key):
    """The fill is limited to holder/stickout_mm: a repo row with a null
    geometry field (synthetic repo table) and a library value for it stay
    refused. Catches a fill-any-null check, which today's repo table (no
    null geometry) cannot."""
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    table = toollib._read(toollib.repo_table_path(REPO))
    lib_value = next(t for t in table["tools"]
                     if t["tool_id"] == T3)[key]
    home = tmp_path / "home"
    home.mkdir()
    toollib.write_json(str(home / "tools.json"), table)   # library: filled
    next(t for t in table["tools"] if t["tool_id"] == T3)[key] = None
    toollib.write_json(toollib.repo_table_path(str(repo)), table)
    eng = runner_mod.EngineRun({"home": str(home), "repo_root": str(repo)},
                               str(tmp_path))
    eng._load_tools({})
    with pytest.raises(runner_mod.EngineError) as e:
        eng._check_library_geometry([3])
    err = e.value.as_error()
    assert (err["code"], err["field"], err["got"], err.get("allowed")) == \
        ("tool_geometry_mismatch", key, lib_value, None)
