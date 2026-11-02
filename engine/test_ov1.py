"""OV1: the --load-limit feed limiter runs in a spawn worker while rough's
closing clcheck runs (verify-and-fallback). On synth_pocket (prepare as
engine/test_sp_hf1b.py, rough in-process through engine.cli.main):
(a) overlap on == overlap off (--ll-overlap 0) byte for byte, and on uses the
    worker result;
(b) the worker given moves that differ from what rough returns -> fallback,
    program == off;
(c) the worker raising -> inline, program == off;
(d) a heavy scene where the limiter really slows feeds: on == off, and a
    raising worker yields the LIMITED program (never the unlimited one).
Runnable directly or under pytest from VibeCAD python."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402
from engine import cli  # noqa: E402

STEP = os.path.join(ROOT, "connector", "testdata", "synth_pocket.step")


def _prepare(td):
    assert os.path.exists(model.freecadcmd()), (
        "test_ov1 needs VibeCAD's freecadcmd at %s - run with "
        "/Applications/VibeCAD.app/Contents/Resources/bin/python"
        % model.freecadcmd())
    r = subprocess.run(
        [model.python311(), "-m", "engine.cli", "prepare", "--step", STEP,
         "--out-dir", td, "--stock-xy", "8", "--stock-top", "1",
         "--stock-bottom", "0", "--cell", "0.5", "--tool-r", "3.0"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    with open(os.path.join(td, "prepare.json")) as fh:
        return json.load(fh)


def _rough(prep, td, tag, overlap, heavy=False, limit=True):
    out = os.path.join(td, "ov_%s.ngc" % tag)
    sj = os.path.join(td, "ov_%s.json" % tag)
    with contextlib.redirect_stdout(io.StringIO()):
        cli.main(["rough", "--step", STEP, "--stock",
                  *[str(v) for v in prep["stock"]], "--tool", "flat:6.0",
                  "--out", out, "--floor", "3.0", "--leave", "0.381",
                  "--axial-leave", "0.381",
                  "--stepdown", "8.0" if heavy else "4.0",
                  "--stepup", "1.905",
                  "--optimal-load-mm", "6.0" if heavy else "2.0",
                  "--tolerance", "0.05", "--min-rest", "0.5",
                  "--stock-cell", "0.5", "--hf", prep["hf"],
                  "--stats-json", sj,
                  "--load-limit" if limit else "--no-load-limit",
                  "--stock-out", os.path.join(td, "ov_%s.npy" % tag),
                  "--ll-overlap", str(overlap)])
    with open(out, "rb") as fh, open(sj) as fj:
        return fh.read(), json.load(fj)


def _boom(*a, **k):
    """Stands in for limit_feeds_pickled inside the worker (by name)."""
    raise RuntimeError("ov1 test: worker failure")


def test_ov1_overlap():
    from engine import load_limit
    from engine import rough as R
    with tempfile.TemporaryDirectory() as td:
        prep = _prepare(td)
        ngc_off, st_off = _rough(prep, td, "off", 0)
        assert st_off["ll_overlap"]["started"] == 0, st_off["ll_overlap"]
        # (a)
        ngc_on, st_on = _rough(prep, td, "on", 1)
        assert st_on["ll_overlap"] == {"started": 1, "used": 1,
                                       "fallback": 0, "error": 0}, \
            st_on["ll_overlap"]
        assert ngc_on == ngc_off, "overlap on/off programs differ"
        # (b) the worker sees one move fewer than rough returns
        orig = R.rough

        def short(*a, **kw):
            cb = kw.get("on_moves")
            if cb is not None:
                kw["on_moves"] = lambda mv: cb(mv[:-1])
            return orig(*a, **kw)
        R.rough = short
        try:
            ngc_b, st_b = _rough(prep, td, "b", 1)
        finally:
            R.rough = orig
        assert st_b["ll_overlap"]["fallback"] == 1 \
            and st_b["ll_overlap"]["used"] == 0, st_b["ll_overlap"]
        assert ngc_b == ngc_off, "fallback program differs from off"
        # (c) the worker raises
        origp = load_limit.limit_feeds_pickled
        load_limit.limit_feeds_pickled = _boom
        try:
            ngc_c, st_c = _rough(prep, td, "c", 1)
        finally:
            load_limit.limit_feeds_pickled = origp
        assert st_c["ll_overlap"]["error"] >= 1 \
            and st_c["ll_overlap"]["used"] == 0, st_c["ll_overlap"]
        assert ngc_c == ngc_off, "worker-error program differs from off"
    print("PASS ov1: on == off byte for byte (worker used), mismatch -> "
          "fallback, worker error -> inline")


def test_ov1_limiter_acts():
    """(d) a scene where the limiter really slows feeds (optimal load 6.0,
    stepdown 8.0): the limited program differs from the unlimited one in F
    words; overlap on == off; a worker that raises -> the inline limiter's
    program (never the unlimited one) == off."""
    from engine import load_limit
    with tempfile.TemporaryDirectory() as td:
        prep = _prepare(td)
        ngc_off, st_off = _rough(prep, td, "hoff", 0, heavy=True)
        ngc_un, _st = _rough(prep, td, "hun", 0, heavy=True, limit=False)
        a, b = ngc_off.splitlines(), ngc_un.splitlines()
        assert len(a) == len(b), (len(a), len(b))
        n_f = sum(1 for x, y in zip(a, b) if x != y)
        assert n_f > 0, "the limiter slowed nothing in the heavy scene"
        ngc_on, st_on = _rough(prep, td, "hon", 1, heavy=True)
        assert st_on["ll_overlap"]["used"] == 1, st_on["ll_overlap"]
        assert ngc_on == ngc_off, "heavy: overlap on != off"
        origp = load_limit.limit_feeds_pickled
        load_limit.limit_feeds_pickled = _boom
        try:
            ngc_c, st_c = _rough(prep, td, "hc", 1, heavy=True)
        finally:
            load_limit.limit_feeds_pickled = origp
        assert st_c["ll_overlap"]["error"] >= 1, st_c["ll_overlap"]
        n_c = sum(1 for x, y in zip(ngc_c.splitlines(), a) if x != y)
        assert ngc_c == ngc_off, \
            "heavy worker error: %d lines differ from the limited program" % n_c
    print("PASS ov1 (d): limiter slows %d lines in the heavy scene; on == "
          "off; worker error -> inline limiter, == off" % n_f)


if __name__ == "__main__":
    test_ov1_overlap()
    test_ov1_limiter_acts()
