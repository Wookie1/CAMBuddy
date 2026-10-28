#!/usr/bin/env python3
"""FL-LOAD red tests (run on the UNCHANGED code first).

(a) test_flload_corner_scene_load: a small synthetic corner/ring scene (flat
    12.686 tool, full-depth side cuts) whose BASE program shows windows with
    load > 1.2 under zmap --load-rule; with the feed limiter on, zmap reports
    0 windows with load > 1.2 beyond the floor_bound ones (each residual is
    verified to carry exactly the 25%-of-Fcut floor feed).
(b) test_flload_path_identity: flag on -> merge collinear consecutive feed
    moves of both programs; the XYZ polylines are identical within 1e-6 and
    no feed was ever raised.
(c) test_flload_off_byte_identical: engine.cli rough --help offers
    --load-limit; with the flag OFF the posted program bytes equal main's
    emitter output (moves_to_gcode on the very moves rough emitted) on two
    small scenes (option present-but-false and option absent).

Run (small-test lane, VibeCAD python):
    <lane> /Applications/VibeCAD.app/Contents/Resources/bin/python -c \
        "import sys; sys.path.insert(0,'.'); import engine.test_flload as t; t.<name>()"
"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")
sys.path.insert(0, os.path.join(ROOT, "verify"))

import numpy as np  # noqa: E402

import zmap  # noqa: E402 (tests may import verify; engine code must not)

DIA = 12.686
R = DIA / 2.0
CUT, RAMP = 3429.0, 1270.0
TOP, LEVEL, FLOORZ = 44.0, 25.146, 24.0   # a = 18.855 at LEVEL
LO, HI = 10.0, 30.0                        # square pocket in a 40x40 frame
CELL = 0.1
FLOOR_FEED = 0.25 * CUT                    # 857.25 feed floor
REF = 2.032 * 19.05 * CUT


def _scene_moves():
    """Pocket-corner scene: vertical plunge at the corner (16.343, 16.343),
    one full-depth SLOT pass along the y=10 wall (load >> 1.2: entry slot at
    a = 18.855), two diagonal full-depth SIDE-cut passes at 3.17 mm stepover
    (load > 1.2), then a full wall circuit (mostly below 1.2, so the cutting
    feed 3429 stays the program's dominant feed - the load rule's reference -
    after the limiter slows only the hot windows). Every wall-touching pass
    keeps its centre exactly R off the wall (16.343 / 23.657) so nothing
    gouges."""
    a, b = LO + R, HI - R
    return [
        {"g": 0, "x": a, "y": a, "z": TOP, "f": None},
        {"g": 1, "x": a, "y": a, "z": LEVEL, "f": RAMP},
        {"g": 1, "x": b, "y": a, "z": LEVEL, "f": CUT},
        {"g": 1, "x": a, "y": a + 3.17, "z": LEVEL, "f": CUT},
        {"g": 1, "x": b, "y": a + 6.34, "z": LEVEL, "f": CUT},
        {"g": 1, "x": b, "y": b, "z": LEVEL, "f": CUT},
        {"g": 1, "x": a, "y": b, "z": LEVEL, "f": CUT},
        {"g": 1, "x": a, "y": a, "z": LEVEL, "f": CUT},
        {"g": 1, "x": b, "y": a, "z": LEVEL, "f": CUT},
    ]


def _post(moves):
    from engine.gcode import moves_to_gcode
    return moves_to_gcode(moves, spindle_rpm=7500,
                          tool_comment="T1 flat D=%.3f CR=%.3f" % (DIA, 0.0))


def _judge(text):
    """zmap --load-rule over the posted program: flat DIA tool, pocket part.
    Returns (n_windows_load_gt_1.2, list of them as {ae_eff, a, feed, load})."""
    n = int(round(40.0 / CELL))
    xs = (np.arange(n) + 0.5) * CELL
    X, Y = np.meshgrid(xs, xs)
    part = np.where((X >= LO) & (X <= HI) & (Y >= LO) & (Y <= HI),
                    FLOORZ, TOP)
    gmv = zmap.parse_gcode(text)
    old = zmap.LOAD_RULE
    zmap.LOAD_RULE = True
    try:
        res = zmap.simulate(gmv, part, CELL, 0.0, 0.0,
                            (0.0, 40.0, 0.0, 40.0, 20.0, TOP),
                            tool="flat", dia=DIA, engage_report=True)
    finally:
        zmap.LOAD_RULE = old
    wins = zmap._ae2_windows(res["_ae2_move_raw"])
    zmap._ae2_engagement_keys(wins, DIA, load_rule=True)  # sets w["load"]
    hot = [{"ae_eff": w["ae_eff"], "a": round(w["a"], 4),
            "feed": w.get("feed"), "load": w["load"]}
           for w in wins if w["load"] > 1.2]
    return len(hot), hot


def test_flload_corner_scene_load():
    """FL-LOAD red (a): base scene shows load > 1.2 windows (paste count and
    max); with the limiter 0 remain beyond floor_bound (residuals verified to
    carry exactly the floor feed)."""
    try:
        from engine import load_limit
    except ImportError as e:
        raise AssertionError("engine.load_limit missing on main (%s)" % e)
    base = _scene_moves()
    n_base, hot_base = _judge(_post(base))
    mx = max((h["load"] for h in hot_base), default=0.0)
    print("flload(a) BASE: %d windows with load > 1.2, max load %.4f "
          "(loads %s)" % (n_base, mx, [h["load"] for h in hot_base]))
    assert n_base > 0, "scene must show load > 1.2 windows on the base"
    slowed, stats = load_limit.limit_feeds(
        base, DIA, 0.0, (0.0, 40.0, 0.0, 40.0), TOP, CUT)
    print("flload(a) limiter stats: %s" % (stats,))
    n_after, hot_after = _judge(_post(slowed))
    print("flload(a) AFTER: %d windows with load > 1.2 (floor_bound=%d), "
          "loads %s feeds %s" % (n_after, stats["floor_bound"],
                                 [h["load"] for h in hot_after],
                                 [h["feed"] for h in hot_after]))
    for h in hot_after:
        # F words post as integers (F%.0f), so the floor feed reads +/- 0.5
        assert abs(h["feed"] - FLOOR_FEED) <= 0.51, \
            "residual load %.3f window at feed %.2f is NOT floor_bound" % (
                h["load"], h["feed"])
    assert n_after == stats["floor_bound"], \
        "%d windows still load > 1.2 after limiting, only %d are " \
        "floor_bound" % (n_after, stats["floor_bound"])
    # one margin for trigger and target (coordinator): windows the engine
    # reads in (1.2*MARGIN, 1.2] are slowed as well, so >= the judge's count
    assert stats["windows_slowed"] >= n_base, \
        "limiter slowed %d windows but the base had %d over-limit ones" % (
            stats["windows_slowed"], n_base)
    assert stats["windows_slowed"] > 0 and stats["mm_slowed"] > 0.0


def _polyline(moves, tol=1e-6):
    """Modal XYZ polyline of a move list with consecutive COLLINEAR feed
    points merged (a point is dropped when it lies on the segment joining
    its neighbours within tol)."""
    pts, pos = [], (0.0, 0.0, 0.0)
    for mv in moves:
        cur = tuple(pos[i] if mv.get(k) is None else mv[k]
                    for i, k in enumerate("xyz"))
        if "x" in mv or "y" in mv or "z" in mv:
            pts.append(cur)
        pos = cur

    def near(p, a, b):
        # distance of p to segment a-b
        ab = [b[k] - a[k] for k in range(3)]
        L2 = sum(v * v for v in ab)
        t = 0.0 if L2 <= 0 else max(
            0.0, min(1.0, sum((p[k] - a[k]) * ab[k]
                              for k in range(3)) / L2))
        return math.sqrt(sum((p[k] - a[k] - t * ab[k]) ** 2
                             for k in range(3)))
    out = list(pts)
    changed = True
    while changed:
        changed = False
        for i in range(1, len(out) - 1):
            if near(out[i], out[i - 1], out[i + 1]) <= tol:
                out.pop(i)
                changed = True
                break
    return out


def test_flload_path_identity():
    """FL-LOAD red (b): flag on -> merged-collinear XYZ polylines identical
    within 1e-6; only F words change and no feed is ever raised."""
    try:
        from engine import load_limit
    except ImportError as e:
        raise AssertionError("engine.load_limit missing on main (%s)" % e)
    base = _scene_moves()
    slowed, stats = load_limit.limit_feeds(
        base, DIA, 0.0, (0.0, 40.0, 0.0, 40.0), TOP, CUT)
    pa, pb = _polyline(base), _polyline(slowed)
    assert len(pa) == len(pb), \
        "polyline vertex count differs: %d vs %d" % (len(pa), len(pb))
    for i, (p, q) in enumerate(zip(pa, pb)):
        d = math.sqrt(sum((p[k] - q[k]) ** 2 for k in range(3)))
        assert d <= 1e-6, "vertex %d moved %.3e mm" % (i, d)
    n_f = 0
    for mv0, mv1 in zip(base, slowed):
        for k in ("g", "x", "y", "z"):
            assert mv0.get(k) == mv1.get(k), \
                "move field %s changed: %r -> %r" % (
                    k, mv0.get(k), mv1.get(k))
        if mv0.get("f"):
            assert mv1["f"] <= mv0["f"] + 1e-9, \
                "feed raised %.1f -> %.1f" % (mv0["f"], mv1["f"])
            n_f += 1
    assert stats["windows_slowed"] > 0, "nothing slowed: vacuous test"
    print("flload(b) PASS: %d XYZ vertices identical (<=1e-6), %d feed "
          "moves, min feed %.1f" % (len(pa), n_f, stats["min_feed"]))


def _run_cli_rough(pocket, extra_argv, cache):
    """Run engine.cli rough on a synthetic pocket scene (model patched, like
    test_rrstock2); cache the moves rough emitted so the caller can compare
    the posted bytes with main's emitter output on the SAME moves."""
    import engine.rough as R
    from engine import cli as climod
    from engine import model as emod
    from engine.test_engine import _rr1b_pocket_scene
    from engine.gcode import moves_to_gcode
    emod.step_to_stl = lambda step, *a, **k: step
    surf, stock_hf, lo, hi = _rr1b_pocket_scene(pocket)
    emod.load_surf = lambda stl: surf
    real = R.rough

    def spy(*args, **kw):
        mv, st = real(*args, **kw)
        cache["moves"] = mv
        return mv, st
    R.rough = spy
    try:
        with tempfile.TemporaryDirectory() as td:
            ngc = os.path.join(td, "rough.ngc")
            rc = climod.main(
                ["rough", "--step", "synth.step",
                 "--stock", "0", "40", "0", "40", "20", "30",
                 "--tool", "flat:%.3f" % DIA, "--out", ngc,
                 "--floor", "24.0", "--workers", "1"] + extra_argv)
            assert rc == 0, "cli rough rc=%d" % rc
            with open(ngc) as fh:
                text = fh.read()
    finally:
        R.rough = real
    expect = moves_to_gcode(cache["moves"], spindle_rpm=7500,
                            tool_comment="T1 flat D=%.3f CR=%.3f" % (DIA, 0.0))
    return text, expect


