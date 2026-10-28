"""TLG1: library tool geometry reaches the engine as well as the judges,
through one effective table per run.

Fast tests fake the runner subprocesses (as test_toollib._fake_spawn does);
ONE test makes real engine.cli post and verify.zmap calls (both pure
python) through the CLI. Run this file through the small-test lane script:
anything that runs the engine or zmap must go through it.

Run: python3 -m pytest connector/test_tlg1.py -q
"""
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
import test_toollib as tl  # noqa: E402
import toollib  # noqa: E402

PY = sys.executable
LIB_ONLY = "lib-only-flat-11.111"

ROUGH_VALS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
    "tool_diameter": 11.111, "corner_radius": 0.0, "flute_length": 40.0,
    "stepdown": 4.0, "optimal_load": 2.0, "stock_to_leave": 0.381,
    "rest_stepup": 1.905, "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "units": "mm", "program_number": 1001,
}


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return str(h)


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _lib_only_flat(home):
    """Seed the library, then make T13 a library-only tool (no repo row)
    with COMPLETE geometry and a distinctive 11.111 mm diameter."""
    lib = toollib.load_library(home, REPO)
    e = next(t for t in lib["tools"] if t["tool_id"] == tl.ROUGH)
    e["tool_id"] = LIB_ONLY
    e["diameter_mm"] = 11.111
    e["flute_mm"] = 40.0
    e["shank_diameter_mm"] = 11.111
    toollib.write_json(os.path.join(home, "tools.json"), lib)
    return lib


def _opt(a, flag):
    return a[a.index(flag) + 1] if flag in a else None


def test_every_engine_call_reads_the_effective_table(home, tmp_path,
                                                     monkeypatch):
    """Item 2: the runner passes the SAME effective table to EVERY
    engine.cli call of the run (rough, finish, rest finish, post, rest
    post), not only zmap; check.json and the run record name its path and
    sha256."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    work = str(tmp_path / "run")
    run = runner_mod.EngineRun(cfg, work)
    result, _ = run.run_slope_split_finish(
        os.path.join(HERE, "testdata", "synth_pocket.step"),
        dict(tl.SLOPE, rest_tool_number=31))
    eff = os.path.join(work, "tools_effective.json")
    seen = 0
    for a in calls:
        if "engine.cli" not in a:
            continue
        sub = a[a.index("engine.cli") + 1]
        if sub == "prepare":
            continue  # prepare reads no tool table
        assert "--tools-json" in a, "%s call lost --tools-json" % sub
        assert _opt(a, "--tools-json") == eff
        seen += 1
    assert seen == 5, "expected rough + finish + rest finish + 2 posts"
    for a in calls:
        if "verify.zmap" in a:
            assert _opt(a, "--tools-json") == eff
    want = _sha(eff)
    with open(os.path.join(work, "check.json")) as fh:
        check = json.load(fh)
    assert check["tools_table"] == {"path": eff, "sha256": want}
    assert result["tools_table"] == {"path": eff, "sha256": want}


def test_library_only_tool_runs_with_its_own_geometry(home, tmp_path,
                                                      monkeypatch):
    """Item 3/4a (faked subprocesses): a library-only tool (complete
    geometry, no repo row) runs; the engine argv and zmap's --dia read ITS
    diameter from the effective table, and check.json names that table."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    _lib_only_flat(home)
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    work = str(tmp_path / "r")
    result, _ = runner_mod.EngineRun(cfg, work).run(
        os.path.join(HERE, "testdata", "synth_pocket.step"),
        dict(ROUGH_VALS))
    rough = [a for a in calls
             if "engine.cli" in a
             and a[a.index("engine.cli") + 1] == "rough"][0]
    assert _opt(rough, "--tool") == "flat:11.1110:0.0000"
    assert _opt(rough, "--tools-json").endswith("tools_effective.json")
    assert _opt(rough, "--tool-number") == "13"
    z = [a for a in calls if "verify.zmap" in a][0]
    assert _opt(z, "--dia") == "11.1110"      # judged with the library dia
    assert _opt(z, "--tools-json") == _opt(rough, "--tools-json")
    assert result["tool"]["diameter_mm"] == 11.111
    with open(os.path.join(work, "check.json")) as fh:
        check = json.load(fh)
    eff = _opt(z, "--tools-json")
    assert check["tools_table"] == {"path": eff, "sha256": _sha(eff)}


