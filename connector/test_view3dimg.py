"""TASK_VIEW3D-IMG red tests: every run attaches two rendered pictures
(view_iso.png - an angled 3D view, view_top.png - a top view) built from the
run's view.bin/view.json. Display only.

(a) written + readable: on a fake-spawn run (test_toollib._fake_spawn) and on
    the committed synthetic fixture connector/testdata/view_fixture.*, both
    PNGs exist, are valid PNGs, long side 1500-1700 px, non-blank (distinct
    colours > 20), deterministic bytes across two renders, each <= 3 MB;
    registered in result["files"] after view.json.
(b) a forced render failure never fails the run: view_*.png dropped from
    result["files"] and the uploads, check.json and gates unchanged, one-line
    note in run.log, view.bin/view.json still present.
(c) markers numbered: the fixture's 2 markers -> caption lists "1" and "2"
    with their codes (checked via the returned dict, no OCR).

Run through the small-test lane:
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_view3dimg.py
"""
import hashlib
import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
import test_toollib as tl  # noqa: E402
from test_track2 import ROUGH_VALUES  # noqa: E402

PY = "/opt/homebrew/bin/python3"
STEP = os.path.join(HERE, "testdata", "synth_pocket.step")
FIX_JSON = os.path.join(HERE, "testdata", "view_fixture.json")
FIX_BIN = os.path.join(HERE, "testdata", "view_fixture.bin")