def test_flload_off_byte_identical():
    """FL-LOAD red (c): --load-limit exists; flag OFF -> posted bytes equal
    main's emitter output on the same moves, on two small scenes."""
    import subprocess
    r = subprocess.run([sys.executable, "-m", "engine.cli", "rough",
                        "--help"], cwd=ROOT, capture_output=True, text=True)
    assert any(ln.strip().startswith("--load-limit")
               for ln in r.stdout.splitlines()), \
        "engine.cli rough has no --load-limit flag (rc=%d)" % r.returncode
    for pocket in ((10.0, 30.0), (12.0, 28.0)):
        cache = {}
        text_off, expect = _run_cli_rough(pocket, ["--no-load-limit"], cache)
        assert text_off == expect, \
            "rough without the option: posted bytes differ from main's " \
            "emitter output (scene %s)" % (pocket,)
        cache2 = {}
        text_false, expect2 = _run_cli_rough(pocket, ["--no-load-limit"],
                                             cache2)
        assert text_false == expect2 == expect, \
            "flag-off output differs between runs (scene %s)" % (pocket,)
        n_moves = len(cache["moves"])
        n_f = sum(1 for m in cache["moves"] if m.get("f"))
        print("flload(c) PASS scene %s: %d moves (%d feed), flag-off bytes "
              "identical to main's emitter output (%d bytes)"
              % (pocket, n_moves, n_f, len(text_off)))


