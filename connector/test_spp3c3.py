"""SP-P3C: EngineRun.kill_all / live_pgids, the connector's shutdown
backstop. One REAL child with a REAL grandchild per chain (test_spp3c2's
harness); kill_all() from another thread must leave no pid alive within
2 s; live_pgids() is non-empty while both children run and empty after."""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
from test_spp3c import _cfg  # noqa: E402
from test_spp3c2 import STEP, gone, make_spawn, read_pids  # noqa: E402
from test_connector import SLOPE_GOOD_INPUTS  # noqa: E402


def test_kill_all_and_live_pgids(tmp_path, monkeypatch):
    pf_e, pf_j = str(tmp_path / "engine.pid"), str(tmp_path / "judge.pid")
    spawn, _rec = make_spawn(
        long={"finish": pf_e, "zmap_rough": pf_j},
        grandchild=("finish", "zmap_rough"),
        durations={"hf01": 0.05, "rough": 0.3, "tess": 0.01})
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
    run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))
    box = {}

    def watcher():
        box["pairs"] = [read_pids(pf_e), read_pids(pf_j)]
        box["live"] = run.live_pgids()
        box["t_kill"] = time.time()
        run.kill_all()

    def do_run():
        try:
            run.run_slope_split_finish(
                STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
        except BaseException as e:      # noqa: BLE001
            box["exc"] = e

    w, r = threading.Thread(target=watcher), threading.Thread(target=do_run)
    w.start()
    r.start()
    r.join(90)
    w.join(60)
    assert not r.is_alive() and not w.is_alive()
    assert len(box["live"]) >= 2, "live_pgids during the run: %r" % box["live"]
    pids = [p for pair in box["pairs"] for p in pair if p]
    assert len(pids) == 4, "expected 2 children + 2 grandchildren"
    for pid in pids:
        t = gone(pid, 2.0)
        assert t is not None and t <= box["t_kill"] + 2.0, \
            "pid %s survived kill_all() for 2 s" % pid
    assert run.live_pgids() == [], "live_pgids not empty after the run"
    print("PASS kill_all: 4 pids gone within 2 s; live_pgids %d -> 0"
          % len(box["live"]))