def _run_rough(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    cfg = {"engine_python": PY, "repo_root": REPO}
    run = runner_mod.EngineRun(cfg, str(tmp_path))
    result, files = run.run(STEP, dict(ROUGH_VALUES))
    return result, files, calls


def _run_chain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    cfg = {"engine_python": PY, "repo_root": REPO}
    run = runner_mod.EngineRun(cfg, str(tmp_path))
    result, files = run.run_slope_split_finish(
        os.path.join(HERE, "unused.step"), dict(tl.SLOPE))
    return result, files, calls


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _check_png(path):
    """valid PNG, long side 1500-1700, distinct colours > 20, <= 3 MB."""
    with open(path, "rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n", "%s is not a PNG" % path
    assert os.path.getsize(path) <= 3 * 1024 * 1024, \
        "%s is %d bytes > 3 MB" % (path, os.path.getsize(path))
    with Image.open(path) as im:
        im.load()
        long_side = max(im.size)
        assert 1500 <= long_side <= 1700, \
            "%s long side %d not in [1500, 1700]" % (path, long_side)
        arr = np.asarray(im.convert("RGB"))
    ncol = len(np.unique(arr.reshape(-1, 3), axis=0))
    assert ncol > 20, "%s has only %d distinct colours (blank?)" % (
        path, ncol)
    return ncol


# ---------------------------------------------------------- (a) red tests ----

def test_view3dimg_written_readable(tmp_path, monkeypatch):
    """fake-spawn adaptive_rough AND the finish chain register view_iso.png
    and view_top.png after view.json; both are readable PNGs; bytes are
    deterministic across two identical runs."""
    work = tmp_path / "r1"
    result, files, _ = _run_rough(work, monkeypatch)
    for name in ("view_iso.png", "view_top.png"):
        assert name in result["files"], "result['files'] lacks %s" % name
        assert name in files, "uploads lack %s" % name
        assert result["files"].index(name) > result["files"].index(
            "view.json"), "%s not registered after view.json" % name
        path = files[name][0]
        assert os.path.exists(path)
        assert files[name][1] == "image/png"
        _check_png(path)
    # deterministic bytes: a second identical run writes the same files
    work2 = tmp_path / "r2"
    _, files2, _ = _run_rough(work2, monkeypatch)
    for name in ("view_iso.png", "view_top.png"):
        assert _sha(files2[name][0]) == _sha(files[name][0]), \
            "%s bytes differ across two identical runs" % name

    # the finish chain registers them too (fake spawn)
    work3 = tmp_path / "r3"
    result3, files3, _ = _run_chain(work3, monkeypatch)
    for name in ("view_iso.png", "view_top.png"):
        assert name in result3["files"] and name in files3
        assert result3["files"].index(name) > result3["files"].index(
            "view.json")
        _check_png(files3[name][0])


def test_view3dimg_fixture_readable(tmp_path):
    """the committed synthetic fixture (100x100 grid, one path, 2 markers)
    renders to two readable, deterministic PNGs."""
    import viewimg
    paths = {}
    for rnd in (1, 2):
        iso = str(tmp_path / ("iso%d.png" % rnd))
        top = str(tmp_path / ("top%d.png" % rnd))
        ret = viewimg.render_images(FIX_JSON, FIX_BIN, iso, top)
        assert ret["view_iso.png"] == iso and ret["view_top.png"] == top
        paths[rnd] = (iso, top)
        if rnd == 1:
            _check_png(iso)
            _check_png(top)
    assert _sha(paths[2][0]) == _sha(paths[1][0]), \
        "view_iso.png bytes differ across two renders"
    assert _sha(paths[2][1]) == _sha(paths[1][1]), \
        "view_top.png bytes differ across two renders"


# ------------------------------------------------- (b) failure tolerance ----

def test_view3dimg_failure_never_fails_the_run(tmp_path, monkeypatch):
    """a forced render failure must not fail the run: the run returns, the
    result's files list and the uploads omit view_*.png, view.bin/view.json
    are still there, check.json and the gates are byte-for-byte what a run
    with working pictures writes, and a one-line note is in run.log."""
    import viewimg

    ok_dir, bad_dir = tmp_path / "ok", tmp_path / "bad"
    r_ok, f_ok, _ = _run_chain(ok_dir, monkeypatch)
    assert "view_iso.png" in r_ok["files"] and "view_iso.png" in f_ok

    def boom(*a, **k):
        raise RuntimeError("forced render failure")
    monkeypatch.setattr(viewimg, "render_images", boom)
    r_bad, f_bad, _ = _run_chain(bad_dir, monkeypatch)
    for name in ("view_iso.png", "view_top.png"):
        assert name not in r_bad["files"], "%s still in result files" % name
        assert name not in f_bad, "%s still uploaded" % name
    assert r_bad["files"] == [f for f in r_ok["files"]
                              if f not in ("view_iso.png", "view_top.png")]
    assert "view.bin" in r_bad["files"] and "view.json" in r_bad["files"]
    assert "view.bin" in f_bad and "view.json" in f_bad
    assert os.path.exists(os.path.join(str(bad_dir), "view.bin"))
    assert os.path.exists(os.path.join(str(bad_dir), "view.json"))
    assert _sha(f_bad["check.json"][0]) == _sha(f_ok["check.json"][0]), \
        "check.json changed when the render failed"
    assert r_bad["zmap"] == r_ok["zmap"], "gates changed when the render failed"
    log = open(os.path.join(str(bad_dir), "run.log")).read()
    notes = [ln for ln in log.splitlines() if "forced render failure" in ln]
    assert len(notes) == 1, "expected exactly one note line, got: %r" % notes
    assert notes[0].startswith("viewimg: skipped"), notes[0]


# ------------------------------------------------------ (c) markers ----

def test_view3dimg_markers_numbered(tmp_path):
    """the fixture's 2 markers are numbered 1..2 and the caption pairs every
    number with its code (checked via the returned dict, no OCR); the legend
    names the program."""
    import viewimg
    ret = viewimg.render_images(
        FIX_JSON, FIX_BIN, str(tmp_path / "i.png"), str(tmp_path / "t.png"),
        tools={"program.nc": "T7 ball 6.000 mm"})
    nums = [(m["number"], m["code"]) for m in ret["markers"]]
    assert nums == [(1, "rough.gouges"), (2, "rough.over_flute")], nums
    assert any("program.nc" in s and "T7" in s for s in ret["legend"]), \
        "legend does not name the program and its tool: %r" % ret["legend"]