def test_flload_trigger_margin():
    """FL-LOAD margin (coordinator): a window the engine reads at load 1.19
    (under 1.2, over 1.2 x MARGIN) is slowed to 1.2 x MARGIN; one at 1.10
    is left alone. The window is injected (engine windowing stubbed)."""
    from engine import load_limit as ll
    cut = 3429.0
    ref = ll.DESIGN_AE * ll.DESIGN_STEPDOWN * cut
    moves = [{"g": 0, "x": 0.0, "y": 0.0, "z": 50.0},
             {"g": 1, "x": 10.0, "y": 0.0, "z": 50.0, "f": cut},
             {"g": 1, "x": 20.0, "y": 0.0, "z": 50.0, "f": cut}]

    def win(idx, load):
        a = ll.DESIGN_STEPDOWN
        return {"area_mm2": load * ref / (a * cut), "length_mm": 1.0, "a": a,
                "feed": cut, "helix_pitch": None, "move_idxs": [idx]}
    real = ll._windows
    ll._windows = lambda recs: [win(1, 1.19), win(2, 1.10)]
    try:
        out, stats = ll.limit_feeds(moves, 12.686, 0.0, (0.0, 20.0, -5.0, 5.0),
                                    50.0, cut)
    finally:
        ll._windows = real
    want = cut * ll.LOAD_MAX * ll.MARGIN / 1.19
    print("flload(m): load 1.19 -> F %.1f (want %.1f), load 1.10 -> F %.1f, "
          "stats %s" % (out[1]["f"], want, out[2]["f"], stats))
    assert abs(out[1]["f"] - want) < 1e-6, \
        "load 1.19 window feed %.1f, want %.1f (slowed to 1.2 x MARGIN)" % (
            out[1]["f"], want)
    assert out[2]["f"] == cut, "load 1.10 window was slowed to %.1f" % (
        out[2]["f"])
    assert stats["windows_slowed"] == 1
