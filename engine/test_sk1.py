#!/usr/bin/env python3
"""SK1 tests: thin side-skin entry from the air outside the stock.

Synthetic block (James's Core Front class): stock (9,51,9,51,0,20), a
12.7-bull r0.127 tool, part = flange box [10,50]^2 z 10..19 with a shaft
[10.3,49.7]^2 z 0..10 - every level below the flange top skin is a ring
region of ~1.3 mm stock around the part wall. On main's code the ring entry
counts as an axial plunge (no in-box descent column, no helix fits a
1.3 mm skin) and the run aborts; with --side-entry-clear faces + a flute the
SK1 air-column class must descend OUTSIDE a listed face and feed in with
the flank, load-checked like the bands.

Run standalone with VibeCAD python:
    /Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_sk1.py
"""
import contextlib
import hashlib
import io
import json
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")

try:
    import area  # noqa: F401
except ImportError as e:   # gate test: a missing area module FAILS, never skips
    raise ImportError(
        "test_sk1 needs VibeCAD's area module - run with "
        "/Applications/VibeCAD.app/Contents/Resources/bin/python (%s)" % e)
HAVE_AREA = True

from engine.rough import rough  # noqa: E402
from engine.gcode import moves_to_gcode  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB_STL = os.path.join(ROOT, "out", "test_block.stl")
TB_BASE = os.path.join(ROOT, "out", "sk1_tb_baseline.ngc")
RUNA_JSON = os.path.join(ROOT, "out", "sk1_runA.json")

# synthetic ring-skin block (mirrors James: 1 mm stock all round, flange)
STOCK = (9.0, 51.0, 9.0, 51.0, 0.0, 20.0)
TOOL_R, CORNER_R, FLUTE = 6.35, 0.127, 31.75
ALL_FACES = "xneg,xpos,yneg,ypos"
SPIKE_MM = 2.44
LOAD_MAX = 1.2
SYN_KW = dict(leave=0.381, axial_leave=0.381, stepdown=19.05, stepup=1.905,
              stepover=0.16, tolerance=0.05, threads=4, stock_cell=0.5,
              min_rest=1.0, corner_r=CORNER_R)


