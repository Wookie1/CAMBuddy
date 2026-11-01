"""SKN: the rough's thin skins left standing reach check.json under
left_for_hole_op_or_another_setup.rough - and ONLY when there is one (no
skins -> the key is absent, check.json unchanged). Canned step outputs via
test_spp3c's fake _spawn; no engine runs."""
import json
import os

import runner as runner_mod
from test_spp3c import STEP, _cfg, make_fake, step_name
from test_connector import SLOPE_GOOD_INPUTS

SKIN = {"faces": ["xpos"], "area_mm2": 88.0, "max_thickness_mm": 1.0,
        "x": 133.119, "y": 64.422, "z": 21.066}


def _with_skins(fake, skins):
    def f(self, argv, *a, **k):
        r = fake(self, argv, *a, **k)
        if step_name(argv) == "rough" and skins:
            sj = argv[list(argv).index("--stats-json") + 1]
            with open(sj) as fh:
                st = json.load(fh)
            st["skin_skipped"] = skins
            with open(sj, "w") as fh:
                json.dump(st, fh)
        return r
    return f


def _chain_check(tmp_path, monkeypatch, skins):
    fake, _rec = make_fake()
    monkeypatch.setattr(runner_mod.EngineRun, "_spawn",
                        _with_skins(fake, skins))
    work = str(tmp_path / ("skins" if skins else "none"))
    run = runner_mod.EngineRun(_cfg(), work)
    run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
    with open(os.path.join(work, "check.json")) as fh:
        return json.load(fh)


def test_skn_chain_check_lists_rough_skins(tmp_path, monkeypatch):
    c = _chain_check(tmp_path, monkeypatch, [SKIN])
    assert c["left_for_hole_op_or_another_setup"]["rough"] == [SKIN]


def test_skn_chain_check_no_skins_no_key(tmp_path, monkeypatch):
    c = _chain_check(tmp_path, monkeypatch, [])
    assert "rough" not in c["left_for_hole_op_or_another_setup"]


def test_rough_skins_reader(tmp_path):
    p = tmp_path / "s.json"
    assert runner_mod._rough_skins(str(p)) == []          # missing file
    p.write_text(json.dumps({"n_moves": 3}))
    assert runner_mod._rough_skins(str(p)) == []
    p.write_text(json.dumps({"skin_skipped": [SKIN]}))
    assert runner_mod._rough_skins(str(p)) == [SKIN]
