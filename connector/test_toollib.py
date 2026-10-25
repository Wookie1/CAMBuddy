"""Track 2 (toollib): tool library, per-document job renumbering, and the
runner wiring. Fast: no engine (runner subprocesses are faked). Every test
uses a temp state dir - never the real ~/.stevecam.

Run: /opt/homebrew/bin/python3 -m pytest connector/test_toollib.py -q
"""
import hashlib
import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import catalog as catalog_mod  # noqa: E402
import connector as connector_mod  # noqa: E402
import runner as runner_mod  # noqa: E402
import toollib  # noqa: E402

PY = "/opt/homebrew/bin/python3"
REPO_TABLE = os.path.join(REPO, "tools", "x7_tools.json")
ROUGH = "flat-12.686"   # library T13
DOC = "doc-renum"

LIST_KEYS = {"tool_id", "t", "h", "d", "name", "type", "dia_mm",
             "corner_r_mm", "flute_len_mm", "reach_mm", "holder", "rpm",
             "feed_mm_min", "plunge_mm_min"}

SLOPE = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 5.0, "tool_diameter": 9.525,
    "stepover": 0.3, "stepdown": 0.3, "slope_threshold": 40.0,
    "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 20, "units": "mm", "program_number": 1002,
    "rough_tool_type": "flat", "rough_tool_diameter": 12.686,
    "rough_corner_radius": 0.0, "rough_flute_length": 50.8,
    "rough_stepdown": 4.0, "rough_optimal_load": 2.0,
    "rough_stock_to_leave": 0.381, "rough_rest_stepup": 1.905,
}


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return str(h)


# ------------------------------------------------------------ library ----

def test_repo_entries_have_unique_stable_tool_ids():
    with open(REPO_TABLE) as fh:
        tools = json.load(fh)["tools"]
    ids = [t.get("tool_id") for t in tools]
    assert all(ids) and len(set(ids)) == len(ids)
    assert next(t for t in tools if t["tool_id"] == ROUGH)["number"] == 13


def test_tools_list_contract_and_seed(home):
    before = _sha(REPO_TABLE)
    out = toollib.tools_list(home, REPO)
    assert out["pockets"] == 12
    assert os.path.exists(os.path.join(home, "tools.json")), "not seeded"
    t13 = next(t for t in out["tools"] if t["tool_id"] == ROUGH)
    assert set(t13) == LIST_KEYS
    assert (t13["t"], t13["h"], t13["d"]) == (13, 13, 13)
    assert t13["type"] == "flat" and t13["dia_mm"] == 12.686
    assert t13["holder"] == "BT30-ER32-70"
    # not in the table: null, never invented
    assert t13["reach_mm"] is None and t13["rpm"] is None
    unassigned = next(t for t in out["tools"] if t["tool_id"] == "ball-19.050")
    assert (unassigned["t"], unassigned["h"], unassigned["d"]) == \
        (None, None, None)
    assert _sha(REPO_TABLE) == before


# --------------------------------------------------------- renumbering ----

def test_renumber_t13_to_t5_job_only(home):
    toollib.tools_list(home, REPO)  # seed
    lib_before = _sha(os.path.join(home, "tools.json"))
    repo_before = _sha(REPO_TABLE)
    job = toollib.renumber(home, REPO, DOC, ROUGH, 5)
    assert job == {"document_id": DOC, "renumber": {ROUGH: 5},
                   "tools_used": [], "setup": None}
    with open(os.path.join(home, "jobs", DOC + ".json")) as fh:
        assert json.load(fh) == {ROUGH: 5}
    assert _sha(os.path.join(home, "tools.json")) == lib_before
    assert _sha(REPO_TABLE) == repo_before
    tab = toollib.effective_table(home, REPO, DOC)
    e = next(t for t in tab["tools"] if t["tool_id"] == ROUGH)
    assert (e["number"], e["length_offset"], e["diameter_offset"]) == \
        (5, "H05", "D05")
    # every other tool keeps its library T/H/D
    lib = toollib.load_library(home, REPO)
    for a, b in zip(lib["tools"], tab["tools"]):
        if a["tool_id"] != ROUGH:
            assert a == b
    # another document is untouched
    other = toollib.effective_table(home, REPO, "doc-other")
    assert next(t for t in other["tools"]
                if t["tool_id"] == ROUGH)["number"] == 13
    # back to the library T clears the override
    assert toollib.renumber(home, REPO, DOC, ROUGH, 13)["renumber"] == {}


