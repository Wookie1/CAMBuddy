"""LR1 (--lr1 / CAMBUDDY_LR1) and AF (--air-feed / CAMBUDDY_AIR_FEED), both
default ON (James, 2026-11-06; off: --no-lr1 / --no-air-feed or env = 0). LR1: the LVA helix start takes its swept-disk stock top from
fine (0.1 mm) point heights - the engine's own milling convention evaluated
at points through a segment index - found by branch and bound over the
upper-bound layer U. AF: helix moves above the fine stock top over the disk
widened by AF_BAND_MM (+ AF_GUARD_MM) run at the cutting feed.
(1) U is an upper bound of the independent 0.1 mm replay
    (entry_depth.replay_stock) on random scenes, flat and bull;
(2) branch and bound equals brute force over every candidate cell on random
    scenes, including queries where the highest-U cell is not the answer;
(3) a centre-sampled over-clear beside a wall (the Floor 0 line-82903 /
    TB-sliver mechanism): the 0.5 mm grid reads the cut height, the fine top
    keeps the sliver, and the LVA start stays high;
(4) a coarse over-read (a tall cell whose centre is inside the dilated scan
    but whose stock lies outside the swept disk): the fine top is lower and
    so is the start;
(5) AF: a sliver just outside r + R is caught by the band - the switch sits
    above it (ramp feed there);
(6) the query cap falls back to today's start and ramp feed (program == OFF);
(7) the BS1d scene, judged by zmap at 0.1 mm: gates 0 incl. entry_stock, no
    cutting-feed descent removes stock, engagement no worse, cycle lower;
(8) ON is the default; OFF (flags or env) is main's program (pinned hash);
    flags parse.
Runnable directly or under pytest from VibeCAD python."""
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)

CUT, RAMP = 3429.0, 1270.0
# main's program on the BS1d scene (sha256 of the move list, first 16 hex;
# main 65727a9, engine == df60a95): LR1 and AF OFF must reproduce it
MAIN_BS1D_SHA16 = "d9091c2b946f26aa"
# the BS1d scene and its zmap judge (as in the parked HS1 / AF1 tests)
STOCK = (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0)


def _scene_rough(**kw):
    from opencamlib import ocl
    from engine.rough import rough
    from engine.test_engine import _box_tris as bt, _write_stl
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "lr1.stl")
        _write_stl(stl, tris)
        surf = ocl.STLSurf()
        ocl.STLReader(stl, surf)
        return rough(surf, STOCK, 6.343, 0.0, leave=0.381, axial_leave=0.381,
                     stepdown=19.05, stepup=1.905, tolerance=0.05, threads=4,
                     stock_cell=0.5, min_rest=0.5, corner_r=0.0, stl_path=stl,
                     side_entry_holder=(25.0, 71.6), **kw)


