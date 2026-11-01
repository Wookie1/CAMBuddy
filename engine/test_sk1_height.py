"""SK1 default (James 2026-10-31): all four stock faces clear, vise/fixture
avoidance by HEIGHT - side-entry descents never go below the finished
part's lowest Z (the runner passes --side-entry-min-z = part bbox zmin).
Runs the real prepare (freecadcmd) + engine.cli rough on box_off_centre
(40 x 20 x 10 mm, 1 mm side skin) with the runner's SK1 arguments;
runnable directly or under pytest from VibeCAD python."""
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

BOX = os.path.join(ROOT, "connector", "testdata", "box_off_centre.step")
TOOL_R = 6.343
FACES = "xneg,xpos,yneg,ypos"


def _rough(td, stock_bottom, floor_below_part):
    r = subprocess.run(
        [model.python311(), "-m", "engine.cli", "prepare", "--step", BOX,
         "--out-dir", td, "--stock-xy", "1", "--stock-top", "0.4",
         "--stock-bottom", str(stock_bottom), "--cell", "0.5",
         "--tool-r", str(TOOL_R)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    with open(os.path.join(td, "prepare.json")) as fh:
        prep = json.load(fh)
    zpart = prep["bbox"][4]
    floor = prep["stock"][4] if floor_below_part else zpart
    stats_p = os.path.join(td, "stats.json")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        cli.main(["rough", "--step", os.path.join(td, "model.step"),
                  "--stock", *["%.4f" % v for v in prep["stock"]],
                  "--tool", "flat:12.6860:0.0000",
                  "--out", os.path.join(td, "rough.nc"),
                  "--floor", "%.4f" % floor, "--leave", "0.381",
                  "--stepdown", "4.0", "--optimal-load-mm", "2.0",
                  "--stepup", "1.905", "--hf", prep["hf"],
                  "--min-rest", "0.5", "--cut-feed", "3429",
                  "--ramp-feed", "1270", "--spindle", "7500",
                  "--post", "lnc", "--program", "1", "--tool-number", "13",
                  "--stats-json", stats_p, "--metric", "--load-limit",
                  "--side-entry-clear", FACES,
                  "--side-entry-min-z", "%.4f" % zpart])
    with open(stats_p) as fh:
        return json.load(fh), err.getvalue(), zpart, floor


def _require_freecad():
    """Gate test: a missing VibeCAD freecadcmd is a FAILURE, never a skip."""
    assert os.path.exists(model.freecadcmd()), (
        "test_sk1_height needs VibeCAD's freecadcmd at %s - run with "
        "/Applications/VibeCAD.app/Contents/Resources/bin/python"
        % model.freecadcmd())


def _no_descent_below(stats, zpart):
    feeds = stats.get("sk1_feedin") or []
    assert all(r["z"] >= zpart - 1e-9 for r in feeds), \
        "side entry below the part bottom: %s" % [r["z"] for r in feeds]
    return feeds


def test_sk1_height_b_skins_cut_by_side_entry():
    """(b) floor at the part bottom: the 1 mm skins are cut by side entry
    (no skin_skipped, 0 plunges), no descent below the part bottom."""
    _require_freecad()
    with tempfile.TemporaryDirectory() as td:
        stats, err, zpart, _f = _rough(td, 0, False)
        feeds = _no_descent_below(stats, zpart)
        assert feeds, "no side entries"
        assert stats["skin_skipped"] == [], stats["skin_skipped"]
        assert stats["n_axial_plunge"] == 0
        assert "WARNING: thin skin" not in err
    print("PASS sk1_height_b: %d side entries (max ae %.3f load %.3f a %.3f),"
          " 0 skins, 0 plunges" % (len(feeds), stats["sk1_max_ae"],
                                   stats["sk1_max_load"], stats["sk1_max_a"]))


def test_sk1_height_c_nothing_below_part_bottom():
    """(c) floor 3 mm below the part bottom (stock where the jaws grip):
    no level below the part bottom cuts, no side entry descends below it,
    and no skin below it is reported (the part heightfield floors at the
    part's lowest Z, so that stock is never in a roughing region)."""
    _require_freecad()
    with tempfile.TemporaryDirectory() as td:
        stats, err, zpart, floor = _rough(td, 3, True)
        assert floor < zpart - 2.9
        _no_descent_below(stats, zpart)
        cut_below = [lv["z"] for lv in stats["levels"]
                     if lv["z"] < zpart - 1e-6 and lv.get("n_regions", 0)]
        assert not cut_below, "levels cut below the part bottom: %s" \
            % cut_below
        assert not [k for k in stats["skin_skipped"]
                    if k["z"] < zpart - 1e-6]
        assert stats["n_axial_plunge"] == 0
    print("PASS sk1_height_c: floor %.3f, part bottom %.3f, nothing cut "
          "below it" % (floor, zpart))


if __name__ == "__main__":
    test_sk1_height_b_skins_cut_by_side_entry()
    test_sk1_height_c_nothing_below_part_bottom()
    print("PASS test_sk1_height")
