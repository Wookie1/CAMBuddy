"""PL1: the rough pass-opener Adaptive2d pool (verify-and-fallback).

(a) the opener rule, unit-tested on a hand-made order list;
(b) pool on vs off on the BS1d drop scene (the config of
    engine/test_engine.py test_bs1d_a2d_drop_counted, unedited) and on
    synth_pocket via engine.cli prepare + rough with engine/test_sp_hf1b.py's
    prepare arguments: pool off is today's all-inline path (byte-identical
    programs, same gates), pool on gives the same gates and uses the pooled
    result where the scene has a second opener;
(c) fallback: a precomputed input made to differ (a point dropped from a
    precomputed outer) -> the loop must discard the pooled result, run the
    level inline, and the program must equal the pool-off program;
(d) a pooled job that raises in the worker -> inline, same program.

Small synthetic/TB scenes only; runnable directly with the VibeCAD python
(opencamlib + area) or under pytest."""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402

STEP = os.path.join(ROOT, "connector", "testdata", "synth_pocket.step")


def test_pl1_pass_opener_rule():
    """(a) a pass opener (after the first) has Z lower than every level
    before it in `order`; equal Z is not lower."""
    from engine.rough import _pass_openers
    assert _pass_openers([42.4, 42.9, 47.2, 35.3, 36.4, 25.1, 27.0]) \
        == [35.3, 25.1]
    assert _pass_openers([]) == []
    assert _pass_openers([42.354]) == []
    assert _pass_openers([5.0, 5.0, 4.0, 4.5, 3.0]) == [4.0, 3.0]
    assert _pass_openers([3.0, 4.0, 5.0]) == []
    print("PASS pl1 opener rule")


def _bs1d_rough(pool_env, **kw_over):
    """The BS1d drop scene of test_bs1d_a2d_drop_counted, config unedited;
    pool_env: "0" off, "1" on (ENGINE_A2D_POOL around the call)."""
    old = os.environ.pop("ENGINE_A2D_POOL", None)
    os.environ["ENGINE_A2D_POOL"] = str(pool_env)
    try:
        from opencamlib import ocl
        from engine.rough import rough
        from engine.test_engine import _box_tris, _write_stl
        bt = _box_tris
        tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
                + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
                + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "bs1d_drop.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            kw = dict(leave=0.381, axial_leave=0.381, stepdown=19.05,
                      stepup=1.905, tolerance=0.05, threads=4,
                      stock_cell=0.5, min_rest=0.5, corner_r=0.0,
                      stl_path=stl)
            kw.update(kw_over)
            return rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0),
                         6.343, 0.0, **kw)
    finally:
        os.environ.pop("ENGINE_A2D_POOL", None)
        if old is not None:
            os.environ["ENGINE_A2D_POOL"] = old


def test_pl1_bs1d_pool_on_off():
    """(b) BS1d scene: pool off == pool on byte for byte (the scene has no
    second opener, so no pool is even created); the BS1d gates hold."""
    moves_off, st_off = _bs1d_rough(0)
    moves_on, st_on = _bs1d_rough(1)
    assert json.dumps(moves_off) == json.dumps(moves_on), \
        "BS1d pool on/off programs differ"
    for st in (st_off, st_on):
        assert isinstance(st.get("a2d_spnf"), int) and st["a2d_spnf"] >= 1
        dropped = st.get("a2d_dropped_outers")
        assert isinstance(dropped, list) and len(dropped) == 1
        assert st.get("n_band_regions", 0) >= 1
        assert st.get("clcheck_violations", 0) == 0
        assert st.get("n_axial_plunge", 0) == 0
        assert st["pl1"]["openers"] == 0 and st["pl1"]["used"] == 0 \
            and st["pl1"]["precomputed"] == 0 and st["pl1"]["fallback"] == 0
    print("PASS pl1 bs1d pool on/off (byte-identical, gates hold)")


