"""FL-LOAD connector route (coordinator): the rough limiter is ON by default in
BOTH cutting actions. adaptive_rough's explicit load_limit input wins; else
the document's job.setup load_limit; else ON. slope_split_finish has no
input of its own (30-input cap) and follows job.setup, else ON.

Unit test: the runner's subprocesses are faked (test_toollib._fake_spawn).
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_flload_conn.py
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
import test_toollib as tl  # noqa: E402
import toollib  # noqa: E402

PY = "/opt/homebrew/bin/python3"
DOC = "doc-flload"
ADAPT = {"orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
         "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
         "tool_diameter": 12.686, "corner_radius": 0.0,
         "flute_length": 50.8, "stepdown": 4.0, "optimal_load": 2.0,
         "stock_to_leave": 0.381, "rest_stepup": 1.905, "rpm": 7500,
         "feed": 3429.0, "ramp_feed": 1270.0, "units": "mm",
         "program_number": 1001}


def _rough_argv(home, tmp_path, monkeypatch, action, values):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    run = runner_mod.EngineRun(cfg, str(tmp_path / ("r-" + action)))
    step = os.path.join(HERE, "testdata", "synth_pocket.step")
    if action == "adaptive":
        run.run(step, values)
    else:
        run.run_slope_split_finish(step, values)
    return [a for a in calls if "engine.cli" in a
            and a[a.index("engine.cli") + 1] == "rough"][0]


def _state(argv):
    return ("--load-limit" in argv, "--no-load-limit" in argv)


@pytest.mark.parametrize("action", ["adaptive", "slope"])
def test_flload_route_default_on(tl_home, tmp_path, monkeypatch, action):
    vals = dict(ADAPT if action == "adaptive" else tl.SLOPE)
    argv = _rough_argv(tl_home, tmp_path, monkeypatch, action, vals)
    assert _state(argv) == (True, False), \
        "%s rough by default: --load-limit present %s, --no-load-limit " \
        "present %s (want on)" % ((action,) + _state(argv))


@pytest.mark.parametrize("action", ["adaptive", "slope"])
def test_flload_route_job_setup_false(tl_home, tmp_path, monkeypatch, action):
    toollib.set_setup(tl_home, DOC, {"load_limit": False})
    vals = dict(ADAPT if action == "adaptive" else tl.SLOPE, document_id=DOC)
    argv = _rough_argv(tl_home, tmp_path, monkeypatch, action, vals)
    assert _state(argv) == (False, True), \
        "%s rough with job.setup load_limit false: --load-limit present %s, " \
        "--no-load-limit present %s (want off)" % ((action,) + _state(argv))


def test_flload_route_adaptive_explicit_false_wins(tl_home, tmp_path,
                                                   monkeypatch):
    toollib.set_setup(tl_home, DOC, {"load_limit": True})
    vals = dict(ADAPT, document_id=DOC, load_limit=False)
    argv = _rough_argv(tl_home, tmp_path, monkeypatch, "adaptive", vals)
    assert _state(argv) == (False, True), \
        "adaptive explicit load_limit false (job.setup true): --load-limit " \
        "present %s, --no-load-limit present %s (want off)" % _state(argv)


def test_flload_setup_rejects_non_boolean(tl_home):
    with pytest.raises(toollib.ToolLibError):
        toollib.set_setup(tl_home, DOC, {"load_limit": "yes"})


@pytest.fixture
def tl_home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return str(h)
