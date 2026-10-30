"""SP-P3A: the pooled island precompute equals the serial path exactly.

Runs the test-block rough three times in-process (VibeCAD python; also
pytest-compatible under any python that can import `area`):
  pooled  - every pooled z is re-computed serially here (level_islands with
            the rough's own thread count) and must be identical
            (forbidden loops ==, Fm np.array_equal);
  off     - STEVECAM_NO_ISLAND_POOL=1: no pool, stats island_pool == 0;
  miss    - a cache missing half the levels: those levels fall back to the
            serial call in the loop.
All three programs must be byte-identical."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model, cli  # noqa: E402  (model: VibeCAD lib path)
from engine import rough as R  # noqa: E402

TB = ["--step", os.path.join(ROOT, "samples", "test_block.step"),
      "--stock", "-50", "50", "-40", "40", "0", "38", "--tool", "flat:12.686",
      "--floor", "20", "--leave", "0.381", "--final-zmin", "20.381",
      "--stepdown", "19.05", "--optimal-load-mm", "2.032"]


def _rough(td, tag, env=None):
    out = os.path.join(td, tag + ".nc")
    st = os.path.join(td, tag + ".json")
    old = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    try:
        cli.main(["rough"] + TB + ["--out", out, "--stats-json", st])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    import json
    with open(out, "rb") as fh, open(st) as fs:
        return fh.read(), json.load(fs)


def test_sp_p3a_pool_equals_serial():
    import numpy as np
    orig_pre, orig_li = R.precompute_islands, R.level_islands
    checked, mism, serial_calls = [], [], []

    def spy_pre(stl_path, zs, tool_r, leave, corner_r, Zg, xs, ys, axl,
                **kw):
        cache, n = orig_pre(stl_path, zs, tool_r, leave, corner_r, Zg, xs,
                            ys, axl, **kw)
        surf = model.load_surf(stl_path)
        cut = R.big_cutter(tool_r, leave, corner_r)
        for z, (isl, Fm) in cache.items():
            s_isl, s_Fm = orig_li(surf, cut, Zg, xs, ys, z, axl, threads=8)
            checked.append(z)
            if s_isl != isl or not np.array_equal(s_Fm, Fm):
                mism.append((z, sum(1 for a, b in zip(s_isl, isl) if a != b)
                             + abs(len(s_isl) - len(isl)),
                             int((s_Fm != Fm).sum())
                             if s_Fm.shape == Fm.shape else -1))
        return cache, n

    with tempfile.TemporaryDirectory() as td:
        R.precompute_islands = spy_pre
        try:
            nc_pool, st_pool = _rough(td, "pool")
        finally:
            R.precompute_islands = orig_pre
        assert checked, "pool never ran"
        assert not mism, "pooled != serial islands at %d levels: %s" % (
            len(mism), mism[:5])
        assert st_pool["island_pool"] > 0, st_pool.get("island_pool")

        nc_off, st_off = _rough(td, "off", {"STEVECAM_NO_ISLAND_POOL": "1"})
        assert st_off["island_pool"] == 0
        assert nc_off == nc_pool, "env off-switch program differs"

        def half_pre(*a, **kw):
            cache, n = orig_pre(*a, **kw)
            drop = sorted(cache)[::2]
            for z in drop:
                del cache[z]
            return cache, n

        def count_li(*a, **kw):
            serial_calls.append(a[5])
            return orig_li(*a, **kw)
        R.precompute_islands, R.level_islands = half_pre, count_li
        try:
            nc_miss, _ = _rough(td, "miss")
        finally:
            R.precompute_islands, R.level_islands = orig_pre, orig_li
        assert serial_calls, "cache miss never fell back to the serial call"
        assert nc_miss == nc_pool, "cache-miss program differs"
    print("PASS sp_p3a: %d pooled levels == serial; off-switch and cache-miss "
          "(%d serial calls) programs identical" % (len(checked),
                                                     len(serial_calls)))


if __name__ == "__main__":
    test_sp_p3a_pool_equals_serial()
