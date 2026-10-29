"""TASK_VIEW3D red tests (a) and (b): view.bin/view.json written, bounded,
deterministic, conservative and within the recorded decimation tolerance;
posted *.nc byte-identical with and without the viewer change.

Fast tests only (runner subprocesses faked with test_toollib._fake_spawn;
the "real scene" is the committed program connector/testdata/check_ok.nc
parsed by view.program_path - no engine, no FreeCAD).

Run through the small-test lane:
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_view3d.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
import test_toollib as tl  # noqa: E402
from test_track2 import ROUGH_VALUES  # noqa: E402

PY = "/opt/homebrew/bin/python3"
STEP = os.path.join(HERE, "testdata", "synth_pocket.step")
CHECK_OK = os.path.join(HERE, "testdata", "check_ok.nc")
BASE_COMMIT = "7326fec"


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


# ---------------------------------------------------------- (a) red tests ----

def test_view3d_file_written_and_bounded(tmp_path, monkeypatch):
    """adaptive_rough (fake spawn): view.bin/view.json registered as run
    files, written, header schema, size cap, deterministic bytes across two
    identical runs, and the zmap call that judges the program now carries
    --stock-out (the final judged stock)."""
    import view

    work = tmp_path / "r1"
    result, files, calls = _run_rough(work, monkeypatch)
    assert "view.bin" in result["files"] and "view.json" in result["files"]
    assert "view.bin" in files and "view.json" in files
    bin_path = files["view.bin"][0]
    json_path = files["view.json"][0]
    assert os.path.exists(bin_path) and os.path.exists(json_path)
    size = os.path.getsize(bin_path) + os.path.getsize(json_path)
    assert size <= view.MAX_BYTES, "view.bin+view.json %d > cap %d" % (
        size, view.MAX_BYTES)

    # the zmap call for rough.nc exports the final judged stock
    zc = [a for a in calls if "verify.zmap" in a][0]
    assert "--stock-out" in zc, "the judging zmap call has no --stock-out"

    hdr = json.load(open(json_path))
    assert hdr["format"] == "stevecam-view" and hdr["version"] == 1
    assert hdr["units"] == "mm"
    for k in ("x0", "y0", "cell", "nx", "ny"):
        assert k in hdr["grid"], "grid.%s missing" % k
    assert hdr["grid"]["cell"] == pytest.approx(0.5)
    assert hdr["grid"]["nx"] == 8 and hdr["grid"]["ny"] == 8
    assert hdr["z"]["scale"] <= 0.01 + 1e-12
    for p in hdr["programs"]:
        assert {"name", "points", "tolerance_mm", "cap", "xyz_offset",
                "flags_offset"} <= set(p)
    assert isinstance(hdr["markers"], list)
    # fake part hf is a flat 0.4, fake stock -1.0, cell 0.5
    raw = open(bin_path, "rb").read()
    npix = hdr["grid"]["ny"] * hdr["grid"]["nx"]
    part = np.frombuffer(raw[hdr["offsets"]["part"]:
                             hdr["offsets"]["part"] + npix * 2],
                         dtype="<u2").reshape(hdr["grid"]["ny"],
                                              hdr["grid"]["nx"])
    stock = np.frombuffer(raw[hdr["offsets"]["stock"]:
                              hdr["offsets"]["stock"] + npix * 2],
                          dtype="<u2").reshape(hdr["grid"]["ny"],
                                               hdr["grid"]["nx"])
    off, sc = hdr["z"]["offset"], hdr["z"]["scale"]
    assert np.all(part.astype(np.float64) * sc + off == pytest.approx(0.4, abs=sc / 2))
    assert np.all(stock.astype(np.float64) * sc + off == pytest.approx(-1.0, abs=sc / 2))

    # deterministic bytes: a second identical run writes the same files
    work2 = tmp_path / "r2"
    result2, files2, _ = _run_rough(work2, monkeypatch)
    assert _sha(files2["view.bin"][0]) == _sha(bin_path)
    assert _sha(files2["view.json"][0]) == _sha(json_path)

    # the finish chain registers them too (fake spawn)
    work3 = tmp_path / "r3"
    result3, files3, _ = _run_chain(work3, monkeypatch)
    assert "view.bin" in result3["files"] and "view.json" in result3["files"]
    assert os.path.exists(files3["view.bin"][0])


def test_view3d_heightfield_roundtrip_bounds(tmp_path):
    """Conservative downsample + uint16 round trip: part keeps the cell MAX,
    stock the cell MIN; decoded error <= scale/2 for the cell extremum and
    every source point within (cell spread + scale/2) of the stored value."""
    import view

    rng = np.random.default_rng(7)
    cell = 0.1
    part = rng.uniform(-2.0, 5.0, size=(20, 30))
    stock = part + rng.uniform(0.0, 0.8, size=(20, 30))
    pn = tmp_path / "part.npy"
    sn = tmp_path / "stock.npy"
    np.save(pn, part)
    np.save(sn, stock)
    meta = {"x0": -1.0, "y0": -2.0, "cell": cell, "tess_tol": 0.01}
    for p in (pn, sn):
        with open(os.path.splitext(str(p))[0] + ".json", "w") as fh:
            json.dump(meta, fh)
    out_bin = tmp_path / "v.bin"
    out_json = tmp_path / "v.json"
    hdr = view.build_view(str(out_bin), str(out_json), str(pn), str(sn),
                          [], {})
    g = hdr["grid"]
    assert g["cell"] == pytest.approx(0.5)
    assert g["nx"] == 6 and g["ny"] == 4  # 30*0.1/0.5, 20*0.1/0.5
    raw = open(out_bin, "rb").read()
    off, sc = hdr["z"]["offset"], hdr["z"]["scale"]
    assert sc <= 0.01 + 1e-12
    pq = np.frombuffer(raw[g["ny"] * g["nx"] * 0: g["ny"] * g["nx"] * 2],
                       dtype="<u2").reshape(g["ny"], g["nx"])
    sq = np.frombuffer(raw[g["ny"] * g["nx"] * 2:],
                       dtype="<u2").reshape(g["ny"], g["nx"])
    pd = pq.astype(np.float64) * sc + off
    sd = sq.astype(np.float64) * sc + off
    k = 5
    for iy in range(g["ny"]):
        for ix in range(g["nx"]):
            blk_p = part[iy * k:(iy + 1) * k, ix * k:(ix + 1) * k]
            blk_s = stock[iy * k:(iy + 1) * k, ix * k:(ix + 1) * k]
            # part: conservative MAX, stock: conservative MIN
            assert abs(pd[iy, ix] - blk_p.max()) <= sc / 2 + 1e-9
            assert abs(sd[iy, ix] - blk_s.min()) <= sc / 2 + 1e-9
            spread_p = blk_p.max() - blk_p.min()
            for v in blk_p.ravel():
                assert -sc / 2 - 1e-9 <= pd[iy, ix] - v <= spread_p + sc / 2 + 1e-9


def test_view3d_path_decimation_within_tolerance(tmp_path):
    """Real program (testdata/check_ok.nc): program_path densely samples
    (arcs resolved by verify.zmap), feed vs rapid flagged, and every dropped
    source point lies within the recorded tolerance of the kept polyline."""
    import view

    pts, flags = view.program_path(CHECK_OK, cell=0.5)
    assert len(pts) > 100, "no path parsed from check_ok.nc"
    assert set(np.unique(flags)) <= {0, 1} and 1 in flags
    for tol in (view.DEFAULT_TOL, 0.2):
        keep = view.decimate(pts, tol, flags)
        assert keep[0] == 0 and keep[-1] == len(pts) - 1
        err = view.path_error(pts, pts[keep])
        assert err <= tol + 1e-9, "dropped points %.4f mm > tol %.4f" % (
            err, tol)
    # decimation actually decimates, and both feed and rapid survive with
    # their flags
    keep = view.decimate(pts, view.DEFAULT_TOL, flags)
    assert len(keep) < len(pts)
    assert {0, 1} == set(flags.tolist()), "no rapid/feed split in check_ok.nc"

    # what build_view RECORDS is what it DID: the stored polyline's measured
    # error stays within the tolerance recorded in view.json (mutation M1:
    # a silently widened tolerance fails here on the measured value)
    cell = 0.1
    pn = tmp_path / "p.npy"
    sn = tmp_path / "s.npy"
    np.save(pn, np.full((60, 60), -3.0))
    np.save(sn, np.full((60, 60), 30.0))
    meta = {"x0": -30.0, "y0": -30.0, "cell": cell, "tess_tol": 0.01}
    for p in (pn, sn):
        with open(os.path.splitext(str(p))[0] + ".json", "w") as fh:
            json.dump(meta, fh)
    hdr = view.build_view(str(tmp_path / "v.bin"), str(tmp_path / "v.json"),
                          str(pn), str(sn), [("program.nc", CHECK_OK)], {})
    rec = hdr["programs"][0]
    assert rec["tolerance_mm"] == pytest.approx(view.DEFAULT_TOL)
    raw = open(tmp_path / "v.bin", "rb").read()
    n = rec["points"]
    stored = np.frombuffer(raw[rec["xyz_offset"]:rec["xyz_offset"] + n * 12],
                           dtype="<f4").reshape(n, 3).astype(np.float64)
    err = view.path_error(pts, stored)
    assert err <= rec["tolerance_mm"] + 1e-4, (
        "stored polyline deviates %.4f mm > recorded tolerance %.4f mm"
        % (err, rec["tolerance_mm"]))


def test_view3d_markers_from_checks():
    """attention-style gate entries with an XY become view markers."""
    import view

    checks = {"rough": {"gouges": {"count": 2, "worst_xy": [1.5, 2.5],
                                   "max_depth": 0.1},
                        "rapid_collisions": {"count": 0},
                        "over_flute": {"count": 1, "worst_xy": [0.0, 3.0]}},
              "finish": {"gouges": {"count": 0}}}
    m = view.markers_from_checks(checks)
    codes = [(x["code"], x["x"], x["y"]) for x in m]
    assert ("rough.gouges", 1.5, 2.5) in codes
    assert ("rough.over_flute", 0.0, 3.0) in codes
    assert len(m) == 2
    assert all("z" in x for x in m)


def test_view3d_size_cap_real_scene(tmp_path):
    """a larger synthetic grid stays within the 8 MB cap after 0.5 mm
    downsampling."""
    import view

    cell = 0.1
    part = np.random.default_rng(3).uniform(-5, 20, size=(600, 800))
    stock = part + 0.4
    pn = tmp_path / "p.npy"
    sn = tmp_path / "s.npy"
    np.save(pn, part)
    np.save(sn, stock)
    meta = {"x0": 0.0, "y0": 0.0, "cell": cell, "tess_tol": 0.01}
    for p in (pn, sn):
        with open(os.path.splitext(str(p))[0] + ".json", "w") as fh:
            json.dump(meta, fh)
    hdr = view.build_view(str(tmp_path / "v.bin"), str(tmp_path / "v.json"),
                          str(pn), str(sn), [], {})
    total = os.path.getsize(tmp_path / "v.bin") + os.path.getsize(
        tmp_path / "v.json")
    assert total <= view.MAX_BYTES
    assert hdr["grid"]["nx"] == 160 and hdr["grid"]["ny"] == 120


# ----------------------------------------------------- (b) byte-identical ----

def _probe_script(connector_dir, work):
    """hash every posted *.nc a fake-spawn rough and finish chain posts,
    using the runner/test_toollib of connector_dir."""
    code = (
        "import hashlib, json, sys, os\n"
        "here = %r\n"
        "sys.path.insert(0, here)\n"
        "import runner, test_toollib\n"
        "calls = []\n"
        "runner.EngineRun._spawn = test_toollib._fake_spawn(calls)\n"
        "cfg = {'engine_python': %r, 'repo_root': %r}\n"
        "out = {}\n"
        "r1 = runner.EngineRun(cfg, %r)\n"
        "_, f1 = r1.run(%r, json.loads(%r))\n"
        "r2 = runner.EngineRun(cfg, %r)\n"
        "_, f2 = r2.run_slope_split_finish(%r, json.loads(%r))\n"
        "for fs in (f1, f2):\n"
        "    for name, (path, _t) in fs.items():\n"
        "        if name.endswith('.nc'):\n"
        "            out[name] = hashlib.sha256(open(path, 'rb').read()).hexdigest()\n"
        "print(json.dumps(sorted(out.items())))\n"
    ) % (connector_dir, PY, REPO,
         os.path.join(work, "a"), STEP, json.dumps(ROUGH_VALUES),
         os.path.join(work, "b"), os.path.join(HERE, "unused.step"),
         json.dumps(dict(tl.SLOPE)))
    return code


@pytest.fixture(scope="module")
def base_tree():
    """pristine copy of the connector package at BASE_COMMIT (git archive,
    read-only)."""
    d = tempfile.mkdtemp(prefix="view3d_base_")
    with tempfile.TemporaryDirectory() as td:
        tar = os.path.join(td, "base.tar")
        with open(tar, "wb") as fh:
            subprocess.run(["git", "-C", REPO, "archive", BASE_COMMIT,
                            "connector"], check=True, stdout=fh)
        with tarfile.open(tar) as tf:
            tf.extractall(d)
    return os.path.join(d, "connector")


def test_view3d_programs_byte_identical(tmp_path, base_tree):
    """the posted *.nc of fake runs are byte-identical between the base
    commit (no viewer) and this branch (viewer)."""
    cur = _probe_script(HERE, str(tmp_path))
    base = _probe_script(base_tree, str(tmp_path))
    r_cur = subprocess.run([PY, "-c", cur], capture_output=True, text=True)
    r_base = subprocess.run([PY, "-c", base], capture_output=True, text=True)
    assert r_cur.returncode == 0, r_cur.stderr[-2000:]
    assert r_base.returncode == 0, r_base.stderr[-2000:]
    h_cur = json.loads(r_cur.stdout)
    h_base = json.loads(r_base.stdout)
    assert h_cur == h_base, ("posted programs differ:\ncur %s\nbase %s"
                             % (h_cur, h_base))
    assert len(h_cur) >= 2, "probe posted no programs: %s" % h_cur


# --------------------------------------------- supervisor fix (coordinator) ----
def test_view3d_real_shaped_stock_nodata(tmp_path):
    """A real judged stock carries -inf outside the stock box (zmap's padded
    grid). build_view must not crash on it: non-finite cells are stored as the
    header's nodata code, finite cells decode within scale/2 of the cell
    extremum, and the offset comes from finite cells only. (Crashed on
    edead3b: OverflowError from math.floor(-inf).)"""
    import view

    cell = 0.1
    part = np.full((40, 60), 1.0)
    stock = np.full((40, 60), -np.inf)
    stock[10:30, 10:50] = 6.0                  # the stock box interior
    part[0, 0] = np.nan                        # and one non-finite part cell
    pn, sn = tmp_path / "part.npy", tmp_path / "stock.npy"
    np.save(pn, part)
    np.save(sn, stock)
    meta = {"x0": 0.0, "y0": 0.0, "cell": cell, "tess_tol": 0.01}
    for p in (pn, sn):
        with open(os.path.splitext(str(p))[0] + ".json", "w") as fh:
            json.dump(meta, fh)
    hdr = view.build_view(str(tmp_path / "v.bin"), str(tmp_path / "v.json"),
                          str(pn), str(sn), [], {})
    g, z = hdr["grid"], hdr["z"]
    nd = z["nodata"]
    raw = open(tmp_path / "v.bin", "rb").read()
    n = g["nx"] * g["ny"]
    pq = np.frombuffer(raw[:2 * n], dtype="<u2").reshape(g["ny"], g["nx"])
    sq = np.frombuffer(raw[2 * n:4 * n], dtype="<u2").reshape(g["ny"], g["nx"])
    assert np.isfinite(z["offset"]) and z["offset"] <= 1.0
    assert sq[0, 0] == nd and sq[-1, -1] == nd, "border stock must be nodata"
    inner = sq[3:5, 3:9]                       # 0.5 mm cells fully inside the box
    assert (inner != nd).all()
    assert np.allclose(inner * z["scale"] + z["offset"], 6.0, atol=z["scale"] / 2)
    assert pq[0, 0] == nd and (pq[1:, 1:] != nd).all()


def test_view3d_failure_never_fails_the_run(tmp_path, monkeypatch):
    """A view failure (forced) must not fail the run: the run returns, the
    result's files list and the uploaded files omit view.*, check.json and
    the gates are byte-for-byte what a run with a working view writes, and a
    one-line note is in the run log (run dir run.log)."""
    import view

    ok_dir, bad_dir = tmp_path / "ok", tmp_path / "bad"
    r_ok, f_ok, _ = _run_chain(ok_dir, monkeypatch)
    assert "view.bin" in r_ok["files"] and "view.bin" in f_ok

    def boom(*a, **k):
        raise RuntimeError("forced view failure")
    monkeypatch.setattr(view, "build_view", boom)
    r_bad, f_bad, _ = _run_chain(bad_dir, monkeypatch)
    assert "view.bin" not in r_bad["files"] and "view.json" not in r_bad["files"]
    assert "view.bin" not in f_bad and "view.json" not in f_bad
    assert r_bad["files"] == [f for f in r_ok["files"]
                              if f not in ("view.bin", "view.json")]
    assert _sha(f_bad["check.json"][0]) == _sha(f_ok["check.json"][0]), \
        "check.json changed when the view failed"
    assert r_bad["zmap"] == r_ok["zmap"], "gates changed when the view failed"
    log = open(os.path.join(str(bad_dir), "run.log")).read()
    assert "view: skipped (RuntimeError: forced view failure)" in log