def _box(x0, x1, y0, y1, z0, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
         (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
         (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [(v[a], v[b], v[c]) for a, b, c in f]


def _synth_stl():
    d = os.path.join(ROOT, "out", "sk1")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "skin.stl")
    if not os.path.exists(path):
        tris = _box(10.0, 50.0, 10.0, 50.0, 10.0, 19.0)      # flange
        tris += _box(10.3, 49.7, 10.3, 49.7, 0.0, 10.0)      # shaft
        with open(path, "w") as fh:
            fh.write("solid s\n")
            for (p, q, r) in tris:
                fh.write(" facet normal 0 0 0\n  outer loop\n")
                for v in (p, q, r):
                    fh.write("   vertex %.4f %.4f %.4f\n" % v)
                fh.write("  endloop\n endfacet\n")
            fh.write("endsolid s\n")
    return path


# M2: SK1 needs the tool's holder; the synthetic runs use T13's table
# holder (BT30-ER32-70, max radius 27) at its 71.6 mm stick-out, which
# clears this 19 mm part everywhere (test_m2_holder covers the limit).
SYN_HOLDER = (27.0, 71.6)


def _synth_rough(mod=None, **kw):
    if mod is None:
        kw.setdefault("side_entry_holder", SYN_HOLDER)
    from opencamlib import ocl
    stl = _synth_stl()
    surf = ocl.STLSurf()
    ocl.STLReader(stl, surf)
    return (mod or rough)(surf, STOCK, TOOL_R, 0.0, stl_path=stl, **SYN_KW,
                          **kw)


def _plunge_count(exc):
    msg = str(exc)
    assert "axial-plunge FAILED" in msg, "unexpected failure: %s" % msg[:200]
    st = getattr(exc, "stats", None)
    if st is not None:
        return st["n_axial_plunge"], st
    return int(msg.split("FAILED: ")[1].split(" ")[0]), None


def _synth_plunge(mod=None, **kw):
    try:
        _moves, stats = _synth_rough(mod, **kw)
    except RuntimeError as e:
        return _plunge_count(e)
    return stats["n_axial_plunge"], stats


def _main_rough_mod():
    """Today's code = main's engine/rough.py (this branch only adds docs on
    top of main), loaded side by side under its own module name. Written
    INSIDE the engine package (engine/_sk1_rough_main.py, removed at exit)
    so the rough()'s spawned worker processes can import it too."""
    import atexit
    import importlib.util
    import subprocess
    src = subprocess.run(["git", "-C", ROOT, "show", "main:engine/rough.py"],
                         capture_output=True, text=True, check=True).stdout
    path = os.path.join(ROOT, "engine", "_sk1_rough_main.py")
    with open(path, "w") as fh:
        fh.write(src)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))
    spec = importlib.util.spec_from_file_location("engine._sk1_rough_main",
                                                 path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["engine._sk1_rough_main"] = mod
    spec.loader.exec_module(mod)
    return mod.rough


def _beyond(sx, sy, r):
    out = set()
    if sx >= STOCK[1] + r:
        out.add("xpos")
    if sx <= STOCK[0] - r:
        out.add("xneg")
    if sy >= STOCK[3] + r:
        out.add("ypos")
    if sy <= STOCK[2] - r:
        out.add("yneg")
    return out


# ------------------------------------------------------------------- tests
def test_sk1_air_entry_all_faces():
    """All four faces open + a flute: the ring-skin block roughs to
    completion with ZERO axial plunges, side entries used, and every
    air-column feed-in within the load gates (ae <= 2.44, load <= 1.2,
    a <= flute), its descent column beyond a LISTED face by >= tool_r."""
    assert HAVE_AREA, "run with VibeCAD python"
    moves, stats = _synth_rough(side_entry_faces=ALL_FACES, flute_mm=FLUTE)
    assert stats["n_axial_plunge"] == 0, \
        "axial plunges remain: %d %s" % (stats["n_axial_plunge"],
                                         stats.get("axial_pts", [])[:6])
    assert stats["n_side_entries"] > 0, "no side entries emitted"
    feeds = stats.get("sk1_feedin") or []
    assert feeds, "side entries did not come from the air-column class"
    for rec in feeds:
        sx, sy = rec["col"]
        b = _beyond(sx, sy, TOOL_R)
        assert b and b <= set(ALL_FACES.split(",")), \
            "descent column %s not beyond a listed face by tool_r" % rec
        assert rec["ae"] <= SPIKE_MM + 1e-9, "ae over bar: %r" % rec
        assert rec["load"] <= LOAD_MAX + 1e-9, "load over bar: %r" % rec
        assert rec["a"] <= FLUTE + 1e-9, "engagement over flute: %r" % rec
    print("SK1 all-faces: %d air feed-ins, max ae=%.3f max load=%.3f "
          "max a=%.3f (flute %.2f), side entries=%d"
          % (len(feeds), stats["sk1_max_ae"], stats["sk1_max_load"],
             stats["sk1_max_a"], FLUTE, stats["n_side_entries"]))


def test_sk1_no_faces_today_behaviour():
    """NO faces listed (jaws/clamps may sit at any face): no air-column
    descent and no side-entry move anywhere, with or without a flute length
    (the class stays OFF). Baseline changed with SKN: the ring is a true thin
    skin, left standing in skin_skipped with its warning, so the run
    completes with 0 axial plunges instead of failing the plunge gate."""
    assert HAVE_AREA, "run with VibeCAD python"
    for kw in ({}, {"flute_mm": FLUTE}):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _moves, stats = _synth_rough(**kw)
        assert not stats.get("sk1_feedin"), \
            "air-column descent with no faces listed %s: %s" \
            % (kw, stats["sk1_feedin"][:3])
        assert stats["n_side_entries"] == 0, \
            "side entry with no faces listed %s: %d" \
            % (kw, stats["n_side_entries"])
        skins = stats["skin_skipped"]
        assert skins, "ring skin not in skin_skipped %s" % kw
        assert err.getvalue().count("WARNING: thin skin") == len(skins)
        assert stats["n_axial_plunge"] == 0, stats.get("axial_pts")
    print("SK1 no-faces: 0 side/air entries, %d skins warned, 0 plunges "
          "(class OFF)" % len(skins))


def test_sk1_partial_faces():
    """Only xpos open: air entries may only descend beyond xpos - no
    descent column lies beyond an UNLISTED face (jaws/clamps may sit at
    the closed faces). Baseline changed with SKN: the skins at the other
    faces are left standing in skin_skipped (warned) instead of aborting
    the run on the plunge gate."""
    assert HAVE_AREA, "run with VibeCAD python"
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        _moves, stats = _synth_rough(side_entry_faces="xpos", flute_mm=FLUTE)
    feeds = stats.get("sk1_feedin") or []
    for rec in feeds:
        sx, sy = rec["col"]
        assert "xpos" in _beyond(sx, sy, TOOL_R), \
            "descent column not beyond the only listed face: %r" % rec
        assert not (_beyond(sx, sy, TOOL_R) - {"xpos"}), \
            "descent column beyond an unlisted face: %r" % rec
    assert stats["n_axial_plunge"] == 0, stats.get("axial_pts")
    skins = stats["skin_skipped"]
    assert skins, "other faces' skins not in skin_skipped"
    assert err.getvalue().count("WARNING: thin skin") == len(skins)
    print("SK1 xpos-only: %d xpos feed-ins accepted, %d skins left at the "
          "other faces, 0 plunges" % (len(feeds), len(skins)))


def test_sk1_side_entry_min_z():
    """--side-entry-min-z: at or above it the air entries run; a level
    below it gets NO air-column entry. Baseline changed with SKN: that
    level's ring is left standing in skin_skipped (warned) instead of
    failing the plunge gate."""
    assert HAVE_AREA, "run with VibeCAD python"
    _moves, stats = _synth_rough(side_entry_faces=ALL_FACES,
                                 flute_mm=FLUTE, side_entry_min_z=0.381)
    assert stats["n_axial_plunge"] == 0
    feeds = stats.get("sk1_feedin") or []
    assert feeds and min(r["z"] for r in feeds) < 0.9, \
        "no lowest-level air entry: %s" % [r["z"] for r in feeds]
    assert all(r["z"] >= 0.381 - 1e-9 for r in feeds)
    # min_z above the final floor level: that level may not air-enter
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        _moves, st = _synth_rough(side_entry_faces=ALL_FACES, flute_mm=FLUTE,
                                  side_entry_min_z=0.881)
    feeds2 = st.get("sk1_feedin") or []
    assert all(r["z"] >= 0.881 - 1e-9 for r in feeds2), \
        "air entry below min_z: %s" % [r["z"] for r in feeds2]
    assert st["n_axial_plunge"] == 0, st.get("axial_pts")
    low = [k for k in st["skin_skipped"] if k["z"] < 0.881]
    assert low, "the level below min_z is not in skin_skipped: %s" \
        % [k["z"] for k in st["skin_skipped"]]
    assert err.getvalue().count("WARNING: thin skin") == \
        len(st["skin_skipped"])
    print("SK1 min-z: %d entries >= 0.381; with min_z=0.881 no entry below "
          "it, %d skins left below it" % (len(stats["sk1_feedin"]), len(low)))


def _tb_program(mod=None):
    """The test block rough program with today's args, no SK1 inputs."""
    import numpy as np
    from opencamlib import ocl
    if not os.path.exists(TB_STL):
        from engine import model
        shutil.copy(model.step_to_stl(os.path.join(ROOT, "samples",
                                                   "test_block.step"),
                                      tol=0.01), TB_STL)
    surf = ocl.STLSurf()
    ocl.STLReader(TB_STL, surf)
    # GR (gap relink) is default ON by design and changes this program; the
    # guard is "SK1 off == main", so both sides run with GR off (main's
    # rough.py ignores the variable).
    old_gr = os.environ.get("ENGINE_GAP_RELINK")
    os.environ["ENGINE_GAP_RELINK"] = "0"
    # LR1 / AF off (coordinator-approved edit, 2026-11-06): this test pins
    # main's pre-LR1 behaviour; LR1 and AF are default ON and change the
    # program it compares
    old_lr = {k: os.environ.get(k) for k in ("CAMBUDDY_LR1",
                                             "CAMBUDDY_AIR_FEED")}
    os.environ["CAMBUDDY_LR1"] = "0"
    os.environ["CAMBUDDY_AIR_FEED"] = "0"
    try:
        moves, stats = (mod or rough)(surf, (-50.0, 50.0, -40.0, 40.0, 0.0,
                                             38.0),
                                      6.343, 20.0, leave=0.381,
                                      axial_leave=0.381, stepdown=19.05,
                                      final_zmin=20.381, stepover=0.16,
                                      tolerance=0.05, threads=4,
                                      stock_cell=0.5, min_rest=1.0,
                                      corner_r=0.0, stl_path=TB_STL)
    finally:
        if old_gr is None:
            os.environ.pop("ENGINE_GAP_RELINK", None)
        else:
            os.environ["ENGINE_GAP_RELINK"] = old_gr
        for k, v in old_lr.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert stats["n_axial_plunge"] == 0
    return "\n".join(moves_to_gcode(moves)) + "\n"


def test_sk1_tb_program_unchanged():
    """Unchanged elsewhere: with no --side-entry-clear the test block rough
    program is byte-identical to main (baseline captured pre-edit, or main's
    rough.py loaded side by side)."""
    assert HAVE_AREA, "run with VibeCAD python"
    gc = _tb_program()
    if os.path.exists(TB_BASE):
        base = open(TB_BASE).read()
        src = "out/sk1_tb_baseline.ngc"
    else:
        base = _tb_program(_main_rough_mod())
        src = "git show main:engine/rough.py"
    assert gc == base, "test block program changed vs %s (md5 %s != %s)" % (
        src, hashlib.md5(gc.encode()).hexdigest(),
        hashlib.md5(base.encode()).hexdigest())
    print("SK1 tb-unchanged: test block program byte-identical to main "
          "(md5 %s)" % hashlib.md5(gc.encode()).hexdigest())


if __name__ == "__main__":
    for fn in (test_sk1_air_entry_all_faces,
               test_sk1_no_faces_today_behaviour,
               test_sk1_partial_faces,
               test_sk1_side_entry_min_z,
               test_sk1_tb_program_unchanged):
        print("== %s" % fn.__name__, flush=True)
        fn()
        print("PASS %s" % fn.__name__, flush=True)
    print("SK1-ALL-PASS", flush=True)
