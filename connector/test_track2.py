"""Track 2 additions (a)-(f): fast tests (runner subprocesses faked, temp
state dirs only). Engine E2E for these items live in test_connector.py.

Run: /opt/homebrew/bin/python3 -m pytest connector/test_track2.py -q
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import catalog as catalog_mod  # noqa: E402
import connector as connector_mod  # noqa: E402
import runner as runner_mod  # noqa: E402
from test_toollib import _fake_spawn  # noqa: E402

PY = "/opt/homebrew/bin/python3"
STEP = os.path.join(HERE, "testdata", "synth_pocket.step")

# inch-valued roughing inputs, units OMITTED
INCH_NO_UNITS = {
    "model": {"document": {"id": "doc-units"}}, "stock_xy": 0.04,
    "stock_top": 0.02, "stock_bottom": 0.04, "floor_z": 0.16,
    "tool_type": "flat", "tool_diameter": 1.0, "corner_radius": 0.0,
    "flute_length": 2.0, "stepdown": 0.16, "optimal_load": 0.08,
    "stock_to_leave": 0.015, "rest_stepup": 0.1, "feed": 100.0,
    "ramp_feed": 50.0, "tool_number": 13,
}


def _posted_dia_feed(values, tmp_path, monkeypatch):
    """Run adaptive_rough on fake engines; return (rough --tool diameter mm,
    --cut-feed mm/min, posts --metric?)."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    cfg = {"engine_python": PY, "repo_root": REPO}
    monkeypatch.setattr(runner_mod, "posted_units", lambda path, req: req)
    runner_mod.EngineRun(cfg, str(tmp_path)).run(STEP, values)
    r = [a for a in calls if "engine.cli" in a
         and a[a.index("engine.cli") + 1] == "rough"][0]
    return (float(r[r.index("--tool") + 1].split(":")[1]),
            float(r[r.index("--cut-feed") + 1]), "--metric" in r)


def measure_units_error(values_in, tmp_path, monkeypatch):
    """|posted - inch interpretation| for diameter (mm) and feed (mm/min)."""
    ok, code, v = connector_mod.prepare_values(values_in,
                                               catalog_mod.ACTION)
    assert ok, (code, v)
    dia, feed, metric = _posted_dia_feed(v, tmp_path, monkeypatch)
    assert v["units"] == "inch" and not metric  # posts G20
    return (abs(dia - values_in["tool_diameter"] * 25.4),
            abs(feed - values_in["feed"] * 25.4))


def test_a_omitted_units_mean_inch(tmp_path, monkeypatch):
    d_err, f_err = measure_units_error(dict(INCH_NO_UNITS), tmp_path,
                                       monkeypatch)
    assert d_err < 1e-9 and f_err < 0.05, (d_err, f_err)


def test_a_injected_fault_is_measured(tmp_path, monkeypatch):
    """Fault: the old order (defaults only after to_mm). The same
    measurement then reads the inch numbers as mm: diameter off by
    25.4 - 1.0 = 24.4 mm, feed off by 2540 - 100 = 2440 mm/min."""
    real = catalog_mod.to_mm
    monkeypatch.setattr(catalog_mod, "to_mm",
                        lambda values, action=None: real(values))
    d_err, f_err = measure_units_error(dict(INCH_NO_UNITS), tmp_path,
                                       monkeypatch)
    assert d_err == pytest.approx(24.4)
    assert f_err == pytest.approx(2440.0)


def test_a_explicit_units_unchanged():
    for units, scale in (("mm", 1.0), ("inch", 25.4)):
        out = catalog_mod.to_mm({"units": units, "feed": 100.0},
                                catalog_mod.ACTION)
        assert out["feed"] == pytest.approx(100.0 * scale)
    # check_program has no units input: nothing defaulted or converted
    out = catalog_mod.to_mm({"stock_xy": 1.0}, catalog_mod.CHECK_ACTION)
    assert out == {"stock_xy": 1.0}


# ------------------------------------------------- (b) model.measure ----

sys.path.insert(0, REPO)
from engine.cli import stock_box  # noqa: E402  (pure, no FreeCAD)


def _measure_vs_stock(bbox_for_measure, bbox, sx=1.0, sy=2.0, top=0.5,
                      bottom=1.5):
    """max |measured bbox + allowances - the runner's stock box| (mm)."""
    m = runner_mod.measure_result(bbox_for_measure)["bbox_mm"]
    grown = [m["min"][0] - sx, m["max"][0] + sx, m["min"][1] - sy,
             m["max"][1] + sy, m["min"][2] - bottom, m["max"][2] + top]
    return max(abs(a - b) for a, b in
               zip(grown, stock_box(bbox, sx, sy, top, bottom)))


BBOX = [-30.0, 10.0, -5.0, 15.0, 0.0, 8.0]  # off-centre, non-cube


def test_b_measure_result_shape():
    r = runner_mod.measure_result(BBOX)
    assert r == {"size_mm": {"x": 40.0, "y": 20.0, "z": 8.0},
                 "bbox_mm": {"min": [-30.0, -5.0, 0.0],
                             "max": [10.0, 15.0, 8.0]}}
    assert _measure_vs_stock(BBOX, BBOX) < 1e-9


def test_b_injected_fault_is_measured():
    """Fault: measuring the stock box instead of the part (allowances
    applied twice) - off by the largest allowance, 2.0 mm."""
    wrong = stock_box(BBOX, 1.0, 2.0, 0.5, 1.5)
    assert _measure_vs_stock(wrong, BBOX) == pytest.approx(2.0)