def test_duplicate_t_refused(home):
    # T3 is the bull's library T
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.renumber(home, REPO, DOC, ROUGH, 3)
    assert e.value.code == "duplicate_t"
    # two job overrides on one T
    toollib.renumber(home, REPO, DOC, ROUGH, 5)
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.renumber(home, REPO, DOC, "ball-19.050", 5)
    assert e.value.code == "duplicate_t"
    assert toollib.job_get(home, DOC)["renumber"] == {ROUGH: 5}


@pytest.mark.parametrize("t", [0, 14, -1, "5", 5.0, True, None])
def test_out_of_range_refused(home, t):
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.renumber(home, REPO, DOC, ROUGH, t)
    assert e.value.code == "out_of_range"
    assert toollib.job_get(home, DOC)["renumber"] == {}


def test_pockets_from_library(home):
    toollib.update_tool(home, REPO, new_pockets=24)
    assert toollib.renumber(home, REPO, DOC, ROUGH, 24)["renumber"] == \
        {ROUGH: 24}
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.renumber(home, REPO, DOC, ROUGH, 25)
    assert e.value.code == "out_of_range"


def test_unknown_tool_and_bad_document(home):
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.renumber(home, REPO, DOC, "nope", 5)
    assert e.value.code == "unknown_tool"
    for bad in ("../x", "", "a/b", ".hidden", "x" * 200):
        with pytest.raises(toollib.ToolLibError) as e:
            toollib.renumber(home, REPO, bad, ROUGH, 5)
        assert e.value.code == "bad_document_id"
    assert not os.path.exists(os.path.join(os.path.dirname(home), "x.json"))


def test_effective_table_refuses_stale_duplicate(home):
    toollib.renumber(home, REPO, DOC, ROUGH, 5)
    # a later library edit puts another tool on T5
    toollib.update_tool(home, REPO, "ball-19.050", {"t": 5})
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.effective_table(home, REPO, DOC)
    assert e.value.code == "duplicate_t"


# --------------------------------------------------------- tools.update --

def test_update_saves_library_never_repo(home):
    repo_before = _sha(REPO_TABLE)
    out = toollib.update_tool(home, REPO, "ball-19.050",
                              {"t": 7, "name": "3/4 BALL", "rpm": 6000,
                               "holder": "BT30-ER20-60"})
    assert set(out["tool"]) == LIST_KEYS
    assert (out["tool"]["t"], out["tool"]["h"], out["tool"]["d"]) == (7, 7, 7)
    assert out["tool"]["name"] == "3/4 BALL" and out["tool"]["rpm"] == 6000
    listed = toollib.tools_list(home, REPO)["tools"]
    assert next(t for t in listed if t["tool_id"] == "ball-19.050")["t"] == 7
    assert _sha(REPO_TABLE) == repo_before


@pytest.mark.parametrize("changes,code", [
    ({"t": 3}, "duplicate_t"),
    ({"t": 40}, "out_of_range"),
    ({"h": 4}, "invalid_field"),
    ({"tool_id": "x"}, "invalid_field"),
    ({"type": "drill"}, "invalid_field"),
    ({"dia_mm": -1}, "invalid_field"),
    ({"corner_r_mm": 1.0}, "invalid_field"),   # a flat has corner 0
    ({"rpm": 0}, "invalid_field"),
    ({"holder": "NOPE"}, "unknown_holder"),
    ({"dia_mm": 12.7, "type": "bull", "corner_r_mm": 0.127},
     "duplicate_tool"),
])
def test_update_refusals(home, changes, code):
    toollib.tools_list(home, REPO)
    before = _sha(os.path.join(home, "tools.json"))
    with pytest.raises(toollib.ToolLibError) as e:
        toollib.update_tool(home, REPO, ROUGH, changes)
    assert e.value.code == code
    assert _sha(os.path.join(home, "tools.json")) == before


# ---------------------------------------------------------- catalog ----

def test_catalog_tool_actions_never_confirm():
    for name in catalog_mod.TOOL_ACTIONS:
        a = catalog_mod.get_action(name)
        assert a is not None and a["confirm"] is False, name
    for name in catalog_mod.ACTIONS:
        p = catalog_mod.get_action(name)["inputs"]["properties"]
        assert p["document_id"]["type"] == "string"
        assert "document_id" not in \
            catalog_mod.get_action(name)["inputs"].get("required", [])
        assert len(p) <= 30