def _prepare(td, tool_r=3.0):
    """engine.cli prepare with engine/test_sp_hf1b.py's exact arguments."""
    r = subprocess.run(
        [model.python311(), "-m", "engine.cli", "prepare",
         "--step", STEP, "--out-dir", td, "--stock-xy", "8",
         "--stock-top", "1", "--stock-bottom", "0", "--cell", "0.5",
         "--tool-r", str(tool_r)],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    with open(os.path.join(td, "prepare.json")) as fh:
        return json.load(fh)


def _rough_cli(prep, td, tag, pool):
    """synth_pocket rough via engine.cli; pool: "0" env-off, "flag"
    --a2d-pool 0, "on" default. Returns (ngc bytes, stats dict)."""
    out = os.path.join(td, "synth_%s.ngc" % tag)
    sj = os.path.join(td, "synth_%s_stats.json" % tag)
    cmd = [model.python311(), "-m", "engine.cli", "rough", "--step", STEP,
           "--stock"] + [str(v) for v in prep["stock"]] + [
        "--tool", "flat:6.0", "--out", out, "--floor", "3.0",
        "--leave", "0.381", "--axial-leave", "0.381", "--stepdown", "4.0",
        "--stepup", "1.905", "--optimal-load-mm", "2.0", "--tolerance",
        "0.05", "--min-rest", "0.5", "--stock-cell", "0.5",
        "--hf", prep["hf"], "--stats-json", sj]
    env = dict(os.environ)
    env.pop("ENGINE_A2D_POOL", None)
    if pool == "0":
        env["ENGINE_A2D_POOL"] = "0"
    elif pool == "flag":
        cmd += ["--a2d-pool", "0"]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, "rough %s failed:\n%s" % (tag, r.stderr[-2000:])
    with open(out, "rb") as fh:
        ngc = fh.read()
    with open(sj) as fh:
        return ngc, json.load(fh)


def test_pl1_synth_pool_on_off():
    """(b) synth_pocket: pool off (env and --a2d-pool 0) is the all-inline
    path, byte-identical programs; pool on keeps the gates (no axial plunge,
    clcheck 0) and uses the pooled result (the scene has a second opener)."""
    assert os.path.exists(model.freecadcmd()), (
        "test_pl1 needs VibeCAD's freecadcmd at %s - run with "
        "/Applications/VibeCAD.app/Contents/Resources/bin/python"
        % model.freecadcmd())
    with tempfile.TemporaryDirectory() as td:
        prep = _prepare(td)
        ngc_off, st_off = _rough_cli(prep, td, "off", "0")
        ngc_flag, st_flag = _rough_cli(prep, td, "flag", "flag")
        ngc_on, st_on = _rough_cli(prep, td, "on", "on")
        assert ngc_off == ngc_flag, "--a2d-pool 0 != ENGINE_A2D_POOL=0"
        assert st_off["pl1"]["openers"] >= 2, \
            "scene lost its second opener: %r" % (st_off["pl1"],)
        for st in (st_off, st_flag):
            assert st["pl1"]["used"] == 0 and st["pl1"]["precomputed"] == 0 \
                and st["pl1"]["fallback"] == 0, st["pl1"]
            assert st.get("clcheck_violations", 0) == 0
            assert st.get("n_axial_plunge", 0) == 0
        assert st_on["pl1"]["used"] >= 1, \
            "pool on never used a precomputed result: %r" % (st_on["pl1"],)
        assert st_on.get("clcheck_violations", 0) == 0
        assert st_on.get("n_axial_plunge", 0) == 0
        same = ngc_off == ngc_on
        print("PASS pl1 synth pool on/off: used=%d fallback=%d openers=%d "
              "(pool-on program %s the pool-off one)"
              % (st_on["pl1"]["used"], st_on["pl1"]["fallback"],
                 st_on["pl1"]["openers"],
                 "byte-identical to" if same else "differs from (allowed: "
                 "a2d link budget is clock-based)"))


def test_pl1_fallback_uses_inline_result():
    """(c) one precomputed input made to differ (a point dropped from the
    precomputed outer of the only pooled opener): the loop must take the
    fallback (inline a2d with the true inputs) and the program must equal
    the pool-off program byte for byte."""
    from engine import rough as roughmod
    from engine.stock import StockField
    ref_moves, ref_st = _bs1d_rough(0, stepdown=8.0)
    assert ref_st["pl1"]["openers"] == 1, ref_st["pl1"]
    assert ref_st["pl1"]["used"] == 0 and ref_st["pl1"]["fallback"] == 0

    orig_po = roughmod._pass_openers
    orig_contours = StockField.contours
    state = {"n": 0}

    def debased_contours(self, m):
        outers, holes = orig_contours(self, m)
        state["n"] += 1
        if state["n"] == 1 and outers and len(outers[0]) > 8:
            # the opener's PRECOMPUTE call (armed inside _pass_openers,
            # before the loop): drop a point from its first outer
            outers = [list(outers[0])[:-1]] + list(outers[1:])
        return outers, holes

    def po(order):
        StockField.contours = debased_contours   # arm before the precompute
        return orig_po(order)

    roughmod._pass_openers = po
    try:
        moves, st = _bs1d_rough(1, stepdown=8.0)
    finally:
        roughmod._pass_openers = orig_po
        StockField.contours = orig_contours
    assert state["n"] >= 2, "debase wrapper never saw the loop's contours"
    assert st["pl1"]["openers"] == 1 and st["pl1"]["precomputed"] == 1, \
        st["pl1"]
    assert st["pl1"]["fallback"] >= 1, \
        "no fallback taken: %r" % (st["pl1"],)
    assert st["pl1"]["used"] == 0, st["pl1"]
    assert json.dumps(moves) == json.dumps(ref_moves), \
        "fallback program differs from the pool-off program"
    assert st.get("clcheck_violations", 0) == 0
    assert st.get("n_axial_plunge", 0) == 0
    print("PASS pl1 fallback: differing precomputed input discarded, inline "
          "result byte-identical to pool-off")


def _boom(job):
    """Stands in for _a2d_pool_job inside the spawned worker (pickled by
    name): every pooled job raises."""
    raise RuntimeError("pl1 test: worker failure")


def test_pl1_worker_failure_falls_back():
    """(d) R1: a pooled job that raises in the worker must not fail the
    rough: the level runs inline (error counted, nothing used) and the
    program equals the pool-off program byte for byte."""
    from engine import rough as roughmod
    ref_moves, _ref_st = _bs1d_rough(0, stepdown=8.0)
    orig = roughmod._a2d_pool_job
    roughmod._a2d_pool_job = _boom
    try:
        moves, st = _bs1d_rough(1, stepdown=8.0)
    finally:
        roughmod._a2d_pool_job = orig
    assert st["pl1"]["precomputed"] == 1, st["pl1"]
    assert st["pl1"]["error"] >= 1 and st["pl1"]["used"] == 0, st["pl1"]
    assert json.dumps(moves) == json.dumps(ref_moves), \
        "worker-failure program differs from the pool-off program"
    assert st.get("clcheck_violations", 0) == 0
    assert st.get("n_axial_plunge", 0) == 0
    print("PASS pl1 worker failure: inline fallback, byte-identical to "
          "pool-off")


if __name__ == "__main__":
    fails = 0
    for fn in (test_pl1_pass_opener_rule, test_pl1_bs1d_pool_on_off,
               test_pl1_synth_pool_on_off,
               test_pl1_fallback_uses_inline_result,
               test_pl1_worker_failure_falls_back):
        t0 = time.time()
        try:
            fn()
            print("PASS %s (%.1f s)" % (fn.__name__, time.time() - t0),
                  flush=True)
        except Exception as e:   # noqa: BLE001
            fails += 1
            print("FAIL %s (%.1f s): %s: %s" % (fn.__name__,
                                                time.time() - t0,
                                                type(e).__name__,
                                                str(e)[:500]), flush=True)
    print("PL1 TESTS DONE fails=%d" % fails)
    sys.exit(1 if fails else 0)