def test_b_catalog_measure_action():
    a = catalog_mod.get_action(catalog_mod.MEASURE_ACTION)
    assert a["confirm"] is False
    p = a["inputs"]["properties"]
    assert set(p) == {"model", "orientation"}
    assert p["model"]["x-steve"] == "file" and p["model"]["format"] == "step"
    assert catalog_mod.MEASURE_ACTION in catalog_mod.ENGINE_ACTIONS


def test_b_runner_measure_uses_prepare(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    cfg = {"engine_python": PY, "repo_root": REPO}
    import json
    real = _fake_spawn(calls)

    def spawn(self, argv, *a, **k):
        real(self, argv, *a, **k)
        with open(os.path.join(self.work, "prepare.json")) as fh:
            prep = json.load(fh)
        prep["bbox"] = BBOX
        with open(os.path.join(self.work, "prepare.json"), "w") as fh:
            json.dump(prep, fh)
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
    result, files = runner_mod.EngineRun(cfg, str(tmp_path)).run_measure(
        STEP, {"orientation": "flip_x_180"})
    assert files == {}
    assert result["size_mm"] == {"x": 40.0, "y": 20.0, "z": 8.0}
    a = calls[0]
    assert a[a.index("engine.cli") + 1] == "prepare"
    assert a[a.index("--orient") + 1] == "flip_x_180"


# --------------------------------------------------- (c) setup memory ----

import json  # noqa: E402
import toollib  # noqa: E402

SETUP = {"orientation": "flip_x_180", "units": "inch", "stock_xy": 1.0,
         "stock_x": 2.286, "stock_y": None, "stock_top": 0.5,
         "stock_bottom": 1.5, "floor_z": 4.0,
         "blank": {"x": 60.0, "y": 40.0, "z": 25.0}}


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return str(h)


def test_c_setup_round_trip_and_coexists_with_renumber(home):
    assert toollib.job_get(home, "doc-s")["setup"] is None
    toollib.renumber(home, REPO, "doc-s", "flat-12.686", 5)
    job = toollib.set_setup(home, "doc-s", SETUP)
    assert job["setup"] == SETUP and job["renumber"] == {"flat-12.686": 5}
    # renumbering keeps the setup, the setup key is never a tool
    job = toollib.renumber(home, REPO, "doc-s", "flat-12.686", 6)
    assert job["setup"] == SETUP and job["renumber"] == {"flat-12.686": 6}
    with open(os.path.join(home, "jobs", "doc-s.json")) as fh:
        raw = json.load(fh)
    assert raw == {"flat-12.686": 6, "setup": SETUP}
    tab = toollib.effective_table(home, REPO, "doc-s")
    assert next(t for t in tab["tools"]
                if t["tool_id"] == "flat-12.686")["number"] == 6


def test_c_setup_defaults_fill_omitted_fields(home):
    job = toollib.set_setup(home, "doc-d", {"orientation": "as_modeled"})
    assert job["setup"] == {"orientation": "as_modeled", "units": "inch",
                            "stock_xy": 1.0, "stock_x": None,
                            "stock_y": None, "stock_top": 1.0,
                            "stock_bottom": 1.0, "floor_z": 0.0,
                            "blank": None}


@pytest.mark.parametrize("bad,code", [
    ({"stock_top": 30.0}, "out_of_range"),        # max 25.4 mm
    ({"stock_x": -0.1}, "out_of_range"),          # min 0
    ({"floor_z": 201.0}, "out_of_range"),         # max 200
    ({"orientation": "sideways"}, "out_of_range"),
    ({"units": "cm"}, "out_of_range"),
    ({"stock_xy": "1"}, "invalid_field"),
    ({"blank": {"x": 1, "y": 2}}, "invalid_field"),
    ({"blank": {"x": 1, "y": 2, "z": 0}}, "invalid_field"),
    ({"tool": 3}, "invalid_field"),
])
def test_c_setup_refusals(home, bad, code):
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.set_setup(home, "doc-r", dict(SETUP, **bad))
    assert e.value.code == code
    assert toollib.job_get(home, "doc-r")["setup"] is None


def test_c_injected_fault_is_measured(home, monkeypatch):
    """Fault: setup validation skipped. stock_top 30.0 mm is then saved,
    4.6 mm above the action's 25.4 mm maximum."""
    monkeypatch.setattr(toollib, "_validate_setup", lambda s: s)
    job = toollib.set_setup(home, "doc-f", dict(SETUP, stock_top=30.0))
    hi = catalog_mod.get_action(catalog_mod.ACTION)["inputs"][
        "properties"]["stock_top"]["maximum"]
    assert job["setup"]["stock_top"] - hi == pytest.approx(4.6)


def test_c_connector_job_setup_dispatch(tmp_path):
    h = tmp_path / "h"
    h.mkdir()
    with open(h / "config.toml", "w") as fh:
        fh.write('base_url = "http://127.0.0.1:9"\nrepo_root = "%s"\n' % REPO)
    c = connector_mod.Connector(str(h))
    job = c.tool_action(catalog_mod.JOB_SETUP,
                        {"document_id": "d1", "setup": SETUP})
    assert c.tool_action(catalog_mod.JOB_GET,
                         {"document_id": "d1"})["setup"] == SETUP == \
        job["setup"]
    assert catalog_mod.get_action(catalog_mod.JOB_SETUP)["confirm"] is False


def test_b_measure_inputs_get_no_document_fallback():
    """model.measure takes no document_id: the model's STEVE document must
    not be injected as an (unknown) input."""
    ok, code, v = connector_mod.prepare_values(
        {"model": {"document": {"id": "doc-x"}}}, catalog_mod.MEASURE_ACTION)
    assert ok, (code, v)
    assert "document_id" not in v
