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

SETUP = {"orientation": "flip_x_180", "origin": "stock_top_centre",
         "units": "inch", "stock_xy": 1.0,
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
    assert job["setup"] == {"orientation": "as_modeled",
                            "origin": "stock_bottom_centre", "units": "inch",
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


# ------------------------------------------------------ (e) work origin --

from engine.cli import origin_offset, ORIGINS  # noqa: E402

# box_origin.step with GOOD-style allowances (xy 1, top 0.4, bottom 1):
# model frame stock box (part x 5..65, y -3..27, z -24..0, Z0 at its top)
STOCK_MODEL = [4.0, 66.0, -4.0, 28.0, -25.0, 0.4]
EXPECT = {"stock_bottom_centre": [-31.0, 31.0, -16.0, 16.0, 0.0, 25.4],
          "stock_top_centre": [-31.0, 31.0, -16.0, 16.0, -25.4, 0.0],
          "model_origin": STOCK_MODEL}


def frame_error(stock_box, origin):
    """max |stock box - where `origin` must put it| (mm)."""
    return max(abs(a - b) for a, b in zip(stock_box, EXPECT[origin]))


def _shift(box, d):
    return [box[0] + d[0], box[1] + d[0], box[2] + d[1], box[3] + d[1],
            box[4] + d[2], box[5] + d[2]]


def test_e_origin_offset_places_stock():
    assert tuple(ORIGINS) == tuple(catalog_mod.ORIGINS)
    for o in ORIGINS:
        moved = _shift(STOCK_MODEL, origin_offset(STOCK_MODEL, o))
        assert frame_error(moved, o) < 1e-9, o


def test_e_injected_fault_is_measured():
    """Fault: a Z offset 0.5 mm off. The frame check misses by 0.5 mm."""
    d = origin_offset(STOCK_MODEL, "stock_bottom_centre")
    moved = _shift(STOCK_MODEL, (d[0], d[1], d[2] + 0.5))
    assert frame_error(moved, "stock_bottom_centre") == pytest.approx(0.5)


def test_e_catalog_origin_inputs():
    for name, default in ((catalog_mod.ACTION, "stock_bottom_centre"),
                          (catalog_mod.SLOPE_ACTION, "stock_bottom_centre"),
                          (catalog_mod.CHECK_ACTION, None)):
        p = catalog_mod.get_action(name)["inputs"]["properties"]
        assert p["origin"]["enum"] == ["stock_bottom_centre",
                                       "stock_top_centre", "model_origin"]
        if default is None:   # check_program: required, no default (TL2)
            assert "default" not in p["origin"], name
            ok, code, _ = catalog_mod.validate_inputs(
                {"model": "m", "program": "p"}, name)
            assert not ok and code == "input_missing", (name, code)
        else:
            assert p["origin"]["default"] == default, name
        assert len(p) <= 30
    ok, code, v = catalog_mod.validate_inputs({"model": "m"},
                                              catalog_mod.ACTION)
    assert ok and v["origin"] == "stock_bottom_centre"
    ok, code, _ = catalog_mod.validate_inputs(
        {"model": "m", "origin": "corner"}, catalog_mod.ACTION)
    assert not ok and code == "input_out_of_range"


def test_e_runner_passes_origin_to_prepare(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    monkeypatch.setattr(runner_mod, "posted_units", lambda path, req: req)
    cfg = {"engine_python": PY, "repo_root": REPO}
    ok, code, v = connector_mod.prepare_values(
        dict(INCH_NO_UNITS, origin="stock_top_centre"), catalog_mod.ACTION)
    assert ok, v
    runner_mod.EngineRun(cfg, str(tmp_path / "r")).run(STEP, v)
    prep = [a for a in calls if "prepare" in a][0]
    assert prep[prep.index("--origin") + 1] == "stock_top_centre"
    calls.clear()
    with pytest.raises(KeyError):  # the fake prepare writes no bbox
        runner_mod.EngineRun(cfg, str(tmp_path / "m")).run_measure(
            STEP, {"orientation": "as_modeled"})
    assert "--origin" not in calls[0]  # measure: the model's own frame


# ------------------------------------------- (f) agent errors + envelope --

import errors  # noqa: E402
import envelope  # noqa: E402


def _rough_err(values_in):
    ok, code, err = connector_mod.prepare_values(values_in,
                                                 catalog_mod.ACTION)
    assert not ok
    return err


def _engine_err(fn):
    with pytest.raises(runner_mod.EngineError) as e:
        fn()
    return e.value.as_error()


def _lib_err(fn):
    with pytest.raises(toollib.ToolLibError) as e:
        fn()
    return e.value.as_dict()


def error_paths(home, tmp_path, monkeypatch):
    """{path name: (agent error, expected field or None)} - one entry per
    refusal path an agent can hit."""
    out = {}
    base = dict(INCH_NO_UNITS)
    out["input_missing"] = (connector_mod.prepare_values(
        {}, catalog_mod.ACTION)[2], "model")
    out["input_unknown"] = (_rough_err(dict(base, tool_diamter=1.0)),
                            "tool_diamter")
    out["input_out_of_range_inch"] = (_rough_err(
        dict(base, tool_diameter=2.0)), "tool_diameter")
    out["input_out_of_range_enum"] = (_rough_err(
        dict(base, tool_type="ball")), "tool_type")
    out["bull_corner"] = (_rough_err(dict(base, tool_type="bull",
                                          tool_diameter=0.5,
                                          corner_radius=0.3)),
                          "corner_radius")
    out["action_unknown"] = (catalog_mod.validate({}, "nope")[1], "action")
    # tool library / jobs
    out["duplicate_t"] = (_lib_err(lambda: toollib.renumber(
        home, REPO, "d", "flat-12.686", 3)), "t")
    out["out_of_range"] = (_lib_err(lambda: toollib.renumber(
        home, REPO, "d", "flat-12.686", 40)), "t")
    out["unknown_tool"] = (_lib_err(lambda: toollib.renumber(
        home, REPO, "d", "nope", 4)), "tool_id")
    out["bad_document_id"] = (_lib_err(lambda: toollib.renumber(
        home, REPO, "../x", "flat-12.686", 4)), "document_id")
    out["unknown_holder"] = (_lib_err(lambda: toollib.update_tool(
        home, REPO, "flat-12.686", {"holder": "X"})), "holder")
    out["invalid_field"] = (_lib_err(lambda: toollib.update_tool(
        home, REPO, "flat-12.686", {"h": 1})), "h")
    out["setup_range"] = (_lib_err(lambda: toollib.set_setup(
        home, "d", {"stock_top": 99})), "setup.stock_top")
    # runner fail-closed paths (no engine: they refuse before it)
    out["tool_not_in_table"] = (_engine_err(lambda: runner_mod.check_tool_entry(
        99, os.path.join(REPO, "tools", "x7_tools.json"))), "tool_number")
    cfg = {"engine_python": PY, "repo_root": REPO}
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn",
                        lambda *a, **k: None)
    slope = {"tool_diameter": 9.525, "rough_tool_type": "flat",
             "rough_tool_diameter": 12.686, "rough_corner_radius": 0.0}
    for code, rest in (("rest_tool_no_holder", 3),
                       ("rest_tool_not_ball", 13), ("rest_tool_too_big", 20)):
        out[code] = (_engine_err(lambda: runner_mod.EngineRun(
            cfg, str(tmp_path / code)).run_slope_split_finish(
                STEP, dict(slope, tool_number=20, rest_tool_number=rest))),
            "rest_tool_number")
    out["finish_tool_not_in_table"] = (_engine_err(
        lambda: runner_mod.EngineRun(cfg, str(tmp_path / "f"))
        .run_slope_split_finish(STEP, dict(slope, tool_diameter=7.7))),
        "tool_number")
    work = tmp_path / "cp"
    work.mkdir()
    for code, text, over in (("multi_tool_program", "T13 M06\nT20 M06\n",
                              {}),
                             ("no_t_word", "G0 X0\n", {}),
                             ("tool_number_mismatch", "T13 M06\n",
                              {"tool_number": 20})):
        (work / "program.nc").write_text(text)
        out[code] = (_engine_err(lambda: runner_mod.EngineRun(
            cfg, str(work)).run_check_program(
                str(work / "program.nc"), STEP,
                dict({"orientation": "as_modeled", "stock_xy": 1.0,
                      "stock_top": 1.0, "stock_bottom": 1.0}, **over))),
            {"multi_tool_program": "program", "no_t_word": "program",
             "tool_number_mismatch": "tool_number"}[code])
    for code, check in (("gouges", {"gouges": {"count": 2, "max_depth": .1,
                                               "worst_xy": [1, 2]}}),
                        ("rapid_collisions",
                         {"rapid_collisions": {"count": 1,
                                               "first_line": 16}}),
                        ("holder_unknown", {"holder": {"status": "none"}})):
        out[code] = (_engine_err(lambda: runner_mod._check_zmap_gates(check)),
                     None)
    out["unsupported_code"] = (runner_mod._engine_error(
        2, "Traceback (most recent call last):\n  File x\nunsupported: G81 "
           "at line 7\n").as_error(), None)
    out["engine_failed"] = (runner_mod._engine_error(
        1, "Traceback (most recent call last):\n  File \"x.py\"\n"
           "ValueError: boom\n").as_error(), None)
    return out


def path_issues(paths):
    bad = {}
    for name, (err, field) in paths.items():
        issues = errors.error_issues(err)
        if field is not None and err.get("field") != field:
            issues.append("field %r != %r" % (err.get("field"), field))
        if issues:
            bad[name] = issues
    return bad


def test_f_every_error_path_is_agent_ready(home, tmp_path, monkeypatch):
    paths = error_paths(home, tmp_path, monkeypatch)
    assert path_issues(paths) == {}
    # spot checks of the agent fields
    e = paths["input_out_of_range_inch"][0]
    assert e["got"] == 2.0 and e["allowed"]["units"] == "inch"
    assert e["allowed"]["maximum"] == pytest.approx(32.0 / 25.4, abs=1e-4)
    assert paths["input_unknown"][0]["allowed"][0] == "tool_diameter"
    assert "did you mean tool_diameter" in paths["input_unknown"][0][
        "message"]
    assert paths["bull_corner"][0]["allowed"]["exclusive_maximum"] == \
        pytest.approx(0.25)
    assert paths["bull_corner"][0]["got"] == 0.3
    assert paths["out_of_range"][0]["allowed"] == {"minimum": 1,
                                                   "maximum": 12}
    assert paths["rapid_collisions"][0]["where"] == {"line": 16}
    assert paths["unsupported_code"][0]["where"] == {"line": 7}
    assert "Traceback" not in paths["engine_failed"][0]["message"]
    assert "ValueError: boom" in paths["engine_failed"][0]["message"]


def test_f_injected_missing_next_step_is_caught(home, tmp_path, monkeypatch):
    """Fault: input_out_of_range loses its next_step. Exactly the paths
    with that code are flagged."""
    monkeypatch.setitem(errors.NEXT_STEPS, "input_out_of_range", "")
    bad = path_issues(error_paths(home, tmp_path, monkeypatch))
    assert sorted(bad) == ["bull_corner", "input_out_of_range_enum",
                           "input_out_of_range_inch"]
    assert all(v == ["missing next_step"] for v in bad.values())


def test_f_codes_table_and_guide_in_sync():
    assert all(step.strip() for step in errors.NEXT_STEPS.values())
    with open(errors.GUIDE) as fh:
        section = errors.guide_codes_section(fh.read())
    assert section == errors.render_code_table(), \
        "docs/agent_guide.md drifted: run python3 connector/errors.py"


# hand-written schema check of the envelope (no new packages)
def envelope_issues(r):
    out = []
    if r.get("verdict") not in ("ready", "needs_review", "failed"):
        out.append("verdict %r" % r.get("verdict"))
    if not (isinstance(r.get("summary"), str) and r["summary"].strip()):
        out.append("summary")
    att = r.get("attention")
    if not isinstance(att, list):
        return out + ["attention not a list"]
    for i, a in enumerate(att):
        if set(a) - {"code", "severity", "message", "where", "next_step"}:
            out.append("attention[%d] extra keys" % i)
        for k in ("code", "message", "next_step"):
            if not (isinstance(a.get(k), str) and a[k].strip()):
                out.append("attention[%d].%s" % (i, k))
        if a.get("severity") not in ("blocker", "review", "info"):
            out.append("attention[%d].severity" % i)
        w = a.get("where")
        if w is not None and (not isinstance(w, dict) or set(w) - {
                "program", "line", "x", "y", "z"}):
            out.append("attention[%d].where" % i)
    sev = {a.get("severity") for a in att if isinstance(a, dict)}
    want = ("failed" if "blocker" in sev else
            "needs_review" if "review" in sev else "ready")
    if r.get("verdict") != want:
        out.append("verdict %s but attention says %s" % (r.get("verdict"),
                                                         want))
    return out


CHECK_OK = {"gouges": {"count": 0}, "leftover": {"mean": 0.2, "p95": 0.4,
                                                 "max": 0.6},
            "within_0p5mm_fraction": 0.9,
            "engagement": {"threshold_mm": 2.4, "count": 0, "max_mm": 2.0},
            "plunge": {"count": 0}}


def test_f_envelope_mapping():
    r = envelope.for_result("adaptive_rough", CHECK_OK)
    assert envelope_issues(r) == [] and r["verdict"] == "ready"
    assert {a["code"] for a in r["attention"]} == {"leftover",
                                                    "area_left_for_next_op"}
    hot = dict(CHECK_OK, engagement={"threshold_mm": 2.4, "count": 3,
                                     "max_mm": 5.0,
                                     "spikes": [{"line": 40}]},
               credit_fallback={"count": 1})
    r = envelope.for_result("adaptive_rough", hot)
    assert envelope_issues(r) == [] and r["verdict"] == "needs_review"
    eng = next(a for a in r["attention"]
               if a["code"] == "engagement_overload")
    assert eng["where"] == {"program": "rough.nc", "line": 40}
    assert "credit_fallback" in {a["code"] for a in r["attention"]}
    chain = {"chain": ["rough", "finish"], "rough": CHECK_OK,
             "finish": CHECK_OK}
    r = envelope.for_result("slope_split_finish", chain)
    assert {a["where"]["program"] for a in r["attention"]} == \
        {"rough.nc", "finish.nc"}
    err = runner_mod._engine_error(
        2, "unsupported: G81 at line 7").as_error()
    r = envelope.for_failure("check_program", err)
    assert envelope_issues(r) == [] and r["verdict"] == "failed"
    assert r["attention"][0]["code"] == "unsupported_code"
    r = envelope.for_tool_action("tools.list",
                                 toollib.tools_list(None, REPO))
    assert envelope_issues(r) == [] and r["verdict"] == "ready"


def test_f_injected_envelope_fault_is_caught():
    """Fault: a review item reported as verdict ready."""
    r = envelope.for_result("adaptive_rough", dict(
        CHECK_OK, plunge={"count": 2, "ramp_angle_deg": 3.0}))
    r["verdict"] = "ready"
    assert envelope_issues(r) == ["verdict ready but attention says "
                                  "needs_review"]


def test_f_catalog_descriptions_state_units_range_default():
    for a in catalog_mod.CATALOG["actions"]:
        assert 20 < len(a["description"]) < 400, a["name"]
        for name, p in a["inputs"]["properties"].items():
            if "x-steve" in p or p.get("type") == "object":
                continue
            d = p["description"]
            assert "default" in d or "optional" in d, (a["name"], name)
            if name in catalog_mod.MM_FIELDS:
                assert "follows `units`" in d, (a["name"], name)
                if "minimum" in p:
                    assert "range" in d and " in" in d, (a["name"], name)


# ------------------------------------------------- TL2: toollib follow-ups --

def test_tl2_check_program_origin_required():
    """Item 1: check_program without origin is refused input_missing,
    field origin, with the setup-hint next_step; with origin it passes."""
    base = {"program": {"url": "u"}, "model": {"url": "u"}}
    ok, err = catalog_mod.validate(base, catalog_mod.CHECK_ACTION)
    assert not ok and err["code"] == "input_missing"
    assert err["field"] == "origin"
    assert err["next_step"] == ("pass the origin the program was posted "
                                "with; runs from this connector record it "
                                "in their check.json setup")
    ok, code, v = catalog_mod.validate_inputs(
        dict(base, origin="model_origin"), catalog_mod.CHECK_ACTION)
    assert ok and v["origin"] == "model_origin", code


def test_tl2_check_origin_injected_fault_is_measured(monkeypatch):
    """Fault: the required-origin rule off (pre-TL2). The same inputs then
    validate ok with NO origin at all (the schema has no default since
    the TL2 review) - measured: ok True and origin None, the exact slip
    item 1 refuses."""
    monkeypatch.setattr(catalog_mod, "CHECK_ACTION", "other")
    ok, code, v = catalog_mod.validate_inputs(
        {"program": {"url": "u"}, "model": {"url": "u"}}, "check_program")
    assert ok and v["origin"] is None


def _tl2_rough_argv(values, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    monkeypatch.setattr(runner_mod, "posted_units", lambda path, req: req)
    cfg = {"engine_python": PY, "repo_root": REPO}
    runner_mod.EngineRun(cfg, str(tmp_path)).run(STEP, values)
    return [a for a in calls if "engine.cli" in a
            and a[a.index("engine.cli") + 1] == "rough"][0]


def test_tl2_runner_posts_origin_header_line(tmp_path, monkeypatch):
    """Item 2: the runner passes the run's origin as a header comment to
    every post: rough, finish and rest."""
    from test_toollib import SLOPE
    ok, code, v = connector_mod.prepare_values(
        dict(INCH_NO_UNITS, origin="stock_top_centre"), catalog_mod.ACTION)
    assert ok, v
    argv = _tl2_rough_argv(v, tmp_path, monkeypatch)
    assert argv[argv.index("--header-comment") + 1] == \
        "ORIGIN: STOCK TOP CENTRE"
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    monkeypatch.setattr(runner_mod, "posted_units", lambda path, req: req)
    runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                         str(tmp_path / "s")).run_slope_split_finish(
        STEP, dict(SLOPE, origin="model_origin", rest_tool_number=31))
    posts = [a for a in calls if "engine.cli" in a
             and a[a.index("engine.cli") + 1] in ("rough", "post")]
    assert len(posts) == 3
    for a in posts:
        assert a[a.index("--header-comment") + 1] == "ORIGIN: MODEL ORIGIN"


def test_tl2_origin_line_injected_fault_is_measured(tmp_path, monkeypatch):
    """Fault: the runner forgets the flag (pre-TL2). The measured count of
    --header-comment words in the rough argv is then 0, not the 1 the
    origin line requires."""
    monkeypatch.setattr(runner_mod, "_origin_flags", lambda values: [])
    ok, code, v = connector_mod.prepare_values(
        dict(INCH_NO_UNITS, origin="stock_top_centre"), catalog_mod.ACTION)
    argv = _tl2_rough_argv(v, tmp_path, monkeypatch)
    assert argv.count("--header-comment") == 0


ROUGH_VALUES = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
    "tool_diameter": 12.686, "corner_radius": 0.0, "flute_length": 50.8,
    "stepdown": 4.0, "optimal_load": 2.0, "stock_to_leave": 0.381,
    "rest_stepup": 1.905, "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "units": "mm", "program_number": 1001,
}


def test_tl2_nothing_to_cut_blocks_the_run(tmp_path, monkeypatch):
    """Item 5: a rough whose program has no moves (exterior box, every
    level skipped) fails as a nothing_to_cut blocker before any judging;
    the envelope says verdict failed. Control: n_moves 1 runs through."""
    import json as _json
    from test_toollib import _fake_spawn

    def no_moves(self, argv, lo, hi, on_progress, json_out=None,
                 extra_env=None):
        _fake_spawn([])(self, argv, lo, hi, on_progress, json_out, extra_env)
        a = list(argv)
        sp = a[a.index("--stats-json") + 1] if "--stats-json" in a else None
        if sp:  # the rough posts an EMPTY program: 0 moves
            with open(sp, "w") as fh:
                _json.dump({"levels": [], "n_moves": 0}, fh)

    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", no_moves)
    cfg = {"engine_python": PY, "repo_root": REPO}
    with pytest.raises(runner_mod.EngineError) as e:
        runner_mod.EngineRun(cfg, str(tmp_path / "r")).run(
            STEP, dict(ROUGH_VALUES))
    err = e.value.as_error()
    assert err["code"] == "nothing_to_cut" and err["message"]
    assert err["message"].startswith("nothing to cut") and err["next_step"]
    env = envelope.for_failure("adaptive_rough", err)
    assert env["verdict"] == "failed"
    assert [a["code"] for a in env["attention"]] == ["nothing_to_cut"]
    assert env["attention"][0]["severity"] == "blocker"
    # injected-fault measurement: the empty program (n_moves 0) is what
    # trips it - with the normal fake engine (n_moves 1) the run succeeds
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn",
                        _fake_spawn([]))
    result, _ = runner_mod.EngineRun(cfg, str(tmp_path / "ok")).run(
        STEP, dict(ROUGH_VALUES))
    assert result["n_moves"] == 1
