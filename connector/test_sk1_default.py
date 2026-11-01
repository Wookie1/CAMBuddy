"""SK1 default (James 2026-10-31): every rough the runner runs, chain and
single, lists all four stock faces as clear and caps side-entry descents at
the finished part's lowest Z (prepare.json bbox zmin) - vise/fixture
avoidance by height. Canned step outputs via test_spp3c's fake _spawn."""
import json
import os

import runner as runner_mod
from test_spp3c import STEP, _cfg, make_fake, step_name
from test_connector import GOOD_INPUTS, SLOPE_GOOD_INPUTS

PART_ZMIN = -0.6


def _with_bbox(fake):
    def f(self, argv, *a, **k):
        r = fake(self, argv, *a, **k)
        if step_name(argv) == "prepare":
            p = os.path.join(self.work, "prepare.json")
            with open(p) as fh:
                prep = json.load(fh)
            prep["bbox"] = [-9.0, 9.0, -9.0, 9.0, PART_ZMIN, 0.0]
            with open(p, "w") as fh:
                json.dump(prep, fh)
        return r
    return f


def _check(argv):
    a = list(argv)
    assert a[a.index("--side-entry-clear") + 1] == "xneg,xpos,yneg,ypos"
    assert float(a[a.index("--side-entry-min-z") + 1]) == PART_ZMIN


def test_chain_rough_argv_all_faces_min_z_part_bottom(tmp_path, monkeypatch):
    fake, rec = make_fake()
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _with_bbox(fake))
    run = runner_mod.EngineRun(_cfg(), str(tmp_path / "c"))
    run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
    _check(rec["argv"]["rough"])


def test_single_rough_argv_all_faces_min_z_part_bottom(tmp_path, monkeypatch):
    fake, rec = make_fake()
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn", _with_bbox(fake))
    run = runner_mod.EngineRun(_cfg(), str(tmp_path / "s"))
    run.run(STEP, dict(GOOD_INPUTS))
    _check(rec["argv"]["rough"])


def test_no_part_bottom_no_side_entry():
    assert runner_mod._side_entry_args({"stock": [0] * 6}) == []