def test_library_only_tool_judged_by_table_diameter(home, tmp_path,
                                                    monkeypatch):
    """Item 4a: the judged diameter is RESOLVED FROM THE EFFECTIVE TABLE
    (check_program reads the tool of the program's T word there): a
    library-only T13 with diameter 11.111 is judged with 11.111, not with
    the repo table's 12.686."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    _lib_only_flat(home)
    work = tmp_path / "c"
    work.mkdir()
    prog = work / "program.nc"
    prog.write_text("%\nO1\nT13 M06\nG0 X0.\nM30\n%\n")
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    result, _ = runner_mod.EngineRun(cfg, str(work)).run_check_program(
        str(prog), os.path.join(HERE, "testdata", "synth_pocket.step"),
        {"orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
         "stock_bottom": 1.0})
    z = [a for a in calls if "verify.zmap" in a][0]
    assert _opt(z, "--dia") == "11.1110"       # the library's diameter
    assert _opt(z, "--tools-json").endswith("tools_effective.json")
    assert result["tool"]["diameter_mm"] == 11.111


def test_incomplete_library_geometry_refused_before_engine(home, tmp_path,
                                                           monkeypatch):
    """Item 3: a used library tool missing any geometry field (here the
    stick-out) is refused with tool_not_in_table before ANY engine call."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    lib = _lib_only_flat(home)
    next(t for t in lib["tools"]
         if t["tool_id"] == LIB_ONLY)["stickout_mm"] = None
    toollib.write_json(os.path.join(home, "tools.json"), lib)
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    with pytest.raises(runner_mod.EngineError) as e:
        runner_mod.EngineRun(cfg, str(tmp_path / "r")).run(
            os.path.join(HERE, "testdata", "synth_pocket.step"),
            dict(ROUGH_VALS))
    err = e.value.as_error()
    assert err["code"] == "tool_not_in_table" and err["got"] == LIB_ONLY
    assert "stickout_mm" in str(e.value)
    assert calls == [], "refused before any engine work"