# ------------------------------------------------ connector dispatch ----

def test_connector_tool_action_dispatch(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    with open(h / "config.toml", "w") as fh:
        fh.write('base_url = "http://127.0.0.1:9"\nrepo_root = "%s"\n' % REPO)
    c = connector_mod.Connector(str(h))
    lst = c.tool_action(catalog_mod.TOOLS_LIST, {})
    assert {t["tool_id"] for t in lst["tools"]} >= {ROUGH}
    job = c.tool_action(catalog_mod.JOB_RENUMBER,
                        {"document_id": DOC, "tool_id": ROUGH, "t": 5})
    assert job["renumber"] == {ROUGH: 5}
    assert c.tool_action(catalog_mod.JOB_GET, {"document_id": DOC}) == job
    upd = c.tool_action(catalog_mod.TOOLS_UPDATE,
                        {"tool_id": ROUGH, "changes": {"name": "T13 LR"}})
    assert upd["tool"]["name"] == "T13 LR"
    with pytest.raises(toollib.ToolLibError) as e:
        c.tool_action(catalog_mod.JOB_RENUMBER,
                      {"document_id": DOC, "tool_id": ROUGH, "t": 99})
    assert e.value.as_dict()["code"] == "out_of_range"


# ------------------------------------------------- runner (fake engine) --

def _fake_spawn(calls):
    def spawn(self, argv, lo, hi, on_progress, json_out=None,
              extra_env=None):
        a = list(argv)
        calls.append(a)

        def opt(flag):
            return a[a.index(flag) + 1] if flag in a else None
        if "verify.zmap" in a:
            if opt("--stock-out"):
                np.save(opt("--stock-out"), np.full((8, 8), -1.0))
            z = {"count": 0, "max_depth": 0.0, "first_line": None}
            with open(opt("--out-json"), "w") as fh:
                json.dump({"gouges": z, "rapid_collisions": z,
                           "outside_grid": z, "over_flute": z,
                           "holder": {"status": "checked"}, "holder_hits": z,
                           "unsupported": [],
                           "leftover": {"max": 0.0, "mean": 0.0, "p95": 0.0},
                           "within_0p5mm_fraction": 1.0, "cycle_time_s": 1.0,
                           "cutting_length_mm": 1.0, "rapid_length_mm": 1.0,
                           "engagement": {}, "plunge": {}}, fh)
        elif any(t.endswith("heightfield.py") for t in a):
            np.save(extra_env["HF_OUT"], np.full((8, 8), 0.4))
            with open(os.path.splitext(extra_env["HF_OUT"])[0] + ".json",
                      "w") as fh:
                json.dump({"step_sha256": _sha(extra_env["STEP_IN"]),
                           "x0": 0.0, "y0": 0.0,
                           "cell": float(extra_env["CELL"]),
                           "tess_tol": 0.01}, fh)
        elif any(t.endswith("_tessellate.py") for t in a):
            with open(extra_env["STL_OUT"], "wb") as fh:
                fh.write(b"solid f\nendsolid f\n")
        elif any(t.endswith("probe_clcheck.py") for t in a):
            json_out.append({"below_cl": 0})
        elif a[a.index("engine.cli") + 1] == "prepare":
            with open(os.path.join(self.work, "o.step"), "w") as fh:
                fh.write("fake")
            with open(os.path.join(self.work, "prepare.json"), "w") as fh:
                json.dump({"step": os.path.join(self.work, "o.step"),
                           "hf": "hf.npz",
                           "stock": [-10, 10, -10, 10, -1, 0.4]}, fh)
        else:
            if opt("--out"):
                with open(opt("--out"), "w") as fh:
                    fh.write("G21\n")
            if opt("--stats-json"):
                with open(opt("--stats-json"), "w") as fh:
                    json.dump({"levels": [], "n_moves": 1}, fh)
    return spawn


def _tool_numbers(calls):
    """{output name: --tool-number} for posts/roughs, plus zmap per input."""
    out = {}
    for a in calls:
        if "--tool-number" not in a:
            continue
        n = int(a[a.index("--tool-number") + 1])
        if "verify.zmap" in a:
            out["zmap:" + os.path.basename(a[a.index("verify.zmap") + 1])] = n
        else:
            out[os.path.basename(a[a.index("--out") + 1])] = n
    return out


def test_runner_chain_posts_job_numbers(home, tmp_path, monkeypatch):
    """rough -> finish -> rest with T13 renumbered to T5 for this document:
    the rough's post and zmap use T5, the finish (T20) and rest (T31) are
    unchanged, zmap reads the effective table, the library is unchanged and
    tools_used records the job's tools."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    toollib.renumber(home, REPO, DOC, ROUGH, 5)
    lib_before = _sha(os.path.join(home, "tools.json"))
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    run = runner_mod.EngineRun(cfg, str(tmp_path / "run"))
    result, _ = run.run_slope_split_finish(
        os.path.join(HERE, "testdata", "synth_pocket.step"),
        dict(SLOPE, rest_tool_number=31, document_id=DOC))
    assert _tool_numbers(calls) == {
        "rough.nc": 5, "finish.nc": 20, "rest.nc": 31,
        "zmap:rough.nc": 5, "zmap:finish.nc": 20, "zmap:rest.nc": 31}
    assert result["programs"]["rough"]["tool"]["number"] == 5
    for a in calls:
        if "verify.zmap" in a:
            tj = a[a.index("--tools-json") + 1]
            with open(tj) as fh:
                tab = json.load(fh)
            assert {t["number"] for t in tab["tools"]
                    if t["tool_id"] == ROUGH} == {5}
    assert _sha(os.path.join(home, "tools.json")) == lib_before
    assert toollib.job_get(home, DOC)["tools_used"] == \
        [ROUGH, "ball-9.525", "ball-5.958"]

    # same run without the document: library T13
    calls.clear()
    run2 = runner_mod.EngineRun(cfg, str(tmp_path / "run2"))
    run2.run_slope_split_finish(
        os.path.join(HERE, "testdata", "synth_pocket.step"), dict(SLOPE))
    assert _tool_numbers(calls)["rough.nc"] == 13


def test_runner_adaptive_rough_job_number(home, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    toollib.renumber(home, REPO, DOC, ROUGH, 5)
    values = {"orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
              "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
              "tool_diameter": 12.686, "corner_radius": 0.0,
              "flute_length": 50.8, "stepdown": 4.0, "optimal_load": 2.0,
              "stock_to_leave": 0.381, "rest_stepup": 1.905, "rpm": 7500,
              "feed": 3429.0, "ramp_feed": 1270.0, "units": "mm",
              "program_number": 1001, "document_id": DOC}
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    result, _ = runner_mod.EngineRun(cfg, str(tmp_path / "r")).run(
        os.path.join(HERE, "testdata", "synth_pocket.step"), values)
    assert _tool_numbers(calls) == {"rough.nc": 5, "zmap:rough.nc": 5}
    assert result["tool"]["number"] == 5


def test_check_program_resolves_job_t(home, tmp_path, monkeypatch):
    """A program posted as T5 for this document is judged with the tool
    renumbered to T5 (flat 12.686, BT30-ER32-70); without the document's
    job, T5 is unknown and the run fails before any engine work."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _fake_spawn(calls))
    toollib.renumber(home, REPO, DOC, ROUGH, 5)
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    work = tmp_path / "c"
    work.mkdir()
    prog = work / "program.nc"
    prog.write_text("%\nO1001\nT5 M06\nG43 Z25. H05 M03 S7500\nG0 X0 Y0\n"
                    "M30\n%\n")
    vals = {"orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
            "stock_bottom": 1.0, "document_id": DOC}
    step = os.path.join(HERE, "testdata", "synth_pocket.step")
    result, _ = runner_mod.EngineRun(cfg, str(work)).run_check_program(
        str(prog), step, vals)
    assert result["tool"]["number"] == 5
    assert result["tool"]["type"] == "flat"
    assert result["tool"]["diameter_mm"] == 12.686
    assert result["tool"]["holder"] == "BT30-ER32-70"
    z = [a for a in calls if "verify.zmap" in a][0]
    assert z[z.index("--tool-number") + 1] == "5"
    assert toollib.job_get(home, DOC)["tools_used"] == [ROUGH]

    calls.clear()
    with pytest.raises(runner_mod.EngineError) as e:
        runner_mod.EngineRun(cfg, str(work)).run_check_program(
            str(prog), step, dict(vals, document_id="doc-other"))
    assert "T5" in str(e.value)
    assert calls == []