def _judge(moves, cell=0.1):
    """zmap CLI (verify/, independent of the engine), as the runner calls it
    for a rough: gates, entry_stock, cycle and the engagement block."""
    x0, y0 = -48.0, -38.0
    nx, ny = int(round(96.0 / cell)), int(round(76.0 / cell))
    X, Y = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell,
                       y0 + (np.arange(ny) + 0.5) * cell)
    inb = (np.abs(X) <= 40) & (np.abs(Y) <= 30)
    tall = ((X <= -30) | (X >= 30) | (Y <= -25) | (Y >= 25)) | \
        ((np.abs(X) <= 11) & (np.abs(Y) <= 6))
    part = np.where(inb, np.where(tall, 14.0, 0.0), -1.0)
    with tempfile.TemporaryDirectory() as td:
        np.save(os.path.join(td, "p.npy"), part)
        with open(os.path.join(td, "p.json"), "w") as fh:
            json.dump({"cell": cell, "x0": x0, "y0": y0, "tess_tol": 0.01}, fh)
        lines = ["G21 G90"]
        for mv in moves:
            w = ["G0" if mv["g"] == 0 else "G1"]
            w += ["%s%.4f" % (k.upper(), mv[k]) for k in ("x", "y", "z")
                  if mv.get(k) is not None]
            if mv["g"] == 1 and mv.get("f"):
                w.append("F%.1f" % mv["f"])
            lines.append(" ".join(w))
        with open(os.path.join(td, "p.nc"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
        subprocess.check_call(
            [sys.executable, "-m", "verify.zmap", os.path.join(td, "p.nc"),
             "--part", os.path.join(td, "p.npy"), "--tool", "flat",
             "--dia", "12.686", "--stock"] + ["%g" % v for v in STOCK]
            + ["--flute", "50.8", "--optimal-load", "2.032",
               "--engage-max", "2.4384", "--out-json",
               os.path.join(td, "c.json")], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(td, "c.json")) as fh:
            return json.load(fh)


GATES = ("gouges", "rapid_collisions", "axial_plunges", "over_flute",
         "outside_grid", "entry_stock", "below_stock_bottom")
ENG = ("overload_feeds", "overload_feeds_ae2", "full_width_slots",
       "full_width_slots_ae2_cutting_feed", "full_width_slots_ae2_entry_feed")


def _eng(c):
    e = c.get("engagement") or {}
    v = {k: (e.get(k) or {}).get("count") for k in ENG}
    v["ae2_max"] = (e.get("ae2") or {}).get("max")
    v["ae2_p99"] = (e.get("ae2") or {}).get("p99")
    return v






def _field(top=50.0, box=(-30.0, 30.0, -30.0, 30.0, 0.0, 50.0)):
    from engine.stock import StockField
    st = StockField(box, cell=0.5)
    st.top[:] = np.where(st.inb, top, -np.inf)
    st.set_tool(6.343)
    st.lr_enable()
    return st


def _brute(st, cx, cy, rad, z):
    """every candidate cell evaluated exactly (no pruning)"""
    c, f = st.cell, st.LR_FINE
    best = -np.inf
    n = int(round(c / f))
    off = (np.arange(n) - (n - 1) / 2.0) * f
    for j in range(st.ny):
        for i in range(st.nx):
            x = st.x0 + (i + 0.5) * c
            y = st.y0 + (j + 0.5) * c
            if math.hypot(max(abs(x - cx) - c / 2, 0),
                          max(abs(y - cy) - c / 2, 0)) > rad:
                continue
            if not np.isfinite(st.U[j, i]):
                continue
            if st.part is not None and st.part[j, i] > z:
                continue
            px = (x + off)[None, :].repeat(n, 0).ravel()
            py = (y + off)[:, None].repeat(n, 1).ravel()
            inn = np.hypot(np.maximum(np.abs(px - cx) - f / 2, 0),
                           np.maximum(np.abs(py - cy) - f / 2, 0)) <= rad
            if inn.any():
                best = max(best, float(st.lr_point_heights(
                    px[inn], py[inn], (j, i)).max()))
    return best


def test_lr1_upper_bound_vs_fine_replay():
    """(1) U >= the independent 0.1 mm replay (replay_stock) over every
    fine cell of every coarse cell, on random flat and bull scenes."""
    from engine import entry_depth as ed
    rng = np.random.default_rng(7)
    worst = np.inf
    for sc in range(6):
        R = float(rng.uniform(0.6, 3.0))
        cr = 0.0 if sc % 2 == 0 else min(0.4, R / 2)
        st = _field(top=20.0, box=(-8.0, 8.0, -8.0, 8.0, 0.0, 20.0))
        mv, pos = [], None
        for _k in range(40):
            a = rng.uniform(-9, 9, 2)
            b = a + rng.uniform(-4, 4, 2)
            zc = float(rng.uniform(2, 18))
            st.mill_segment(a[0], a[1], b[0], b[1], zc, R, cr)
            mv += [{"g": 0, "x": a[0], "y": a[1], "z": zc},
                   {"g": 1, "x": b[0], "y": b[1], "z": zc}]
        with tempfile.TemporaryDirectory() as td:
            F, fx0, fy0, fc = ed.replay_stock(mv, 2 * R, cr,
                                              os.path.join(td, "f.npy"),
                                              box=(-8.0, 8.0, -8.0, 8.0),
                                              top_z=20.0)
        fxs = fx0 + (np.arange(F.shape[1]) + 0.5) * fc
        fys = fy0 + (np.arange(F.shape[0]) + 0.5) * fc
        for j in range(st.ny):
            for i in range(st.nx):
                if not np.isfinite(st.U[j, i]):
                    continue
                x0c = st.x0 + i * st.cell
                y0c = st.y0 + j * st.cell
                ii = np.nonzero((fxs > x0c) & (fxs < x0c + st.cell))[0]
                jj = np.nonzero((fys > y0c) & (fys < y0c + st.cell))[0]
                if not len(ii) or not len(jj):
                    continue
                sub = F[np.ix_(jj, ii)]
                sub = sub[np.isfinite(sub)]
                if sub.size:
                    worst = min(worst, float(st.U[j, i] - sub.max()))
                    assert st.U[j, i] >= sub.max() - 1e-6, \
                        ("U under the fine replay", sc, j, i,
                         float(st.U[j, i]), float(sub.max()))
    print("PASS lr1 U >= 0.1 mm replay on 6 random scenes (min margin %.4f)"
          % worst)


def test_lr1_branch_and_bound_matches_brute_force():
    """(2) lr_disk_top == brute force; some queries have a highest-U cell
    whose exact value is not the answer (pruning order matters)."""
    rng = np.random.default_rng(11)
    n_q, n_order = 0, 0
    for sc in range(5):
        st = _field(top=20.0, box=(-8.0, 8.0, -8.0, 8.0, 0.0, 20.0))
        for _k in range(120):
            a = rng.uniform(-9, 9, 2)
            b = a + rng.uniform(-3, 3, 2)
            st.mill_segment(a[0], a[1], b[0], b[1], float(rng.uniform(1, 19)),
                            float(rng.uniform(0.3, 0.9)))
        for _q in range(8):
            cx, cy = rng.uniform(-5, 5, 2)
            rad = float(rng.uniform(1.0, 4.0))
            got, ev = st.lr_disk_top(cx, cy, rad, 0.0, cap=10 ** 6)
            want = _brute(st, cx, cy, rad, 0.0)
            assert abs(got - want) < 1e-9, ("B&B != brute", sc, got, want)
            n_q += 1
            n_order += int(ev > 1)
    assert n_order >= 3, ("pruning order never exercised", n_order)
    print("PASS lr1 branch and bound == brute force on %d queries (%d needed"
          " more than one exact cell)" % (n_q, n_order))


def _overclear_scene(dy_helix):
    """Stock 50; two passes at Z36 (R 6.343). The upper pass runs 6.29 below
    a cell-centre row yc: that row's centres are inside R by 0.053, so the
    0.5 mm grid marks the row cut to 36, while points 0.1-0.2 mm above the
    centres stand at 50 - a sliver beside the pass edge. The helix (r 3.17)
    is centred dy_helix below yc."""
    st = _field()
    R, z = 6.343, 30.0
    j = st._cj(5.0)
    yc = st.y0 + (j + 0.5) * st.cell
    for yl in (yc - 6.29, yc - 6.29 - 12.0, yc - 6.29 - 24.0):
        st.mill_segment(-29.0, yl, 29.0, yl, 36.0, R)
    r = 3.17
    c = (0.0, yc - dy_helix)
    s = (c[0], c[1] - r)
    return st, c, r, s, z, yc


def test_lr1_overclear_keeps_start_high():
    """(3) the 0.5 mm grid under-reads the sliver (36); the fine top keeps it
    (50) and the LVA start stays above it."""
    from engine.rough import _lva_start, _cut_top_max
    R = 6.343
    st, c, r, s, z, yc = _overclear_scene(9.4)
    coarse = _cut_top_max(st, c[0], c[1],
                          r + R + st.cell * math.sqrt(2) / 2, z)
    fine, ev = st.lr_disk_top(c[0], c[1], r + R, z)
    assert abs(coarse - 36.0) < 1e-9, ("grid should read the cut", coarse)
    assert fine is not None and abs(fine - 50.0) < 1e-9, ("sliver lost", fine)
    zs_f = _lva_start(st, c[0], c[1], r, s, z, R, 1.0, (25.0, 71.6),
                      disk_top=fine)
    zs_c = _lva_start(st, c[0], c[1], r, s, z, R, 1.0, (25.0, 71.6))
    assert zs_f is not None and zs_f >= 51.0 - 1e-9, zs_f
    assert zs_c is not None and zs_c < 40.0, zs_c
    print("PASS lr1 over-clear: grid %.3f, fine %.3f (%d cells); start %.3f"
          " (grid start %.3f)" % (coarse, fine, ev, zs_f, zs_c))


def test_lr1_overread_lowers_start():
    """(4) a tall cell whose centre is inside the dilated scan (r + R +
    cell*sqrt(2)/2) but whose square does not meet the swept disk: the grid
    counts it, the fine top does not, the start is lower."""
    from engine.rough import _lva_start, _cut_top_max
    R, r, z = 6.343, 3.17, 30.0
    st = _field()
    # milled region x <= 5.0 at Z36 (passes along Y); cells from x 5.0 on
    # stand at 50 (centre 5.25 is 6.593 from the last pass line)
    for xl in (5.0 - R, 5.0 - R - 12.0, 5.0 - R - 24.0, 5.0 - R - 36.0):
        st.mill_segment(xl, -29.0, xl, 29.0, 36.0, R)
    rad = r + R
    c = (4.95 - rad, 0.25)      # the disk ends at x 4.95
    s = (c[0] - r, c[1])
    coarse = _cut_top_max(st, c[0], c[1],
                          rad + st.cell * math.sqrt(2) / 2, z)
    fine, _ev = st.lr_disk_top(c[0], c[1], rad, z)
    assert abs(coarse - 50.0) < 1e-9, ("grid should count the tall cell",
                                       coarse)
    assert fine is not None and abs(fine - 36.0) < 1e-9, fine
    zs_f = _lva_start(st, c[0], c[1], r, s, z, R, 1.0, (25.0, 71.6),
                      disk_top=fine)
    zs_c = _lva_start(st, c[0], c[1], r, s, z, R, 1.0, (25.0, 71.6))
    assert zs_f < zs_c - 10.0, (zs_f, zs_c)
    print("PASS lr1 over-read: grid %.3f, fine %.3f; start %.3f (grid %.3f)"
          % (coarse, fine, zs_f, zs_c))


def test_af_band_catches_sliver_outside_disk():
    """(5) the sliver of (3) 0.04 mm outside r + R: the fine top over
    r + R misses it, the AF switch (band AF_BAND_MM) does not - the switch
    is above the sliver, so the helix beside it stays at the ramp feed."""
    from engine.rough import _af_switch_z
    R, r = 6.343, 3.17
    # nearest standing 0.1 mm point is yc + 0.1: its square starts 0.05
    # above it, so it sits 0.04 mm outside r + R when the centre is
    # r + R - 0.01 below yc
    st, c, r, s, z, yc = _overclear_scene(r + R - 0.01)
    inside, _e = st.lr_disk_top(c[0], c[1], r + R, z)
    zsw, _e2 = _af_switch_z(st, c[0], c[1], r, R, z)
    assert inside is not None and inside < 40.0, ("sliver inside r+R",
                                                  inside)
    assert zsw is not None and zsw >= 50.0, ("band missed the sliver", zsw)
    print("PASS af band: top over r+R %.3f, switch %.3f (sliver 50)"
          % (inside, zsw))


def test_lr1_cap_falls_back():
    """(6) with the cap at 0 every fine query falls back: today's start and
    ramp feed, i.e. main's program; every query counts a cap hit."""
    from engine import rough as rmod
    old = rmod.LR1_CAP
    rmod.LR1_CAP = 0
    try:
        m, st = _scene_rough(lr1=1, air_feed=1)
    finally:
        rmod.LR1_CAP = old
    h = hashlib.sha256(json.dumps(m).encode()).hexdigest()[:16]
    assert st["lr1"]["queries"] >= 1 and \
        st["lr1"]["cap_hits"] == st["lr1"]["queries"], st["lr1"]
    assert st["af"]["cap_hits"] == st["af"]["queries"] >= 1, st["af"]
    assert h == MAIN_BS1D_SHA16, ("cap fallback is not today's program", h)
    print("PASS lr1 cap fallback: %s, af %s, program == main %s"
          % (st["lr1"], {k: v for k, v in st["af"].items()
                          if k != "switch_z"}, h))


def _cutfeed_removals(moves):
    """zmap (0.1 mm) over the BS1d program: descending moves at the cutting
    feed that zmap measures removing or touching stock."""
    from verify import zmap
    feeds, lines = {}, ["G21 G90"]
    for mv in moves:
        w = ["G0" if mv["g"] == 0 else "G1"]
        w += ["%s%.4f" % (k.upper(), mv[k]) for k in ("x", "y", "z")
              if mv.get(k) is not None]
        if mv["g"] == 1 and mv.get("f"):
            w.append("F%.1f" % mv["f"])
        lines.append(" ".join(w))
        feeds[len(lines)] = mv.get("f") if mv["g"] == 1 else None
    cell, x0, y0 = 0.1, -48.0, -38.0
    nx, ny = 960, 760
    X, Y = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell,
                       y0 + (np.arange(ny) + 0.5) * cell)
    inb = (np.abs(X) <= 40) & (np.abs(Y) <= 30)
    tall = ((X <= -30) | (X >= 30) | (Y <= -25) | (Y >= 25)) | \
        ((np.abs(X) <= 11) & (np.abs(Y) <= 6))
    part = np.where(inb, np.where(tall, 14.0, 0.0), -1.0)
    mvs = zmap.parse_gcode("\n".join(lines) + "\n")
    res = zmap.simulate(mvs, part, cell, x0, y0, STOCK, tool="flat",
                        dia=12.686, flute=50.8, engage_max=2.4384)
    return [r for r in res["_hw_raw"] if r["kind"] == "entry"
            and feeds.get(r["line"]) == CUT
            and (r["depth_mm"] > 0.0 or r["width_mm"] > 0.0)]


def test_lr1_bs1d_judged():
    """(7) BS1d, LR1 and LR1 + AF vs OFF, judged by zmap at 0.1 mm."""
    m_off, _s = _scene_rough(lr1=0, air_feed=0)
    c_off = _judge(m_off)
    e_off = _eng(c_off)
    out = []
    for lr, af in ((1, 0), (1, 1)):
        m, st = _scene_rough(lr1=lr, air_feed=af)
        assert st["lr1"]["lowered"] >= 1 and st["lr1"]["cap_hits"] == 0, \
            st["lr1"]
        c = _judge(m)
        for g in GATES:
            if isinstance(c.get(g), dict):
                assert c[g]["count"] == 0, (lr, af, g, c[g])
        e = _eng(c)
        for k in e_off:
            assert e[k] <= e_off[k] + 1e-9, ("engagement worse", lr, af, k,
                                             e[k], e_off[k])
        assert c["cycle_time_s"] < c_off["cycle_time_s"], \
            (c["cycle_time_s"], c_off["cycle_time_s"])
        bad = _cutfeed_removals(m) if af else []
        assert not bad, ("cutting-feed descent touches stock", bad[:3])
        out.append("lr1 %d af %d cycle %.1f" % (lr, af, c["cycle_time_s"]))
    print("PASS lr1 bs1d at 0.1 mm: off %.1f s, %s; gates 0, engagement <="
          " off, 0 cutting-feed contacts" % (c_off["cycle_time_s"],
                                              ", ".join(out)))


class _Parsed(Exception):
    def __init__(self, ns):
        super().__init__("parsed")
        self.ns = ns


def test_lr1_default_on_and_off_is_main():
    """(8) LR1 and AF are ON by default (James, 2026-11-06): the default
    program equals lr1=1 + air_feed=1 (with lr1 / af stats) and differs from
    OFF; lr1=0 + air_feed=0 and CAMBUDDY_LR1=0 + CAMBUDDY_AIR_FEED=0 give the
    same program, without the keys, and it is main's (pinned hash). The
    parser maps nothing to None (= default ON), --lr1 1 / --air-feed 1 to 1
    and --no-lr1 / --no-air-feed to 0."""
    olds = {k: os.environ.pop(k, None)
            for k in ("CAMBUDDY_LR1", "CAMBUDDY_AIR_FEED")}
    try:
        m_def, s_def = _scene_rough()
        m_on, _s = _scene_rough(lr1=1, air_feed=1)
        m_off, s_off = _scene_rough(lr1=0, air_feed=0)
        os.environ["CAMBUDDY_LR1"] = "0"
        os.environ["CAMBUDDY_AIR_FEED"] = "0"
        m_env, s_env = _scene_rough()
    finally:
        for k, v in olds.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    assert "lr1" in s_def and "af" in s_def, sorted(s_def)
    assert json.dumps(m_def) == json.dumps(m_on), "default != ON"
    for s_ in (s_off, s_env):
        assert "lr1" not in s_ and "af" not in s_
    assert json.dumps(m_off) == json.dumps(m_env), "off != env 0"
    h = hashlib.sha256(json.dumps(m_off).encode()).hexdigest()[:16]
    assert h == MAIN_BS1D_SHA16, ("OFF is not main's program", h)
    assert json.dumps(m_def) != json.dumps(m_off), "ON changes nothing"
    import argparse
    from engine import cli
    orig = argparse.ArgumentParser.parse_args

    def grab(self, args=None, namespace=None):
        raise _Parsed(orig(self, args, namespace))
    argparse.ArgumentParser.parse_args = grab
    try:
        for argv, want in (([], (None, None)),
                           (["--lr1", "1", "--air-feed", "1"], (1, 1)),
                           (["--no-lr1", "--no-air-feed"], (0, 0)),
                           (["--no-lr1"], (0, None)),
                           (["--no-air-feed"], (None, 0))):
            try:
                cli.main(["rough", "--step", "x.step", "--stock", "0", "1",
                          "0", "1", "0", "1", "--tool", "flat:12.686",
                          "--out", os.devnull, "--floor", "0"] + argv)
            except _Parsed as e:
                assert (e.ns.lr1, e.ns.air_feed) == want, argv
            else:
                raise AssertionError("parser not reached")
    finally:
        argparse.ArgumentParser.parse_args = orig
    print("PASS lr1 default ON (== ON, != OFF); OFF / env 0 identical, no "
          "keys, == main %s; --no-lr1 / --no-air-feed parse to 0" % h)


if __name__ == "__main__":
    test_lr1_upper_bound_vs_fine_replay()
    test_lr1_branch_and_bound_matches_brute_force()
    test_lr1_overclear_keeps_start_high()
    test_lr1_overread_lowers_start()
    test_af_band_catches_sliver_outside_disk()
    test_lr1_cap_falls_back()
    test_lr1_default_on_and_off_is_main()
    test_lr1_bs1d_judged()
