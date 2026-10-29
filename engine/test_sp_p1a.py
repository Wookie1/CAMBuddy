"""SP-P1A: rough --load-limit --stock-out writes load_limit's own final
stock instead of a second entry_depth.replay_stock pass. Proof: on a small
synthetic flat-tool rough the new path and the forced old path
(STEVECAM_FORCE_REPLAY=1) write byte-identical .npy, .json and .nc.
Runs the CLI with VibeCAD python (opencamlib + area); runnable directly or
under pytest from any python."""
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402

STEP = os.path.join(ROOT, "connector", "testdata", "synth_pocket.step")


def _rough(td, tag, force):
    out = os.path.join(td, tag)
    env = dict(os.environ, ENGINE_WORKERS="4")
    env.pop("STEVECAM_FORCE_REPLAY", None)
    if force:
        env["STEVECAM_FORCE_REPLAY"] = "1"
    r = subprocess.run(
        [model.python311(), "-m", "engine.cli", "rough", "--step", STEP,
         "--stock", "-31", "31", "-31", "31", "-1", "12.4",
         "--tool", "flat:6.0:0.0", "--floor", "3.0", "--leave", "0.381",
         "--stepdown", "4.0", "--stepup", "1.905", "--min-rest", "0.5",
         "--load-limit", "--out", out + ".nc", "--stock-out", out + ".npy"],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, "rough %s failed:\n%s" % (tag, r.stderr[-2000:])
    one = "from load_limit's replay" in r.stdout
    assert one == (not force), "%s: wrong stock path taken" % tag
    return out


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_sp_p1a_one_replay_matches_forced_replay():
    if not os.path.exists(model.python311()):
        import pytest
        pytest.skip("VibeCAD python missing")
    with tempfile.TemporaryDirectory() as td:
        new = _rough(td, "new", force=False)
        old = _rough(td, "old", force=True)
        a, b = np.load(new + ".npy"), np.load(old + ".npy")
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        assert a.shape == b.shape, "shape %s vs %s" % (a.shape, b.shape)
        assert same.all(), "stock differs in %d cells" % int((~same).sum())
        assert _read(new + ".npy") == _read(old + ".npy"), ".npy bytes differ"
        assert _read(new + ".json") == _read(old + ".json"), ".json differs"
        assert _read(new + ".nc") == _read(old + ".nc"), ".nc differs"
        print("PASS sp_p1a: stock %s byte-identical (.npy/.json/.nc)"
              % (a.shape,))


if __name__ == "__main__":
    test_sp_p1a_one_replay_matches_forced_replay()