def test_library_geometry_mismatch_still_refused(home, tmp_path,
                                                 monkeypatch):
    """Item 3: a library tool whose tool_id IS in the repo table with a
    different diameter still refuses (tool_geometry_mismatch)."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    toollib.update_tool(home, REPO, tl.ROUGH, {"dia_mm": 12.0})
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    with pytest.raises(runner_mod.EngineError) as e:
        runner_mod.EngineRun(cfg, str(tmp_path / "r")).run(
            os.path.join(HERE, "testdata", "synth_pocket.step"),
            dict(ROUGH_VALS, tool_diameter=12.686, tool_number=13))
    err = e.value.as_error()
    assert err["code"] == "tool_geometry_mismatch" and err["field"] == "diameter_mm"
    assert calls == []


# ------------------------------------------------- one REAL post + zmap --

# FE5M (fe5 merge, ZB): the ball enters on a 10-deg helix (radius 1 about
# X1 Y0, 2 turns, 10.5 -> 9.0) instead of a straight feed plunge into the
# stock top Z10, and ends where the plunge ended (X0 Y0 Z9.0).
NEUTRAL = ("(BALL NOSE END MILL)\nG21\nG90\nG0 Z12.0\nG1 Z10.5 F1270\n"
           + "".join("G1 X%.4f Y%.4f Z%.4f F1270\n" % (
               1.0 + np.cos(np.pi + 2 * np.pi * i / 36),
               np.sin(np.pi + 2 * np.pi * i / 36), 10.5 - 1.5 * i / 72)
               for i in range(1, 73))
           + "G1 X5.0 Y0.0 F3429\nG0 Z12.0\n")


def _lib_only_ball(home):
    """Library-only ball 7.777 on T50, complete geometry incl. holder."""
    lib = toollib.load_library(home, REPO)
    lib["tools"].append({
        "tool_id": "ball-7.777", "number": 50, "type": "ball",
        "diameter_mm": 7.777, "corner_radius_mm": 3.8885,
        "length_offset": "H50", "diameter_offset": "D50",
        "flute_mm": 15.0, "shank_diameter_mm": 7.777,
        "stickout_mm": 18.0, "holder": "BT30-ER20-60",
        "description": "TLG1 test ball"})
    toollib.write_json(os.path.join(home, "tools.json"), lib)


def test_real_post_and_zmap_read_the_effective_table(home, tmp_path):
    """Item 4a: ONE real engine.cli post + ONE real verify.zmap call (both
    pure python, no opencamlib) with a library-only ball: the posted
    program's tool comment and T/H word and zmap's tool + holder blocks all
    read the LIBRARY geometry through --tools-json; without it the tool is
    unknown (repo table)."""
    eff = tmp_path / "tools_effective.json"
    _lib_only_ball(home)
    toollib.write_json(str(eff), toollib.effective_table(home, REPO, None))
    assert next((t for t in json.load(open(str(eff)))["tools"]
                 if t["number"] == 50), None) is not None
    assert 50 not in {t.get("number") for t in json.load(open(os.path.join(
        REPO, "tools", "x7_tools.json")))["tools"]}
    neu = tmp_path / "n.ngc"
    neu.write_text(NEUTRAL)
    nc = tmp_path / "p.nc"
    r = subprocess.run(
        [PY, "-m", "engine.cli", "post", "--in", str(neu), "--out", str(nc),
         "--metric", "--tool-kind", "ball", "--dia", "7.777",
         "--corner", "3.8885", "--tools-json", str(eff)],
        cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    posted = nc.read_text()
    assert "T50 M06" in posted and "H50" in posted
    assert "D=7.777" in posted          # header tool comment: library dia
    # without --tools-json the repo table cannot number this tool
    r2 = subprocess.run(
        [PY, "-m", "engine.cli", "post", "--in", str(neu), "--out",
         str(tmp_path / "x.nc"), "--metric", "--tool-kind", "ball",
         "--dia", "7.777", "--corner", "3.8885"],
        cwd=REPO, capture_output=True, text=True)
    assert r2.returncode != 0 and "not in" in (r2.stderr + r2.stdout)

    # zmap judges with the effective table: tool block + holder resolution
    n = 40
    part = np.full((n, n), 10.0)
    hf = tmp_path / "part_hf.npy"
    np.save(str(hf), part)
    with open(str(hf)[:-4] + ".json", "w") as fh:
        json.dump({"x0": -10.0, "y0": -10.0, "cell": 0.5,
                   "tess_tol": 0.01, "step_sha256": "0" * 64}, fh)
    zj = tmp_path / "check.json"
    argv = [PY, "-m", "verify.zmap", str(nc), "--part", str(hf),
            "--tool", "ball", "--dia", "7.777", "--corner", "3.8885",
            "--stock", "-9", "9", "-9", "9", "0", "10",
            "--tool-number", "50", "--out-json", str(zj)]
    r3 = subprocess.run(argv + ["--tools-json", str(eff)],
                        cwd=REPO, capture_output=True, text=True)
    assert r3.returncode == 0, r3.stderr[-800:]
    rep = json.load(open(str(zj)))
    assert rep["tool"]["dia"] == pytest.approx(7.777)
    assert rep["holder"]["status"] == "checked"
    assert rep["holder"]["name"] == "BT30-ER20-60"   # from the eff. table
    # the same call on the repo table cannot resolve the library-only T50
    r4 = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    assert r4.returncode == 0, r4.stderr[-800:]
    rep2 = json.load(open(str(zj)))
    assert rep2["holder"]["status"] != "checked"


def test_t_number_collision_library_tool_wins(home, tmp_path):
    """Coordinator (TLG1 review 2): a library tool whose T equals a repo
    tool's T (T31, repo ball-5.958) with a different tool_id. The effective
    table holds exactly ONE T31 entry - the library's - and the engine post
    (post_lnc lookup by kind + dia) and zmap both read the LIBRARY geometry
    (dia 7.777, stick-out 33 vs the repo row's 5.958 / 18)."""
    lib = toollib.load_library(home, REPO)
    next(t for t in lib["tools"] if t["tool_id"] == "ball-5.958")["number"] = None
    lib["tools"].append({
        "tool_id": "ball-7.777-t31", "number": 31, "type": "ball",
        "diameter_mm": 7.777, "corner_radius_mm": 3.8885,
        "length_offset": "H31", "diameter_offset": "D31", "flute_mm": 15.0,
        "shank_diameter_mm": 7.777, "stickout_mm": 33.0,
        "holder": "BT30-ER20-60", "description": "TLG1 T collision"})
    toollib.write_json(os.path.join(home, "tools.json"), lib)
    eff = tmp_path / "tools_effective.json"
    toollib.write_json(str(eff), toollib.effective_table(home, REPO, None))
    t31 = [t for t in json.load(open(str(eff)))["tools"] if t.get("number") == 31]
    assert [t["tool_id"] for t in t31] == ["ball-7.777-t31"], t31
    neu = tmp_path / "n.ngc"
    neu.write_text(NEUTRAL)
    nc = tmp_path / "p.nc"
    r = subprocess.run(
        [PY, "-m", "engine.cli", "post", "--in", str(neu), "--out", str(nc),
         "--metric", "--tool-kind", "ball", "--dia", "7.777",
         "--corner", "3.8885", "--tools-json", str(eff)],
        cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    posted = nc.read_text()
    assert "T31 M06" in posted and "D=7.777" in posted, posted[:400]
    part = np.full((40, 40), 10.0)
    hf = tmp_path / "part_hf.npy"
    np.save(str(hf), part)
    with open(str(hf)[:-4] + ".json", "w") as fh:
        json.dump({"x0": -10.0, "y0": -10.0, "cell": 0.5,
                   "tess_tol": 0.01, "step_sha256": "0" * 64}, fh)
    zj = tmp_path / "check.json"
    r3 = subprocess.run(
        [PY, "-m", "verify.zmap", str(nc), "--part", str(hf), "--tool",
         "ball", "--dia", "7.777", "--corner", "3.8885", "--stock", "-9",
         "9", "-9", "9", "0", "10", "--tool-number", "31", "--out-json",
         str(zj), "--tools-json", str(eff)],
        cwd=REPO, capture_output=True, text=True)
    assert r3.returncode == 0, r3.stderr[-800:]
    hd = json.load(open(str(zj)))["holder"]
    assert hd["status"] == "checked" and hd["stickout_mm"] == pytest.approx(33.0), hd


def test_repo_tool_with_null_holder_keeps_tl2_behaviour(home, tmp_path):
    """Coordinator (TLG1 review 1): the completeness check applies only to
    library-only tools. A used REPO-table tool whose row has a null holder /
    stick-out (T3 bull-12.700-r0.127) is not refused by the geometry check,
    exactly as on 98a5706 (TL2: mismatch compare only)."""
    t3 = next(t for t in json.load(open(os.path.join(
        REPO, "tools", "x7_tools.json")))["tools"] if t.get("number") == 3)
    assert t3.get("holder") is None and t3.get("stickout_mm") is None, t3
    cfg = {"engine_python": PY, "repo_root": REPO, "home": home}
    run = runner_mod.EngineRun(cfg, str(tmp_path / "run"))
    run._load_tools({})
    run._check_library_geometry({3})       # must not raise
