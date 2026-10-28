"""RR-STOCK2 item 3 (red): the rest pass's --rest-from is PINNED to the
engine's own replay file (stock_after_finish_engine*), never a zmap stock
file (M2: pointing it back at zmap's stock_after_finish.npy must fail here).

Unit test: the runner's subprocesses are faked (test_toollib._fake_spawn);
no engine, no zmap. Run through the small-test lane:
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_rrstock2.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
import test_toollib as tl  # noqa: E402

PY = "/opt/homebrew/bin/python3"


def test_rrstock2_rest_from_is_engine_replay(tmp_path, monkeypatch):
    """the rest finish's --rest-from must be the finish's own engine
    --stock-out file (stock_after_finish_engine.npy) - never zmap's
    stock_after_finish.npy (mutation M2)."""
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", tl._fake_spawn(calls))
    cfg = {"engine_python": PY, "repo_root": REPO}
    run = runner_mod.EngineRun(cfg, str(tmp_path))
    run.run_slope_split_finish(os.path.join(HERE, "unused.step"),
                               dict(tl.SLOPE, rest_tool_number=31))
    fin = [a for a in calls if "engine.cli" in a
           and a[a.index("engine.cli") + 1] == "finish"
           and "--rest-from" not in a][0]
    rest_fin = [a for a in calls if "engine.cli" in a
                and a[a.index("engine.cli") + 1] == "finish"
                and "--rest-from" in a][0]
    rest_from = rest_fin[rest_fin.index("--rest-from") + 1]
    base = os.path.basename(rest_from)
    assert base != "stock_after_finish.npy", \
        "the rest pass plans on zmap's judge stock %s - RR-STOCK says the " \
        "engine replays its own finish" % base
    assert base.startswith("stock_after_finish_engine"), \
        "rest-from is %r, want the engine replay stock_after_finish_engine*" \
        % base
    # and it is EXACTLY the file the finish's --stock-out exports
    assert rest_from == fin[fin.index("--stock-out") + 1], \
        "rest-from %s is not the finish's --stock-out" % rest_from
