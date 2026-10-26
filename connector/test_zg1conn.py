"""zg1conn: the connector keeps the judge's stock bottom check alive.

(i) the runner merges its grid keys into stock_after_finish.json instead of
overwriting zmap's own sidecar (which carries the true stock_box the rest
judge needs); (ii) a below_stock_bottom "unknown" status becomes a review
item, stock_bottom_unchecked; (iii) no runner zmap call uses --window (a
speed-only option that leaves off-window cells unjudged).

Run: /opt/homebrew/bin/python3 -m pytest connector/test_zg1conn.py -q
"""
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import envelope  # noqa: E402
import runner as runner_mod  # noqa: E402
from test_toollib import PY, SLOPE, _fake_spawn  # noqa: E402

BOX = [-10.0, 10.0, -10.0, 10.0, -1.0, 0.4]


def _zmap_writes_box(calls):
    """_fake_spawn plus what the real zmap does on --stock-out: write the
    sidecar's stock_box, merging keys already there."""
    base = _fake_spawn(calls)

    def spawn(self, argv, *a, **k):
        base(self, argv, *a, **k)
        if "verify.zmap" in argv and "--stock-out" in argv:
            sc = os.path.splitext(argv[argv.index("--stock-out") + 1])[0] \
                + ".json"
            meta = json.load(open(sc)) if os.path.exists(sc) else {}
            meta["stock_box"] = BOX
            json.dump(meta, open(sc, "w"))
    return spawn


def test_stock_after_finish_sidecar_keeps_stock_box(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn",
                        _zmap_writes_box(calls))
    run = runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                               str(tmp_path / "run"))
    run.run_slope_split_finish(
        os.path.join(HERE, "testdata", "synth_pocket.step"),
        dict(SLOPE, rest_tool_number=31))
    with open(os.path.join(run.work, "stock_after_finish.json")) as fh:
        meta = json.load(fh)
    assert meta["stock_box"] == BOX, meta
    assert {"x0", "y0", "cell"} <= set(meta), meta
    zmaps = [a for a in calls if "verify.zmap" in a]
    assert len(zmaps) == 3 and not any("--window" in a for a in zmaps)


UNKNOWN = {"status": "unknown", "count": 0, "max_depth": 0.0,
           "worst_xy": None, "first_line": None,
           "reason": "stock bottom check NOT done: no --stock and no "
                     "stock_box in the --stock-in sidecar"}


def test_stock_bottom_unknown_is_review():
    ok = {"gouges": {"count": 0},
          "below_stock_bottom": {"count": 0, "max_depth": 0.0}}
    r = envelope.for_result("adaptive_rough", ok)
    assert r["verdict"] == "ready", r
    chain = {"chain": ["rough", "finish", "rest"], "rough": ok,
             "finish": ok, "rest": dict(ok, below_stock_bottom=UNKNOWN)}
    r = envelope.for_result("slope_split_finish", chain)
    assert r["verdict"] == "needs_review", r
    it = [a for a in r["attention"] if a["code"] == "stock_bottom_unchecked"]
    assert len(it) == 1 and it[0]["severity"] == "review"
    assert it[0]["where"] == {"program": "rest.nc"} and it[0]["next_step"]


def test_runner_source_never_passes_window():
    src = open(os.path.join(HERE, "runner.py")).read()
    assert not re.search(r"""["']--window["']""", src)
