"""HOLDER-PRECHECK: a rough/slope run whose tool has no holder or stick-out
in the effective tool library fails at once with tool_holder_missing - no
engine process is started (before: the whole rough ran, then zmap's gate
failed it as 'holder unknown').

Fast: in-process Connector against the local MockSteve; the STEP download and
EngineRun._spawn are faked (the spawn counts calls and stops the run).
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_holder_precheck.py
"""
import hashlib
import json
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import connector as connector_mod  # noqa: E402
import runner as runner_mod  # noqa: E402
from mock_steve import MockSteve  # noqa: E402

FAKE_STEP = b"ISO-10303-21;\nEND-ISO-10303-21;\n"
RUN_INPUTS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
    "tool_diameter": 12.686, "corner_radius": 0.0, "flute_length": 50.8,
    "stepdown": 4.0, "optimal_load": 2.0, "stock_to_leave": 0.381,
    "rest_stepup": 1.905, "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 13, "units": "mm", "program_number": 1001,
    "model": {
        "kind": "file", "format": "step", "name": "fake.step",
        "sha256": hashlib.sha256(FAKE_STEP).hexdigest(),
        "bytes": len(FAKE_STEP),
        "url": "http://127.0.0.1:9/fake.step", "headers": {},
        "document": {"id": "doc-hp"}, "revision": 1,
    },
}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    mock = MockSteve(code="PAIR-1234")
    base = mock.serve_forever()
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "config.toml", "w") as fh:
        fh.write('base_url = "%s"\npairing_code = "PAIR-1234"\n'
                 'repo_root = "%s"\n' % (base, REPO))
    shutil.copy(os.path.join(REPO, "tools", "x7_tools.json"),
                home / "tools.json")
    mock.confirm()
    c = connector_mod.Connector(str(home))
    c.enroll()
    c.get_token_blocking()
    monkeypatch.setattr(c.client, "download",
                        lambda url, headers=None: FAKE_STEP)
    spawns = []

    def fake_spawn(self, argv, *a, **kw):
        spawns.append(argv)
        raise runner_mod.EngineError("stopped by test after spawn",
                                     code="engine_failed")
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake_spawn)
    yield c, mock, home, spawns
    mock.stop()


def _run(c, mock, run_id, **over):
    inputs = json.loads(json.dumps(RUN_INPUTS))
    inputs.update(over)
    mock.enqueue_run(run_id, action="adaptive_rough", inputs=inputs)
    c.handle_message(mock.messages[-1])
    assert mock.wait_terminal(run_id, timeout=20) == "failed"
    with mock.lock:
        reps = [r["body"] for r in mock.reports
                if str(r["run_id"]) == str(run_id)]
    return reps[-1]


def test_tool_without_holder_fails_before_any_engine_spawn(conn):
    """James's case: T3 (12.7 mm bull r0.127) has no holder or stick-out in
    the repo table, so his library copy has none either (the geometry check
    passes: both agree). Before HOLDER-PRECHECK the rough ran in full."""
    c, mock, home, spawns = conn
    rep = _run(c, mock, 9301, tool_type="bull", tool_diameter=12.7,
               corner_radius=0.127, tool_number=3)
    print("HOLDER-PRECHECK: engine spawns before failing = %d, error %r"
          % (len(spawns), rep.get("error", {}).get("code")))
    assert len(spawns) == 0, "engine started %d step(s) for a tool with no " \
        "holder" % len(spawns)
    err = rep["error"]
    assert err["code"] == "tool_holder_missing"
    assert err["message"] == (
        "T3 (12.7 mm bull) has no holder or stick-out in your tool library. "
        "Add them in the panel's tool library, then run again.")


def test_complete_tool_still_reaches_the_engine(conn):
    c, mock, home, spawns = conn
    rep = _run(c, mock, 9302)
    assert len(spawns) >= 1, "a tool with holder + stick-out never ran"
    assert rep["error"]["code"] != "tool_holder_missing"


def test_slope_rough_tool_without_holder_is_refused(conn):
    """slope_split_finish: its rough tool goes through the same check."""
    c, mock, home, spawns = conn
    ok, code, values = connector_mod.prepare_values({
        "model": RUN_INPUTS["model"], "units": "mm",
        "rough_tool_type": "bull", "rough_tool_diameter": 12.7,
        "rough_corner_radius": 0.127, "tool_diameter": 6.0},
        connector_mod.catalog_mod.SLOPE_ACTION)
    assert ok, (code, values)
    with pytest.raises(runner_mod.EngineError) as e:
        connector_mod.precheck_holders(c.cfg, connector_mod.catalog_mod.SLOPE_ACTION,
                                       values)
    assert e.value.code == "tool_holder_missing"
    assert str(e.value).startswith("T3 (12.7 mm bull)")
