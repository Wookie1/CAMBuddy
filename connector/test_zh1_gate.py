"""ZH1 (entry_stock) is a runner gate, like the other zmap gates (panel
mutant MZ1: ZH1 removed from the gate list must turn this red).
(a) _check_zmap_gates refuses a check whose ONLY failing gate is
    entry_stock, with the entry_stock code and message; count 0 passes;
(b) a whole runner run (fake engine, fake zmap) whose zmap check reports
    entry_stock count > 0 and every other gate at 0 is REFUSED."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from runner import EngineError, _check_zmap_gates  # noqa: E402

ES_BAD = {"count": 11, "entries": 472, "max_mm": 17.609,
          "max_over_bar_mm": 17.109, "worst_xy": [1.0, 2.0],
          "first_line": 76936, "bar": "max(helix pitch, 0.5 mm)"}


def _check(es):
    return {
        "tool": {"type": "flat", "dia": 12.686, "corner": 0.0},
        "gouges": {"count": 0, "max_depth": 0.0},
        "rapid_collisions": {"count": 0, "first_line": None},
        "over_flute": {"count": 0, "max_depth": 0.0},
        "holder": {"status": "checked"},
        "holder_hits": {"count": 0, "max_intrusion": 0.0},
        "axial_plunges": {"count": 0, "max_depth_mm": 0.0,
                          "first_line": None, "worst_xy": None},
        "entry_stock": es,
    }


def test_entry_stock_is_a_runner_gate():
    with pytest.raises(EngineError) as ei:
        _check_zmap_gates(_check(dict(ES_BAD)))
    assert getattr(ei.value, "code", None) == "entry_stock", ei.value
    assert "11 entries start under standing stock" in str(ei.value)
    assert "first line 76936" in str(ei.value)
    _check_zmap_gates(_check(dict(ES_BAD, count=0, max_over_bar_mm=0.0,
                                  first_line=None, worst_xy=None)))


def test_run_with_entry_stock_is_refused(tmp_path, monkeypatch):
    import test_connector as tc
    run, _calls = tc.TestPostedUnitsRunner()._spawn(tmp_path, monkeypatch)
    import runner as runner_mod
    spawn = runner_mod.EngineRun._spawn

    def spawn_es(self, argv, lo, hi, on_progress, json_out=None,
                 extra_env=None):
        out = spawn(self, argv, lo, hi, on_progress, json_out, extra_env)
        a = list(argv)
        if "verify.zmap" in a:   # the zmap check: every gate 0 but ZH1
            p = a[a.index("--out-json") + 1]
            with open(p) as fh:
                check = json.load(fh)
            check["entry_stock"] = dict(ES_BAD)
            with open(p, "w") as fh:
                json.dump(check, fh)
        return out

    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn_es)
    with pytest.raises(EngineError) as ei:
        run.run_slope_split_finish(os.path.join(HERE, "unused.step"),
                                   dict(tc.SLOPE_GOOD_INPUTS,
                                        rest_tool_number=31))
    assert getattr(ei.value, "code", None) == "entry_stock", ei.value
    assert "entries start under standing stock" in str(ei.value)
