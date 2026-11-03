"""LVA (lever A, --air-descent-g0): a helix entry G0s down its column to
_lva_start() instead of spiralling at ramp feed from the link plane.
(a) _lva_start on synthetic StockField grids, values known analytically:
    open column -> column top + margin; a PART wall inside the helix's swept
    disk does NOT lift it (A1b: the helix circle is island-legal); STOCK
    standing in that disk does; part at the G0 column (R5 term) does; a wall
    inside the holder radius lifts it to the holder-safe height; unknown
    holder -> None (today's start);
(b) LVA default ON; explicit off / ENGINE_AIR_G0=0 / --no-air-descent-g0 off.
Runnable directly or under pytest from VibeCAD python."""
import json
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import model  # noqa: E402,F401  (puts area on the path)

TOOL_R, R_HX, MARGIN, Z = 6.343, 3.17, 1.0, 5.0
S = (-R_HX, 0.0)          # helix start point on the circle about (0, 0)


def _field(walls=(), stock=()):
    """Stock cleared to Z10 over the box. walls: PART features (x0, x1, y0,
    y1, top) - the stock over them stands at their top + 0.381 (the leave
    the rough keeps); stock: standing CUTTABLE stock blocks (no part)."""
    from engine.stock import StockField
    st = StockField((-50.0, 50.0, -50.0, 50.0, 0.0, 30.0), cell=0.5)
    st.top = np.where(st.inb, 10.0, -np.inf)
    xs = st.x0 + (np.arange(st.nx) + 0.5) * st.cell
    ys = st.y0 + (np.arange(st.ny) + 0.5) * st.cell
    part = np.full((st.ny, st.nx), -np.inf)
    box = lambda b: ((xs >= b[0]) & (xs <= b[1]))[None, :] & \
        ((ys >= b[2]) & (ys <= b[3]))[:, None]
    for w in walls:
        m = box(w)
        part[m] = w[4]
        st.top[m] = w[4] + 0.381
    for b in stock:
        m = box(b)
        st.top[m] = np.maximum(st.top[m], b[4])
    st.part = part
    return st


def _start(st, holder=(25.0, 71.6)):
    from engine.rough import _lva_start
    return _lva_start(st, 0.0, 0.0, R_HX, S, Z, TOOL_R, MARGIN, holder)


def test_lva_start_values():
    # open column: everything cleared to Z10 -> 10 + margin
    zs = _start(_field())
    assert zs is not None and abs(zs - 11.0) < 1e-6, zs
    # (A1b) a tall PART wall inside the helix's swept disk but outside the
    # tool disk at s: the island-legal helix cannot reach it, so the start
    # may go below its top (stays at the column floor + margin)
    wall = (9.5, 12.0, -3.0, 3.0, 18.0)
    zs_w = _start(_field([wall]))
    assert zs_w is not None and abs(zs_w - 11.0) < 1e-6, \
        "part wall in the helix disk: %r" % zs_w
    # STOCK standing in the helix disk above the column floor: the first
    # turns would side-cut it - the start stays margin over it
    blk = (9.5, 12.0, -3.0, 3.0, 15.0)
    zs_s = _start(_field(stock=[blk]))
    assert zs_s is not None and abs(zs_s - 16.0) < 1e-6, \
        "stock in the helix disk: %r" % zs_s
    # stock terrace sitting ON the part where the part stands above Z (part 8,
    # stock top 12, Z 5) inside the helix disk: island at Z, out of reach
    terr = _field([(9.5, 12.0, -3.0, 3.0, 8.0)])
    m = terr.part > -np.inf
    terr.top[m] = 12.0
    zs_t = _start(terr)
    assert zs_t is not None and abs(zs_t - 11.0) < 1e-6, \
        "stock on the part island: %r" % zs_t
    # a part wall within tool_r + margin of the G0 column s (R5 term):
    # x -12..-9.5 is 6.3..8.8 from s (-3.17, 0) -> inside 7.343
    wall_s = (-12.0, -9.5, -3.0, 3.0, 18.0)
    zs_r = _start(_field([wall_s]))
    assert zs_r is not None and abs(zs_r - 19.381) < 1e-6, \
        "part at the G0 column: %r" % zs_r
    # holder: wall 13..15 mm from the centre (outside the helix disk), 16.2
    # from s (inside holder_r + 1 = 21), top 25; stick-out 9 -> nose >= 1 mm
    # over its stock top 25.381: zs >= 25.381 - 9 + 1 = 17.381
    hwall = (13.0, 15.0, -3.0, 3.0, 25.0)
    zs_h = _start(_field([hwall]), holder=(20.0, 9.0))
    assert zs_h is not None and abs(zs_h - 17.381) < 1e-6, \
        "holder wall: %r" % zs_h
    zs_l = _start(_field([hwall]), holder=(20.0, 71.6))
    assert zs_l is not None and abs(zs_l - 11.0) < 1e-6, zs_l
    assert _start(_field(), holder=None) is None
    print("PASS lva start (A1b): open %.3f, part wall in helix disk %.3f, "
          "stock in helix disk %.3f, stock on the part island %.3f, part at "
          "the column %.3f, holder %.3f (long stick-out %.3f), unknown "
          "holder None" % (zs, zs_w, zs_s, zs_t, zs_r, zs_h, zs_l))


def test_lva_margin_band():
    """(a') the scan band just outside the helix's swept disk: a part>Z
    cell with a tall terrace must NOT lift the start; a part<=Z cell under
    tall stock MUST lift it within r + R + h (h = half a cell diagonal) and
    must NOT beyond it (A2)."""
    # boundary band: cells between the swept disk (r + R = 9.513) and the
    # scan radius (+ margin = 10.513), at x 9.8..10.4 (cell centre 10.25)
    band = (9.8, 10.4, -1.0, 1.0)
    # (i) part ABOVE Z there with a tall terrace on it: island at Z, must
    # NOT lift the start
    bi = _field([band + (8.0,)])
    bi.top[bi.part > -np.inf] = 25.0
    zs_bi = _start(bi)
    assert zs_bi is not None and abs(zs_bi - 11.0) < 1e-6, \
        "terrace on part > Z in the margin band: %r" % zs_bi
    # (ii) A2 (coordinator-approved): the scan reaches r + R + h only,
    # h = cell * sqrt(2) / 2 = 0.354 (grid discretisation): r + R + h =
    # 9.867. A part<=Z cell (part 3) under tall stock whose centre is in
    # (r + R, r + R + h] MUST lift it (centres x 9.75, |y| <= 0.75: 9.753 ..
    # 9.779); the same cell beyond r + R + h (centre x 10.25) must NOT.
    near = (9.6, 9.9, -1.0, 1.0)
    bii = _field([near + (3.0,)])
    bii.top[bii.part > -np.inf] = 15.0
    zs_bii = _start(bii)
    assert zs_bii is not None and abs(zs_bii - 16.0) < 1e-6, \
        "stock on part <= Z within r + R + h: %r" % zs_bii
    far = (10.0, 10.4, -1.0, 1.0)
    biii = _field([far + (3.0,)])
    biii.top[biii.part > -np.inf] = 15.0
    zs_biii = _start(biii)
    assert zs_biii is not None and abs(zs_biii - 11.0) < 1e-6, \
        "stock on part <= Z beyond r + R + h: %r" % zs_biii
    print("PASS lva margin band: part>Z terrace %.3f, part<=Z stock within "
          "h %.3f, beyond h %.3f" % (zs_bi, zs_bii, zs_biii))


def _zmap_judge(moves):
    """zmap (verify/, independent of the engine) on a BS1d program: the part
    grid is the scene's boxes sampled at cell centres."""
    from verify import zmap
    cell, x0, y0 = 0.5, -48.0, -38.0
    nx, ny = 192, 152
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    X, Y = np.meshgrid(xs, ys)
    part = np.where((np.abs(X) <= 40) & (np.abs(Y) <= 30), 0.0, -1.0)
    tall = ((X <= -30) | (X >= 30) | (Y <= -25) | (Y >= 25)) | \
        ((np.abs(X) <= 11) & (np.abs(Y) <= 6))
    part = np.where(tall & (np.abs(X) <= 40) & (np.abs(Y) <= 30), 14.0, part)
    lines = ["G21 G90"]
    for mv in moves:
        w = ["G0" if mv["g"] == 0 else "G1"]
        w += ["%s%.4f" % (k.upper(), mv[k]) for k in ("x", "y", "z")
              if mv.get(k) is not None]
        if mv["g"] == 1 and mv.get("f"):
            w.append("F%.1f" % mv["f"])
        lines.append(" ".join(w))
    return zmap.simulate(zmap.parse_gcode("\n".join(lines) + "\n"), part,
                         cell, x0, y0, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0),
                         dia=12.686)


class _Parsed(Exception):
    def __init__(self, ns):
        super().__init__("parsed")
        self.ns = ns


def test_lva_default_on_and_off_switches():
    """(b) LVA is ON by default (stats lva.on == 1 with no flag or env);
    explicit off (air_descent_g0=0) and ENGINE_AIR_G0=0 both turn it off and
    give the same program; on the BS1d scene exactly one LVA G0 fires and
    default differs from off only in that entry's span, judged clean by
    zmap (A2). Also: engine.cli parses --no-air-descent-g0 to 0."""
    from opencamlib import ocl
    from engine import cli
    from engine.rough import rough
    from engine.test_engine import _box_tris, _write_stl
    bt = _box_tris
    tris = (bt(-40, 40, -30, 30, -1, 0) + bt(-40, -30, -30, 30, 0, 14)
            + bt(30, 40, -30, 30, 0, 14) + bt(-30, 30, -30, -25, 0, 14)
            + bt(-30, 30, 25, 30, 0, 14) + bt(-11, 11, -6, 6, 0, 14))
    out, ons, raw, sts = {}, {}, {}, {}
    old = os.environ.pop("ENGINE_AIR_G0", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            stl = os.path.join(td, "lva_def.stl")
            _write_stl(stl, tris)
            surf = ocl.STLSurf()
            ocl.STLReader(stl, surf)
            for tag, flag, env in (("default", None, None), ("off", 0, None),
                                   ("env0", None, "0")):
                if env is None:
                    os.environ.pop("ENGINE_AIR_G0", None)
                else:
                    os.environ["ENGINE_AIR_G0"] = env
                m, st = rough(surf, (-40.0, 40.0, -30.0, 30.0, -1.0, 14.0),
                              6.343, 0.0, leave=0.381, axial_leave=0.381,
                              stepdown=19.05, stepup=1.905, tolerance=0.05,
                              threads=4, stock_cell=0.5, min_rest=0.5,
                              corner_r=0.0, stl_path=stl,
                              side_entry_holder=(25.0, 71.6),
                              air_descent_g0=flag)
                out[tag], ons[tag] = json.dumps(m), st["lva"]["on"]
                raw[tag], sts[tag] = m, st
    finally:
        os.environ.pop("ENGINE_AIR_G0", None)
        if old is not None:
            os.environ["ENGINE_AIR_G0"] = old
    assert ons == {"default": 1, "off": 0, "env0": 0}, ons
    assert out["off"] == out["env0"], "explicit off != ENGINE_AIR_G0=0"
    # A2 (coordinator-approved edit, replaces default == off byte for byte):
    # with the r + R + h scan exactly one LVA G0 fires on this scene; the
    # programs share a common prefix and suffix and differ only in the one
    # span that starts with that vertical G0; the engine's checks hold and
    # the independent judge (zmap) sees no rapid collision and no entry
    # under standing stock (ZH1) in the default program.
    a, b, sd = raw["default"], raw["off"], sts["default"]
    assert sd["lva"]["g0"] == 1, sd["lva"]
    i = next(k for k in range(min(len(a), len(b))) if a[k] != b[k])
    t = 0
    while t < min(len(a), len(b)) - i and a[-1 - t] == b[-1 - t]:
        t += 1
    mid = a[i:len(a) - t]
    assert mid and mid[0]["g"] == 0 and i > 0 and \
        (mid[0]["x"], mid[0]["y"]) == (a[i - 1]["x"], a[i - 1]["y"]) and \
        mid[0]["z"] < a[i - 1]["z"], ("span does not start with the LVA G0",
                                       a[i - 1:i + 2])
    assert all(mv["g"] == 1 for mv in mid[1:]), "more than one G0 in the span"
    assert all(mv["g"] == 1 for mv in b[i:len(b) - t]), "off span has a G0"
    # A2 (panel, MF1b): the on-span's helix is the off-span's helix entered
    # lower. _helix_moves descends over a WHOLE number of turns at a uniform
    # rate, so a shorter descent has fewer turns and a shallower pitch: the
    # Z values differ, but move k of both spans is the same point of the
    # same circle (same centre, radius, start angle, segments per turn), the
    # feed is identical, the helix's closing move is shared, and the descent
    # is uniform and never steeper than the off helix.
    on_g1, off_g1 = mid[1:], b[i:len(b) - t]
    assert 0 < len(on_g1) <= len(off_g1), (len(on_g1), len(off_g1))
    for k, (p, q) in enumerate(zip(on_g1, off_g1)):
        assert abs(p["x"] - q["x"]) <= 1e-6 and \
            abs(p["y"] - q["y"]) <= 1e-6, ("helix point", k, p, q)
        assert p.get("f") == q.get("f"), ("helix feed", k, p, q)
    # the helix's last move (back over its start point at the bottom) is
    # the first move both programs share again
    end = a[len(a) - t]
    assert t > 0 and end == b[len(b) - t] and end["g"] == 1 and \
        abs(end["x"] - mid[0]["x"]) <= 1e-6 and \
        abs(end["y"] - mid[0]["y"]) <= 1e-6 and \
        end.get("f") == on_g1[0].get("f") and \
        end["z"] < on_g1[-1]["z"], (end, mid[0], on_g1[-1])

    def drops(seq, z0):
        zs = [z0] + [mv["z"] for mv in seq]
        return [zs[j] - zs[j + 1] for j in range(len(seq))]
    d_on, d_off = drops(on_g1, mid[0]["z"]), drops(off_g1, a[i - 1]["z"])
    assert max(d_on) - min(d_on) <= 2e-4 and min(d_on) > 0, d_on
    assert max(d_on) <= min(d_off) + 2e-4, (max(d_on), min(d_off))
    assert sd.get("clcheck_violations") == 0 and \
        sd.get("n_axial_plunge", 0) == 0, (sd.get("clcheck_violations"),
                                           sd.get("n_axial_plunge"))
    zr = _zmap_judge(a)
    assert zr["rapid_collisions"]["count"] == 0, zr["rapid_collisions"]
    assert zr["entry_stock"]["count"] == 0, zr["entry_stock"]
    # the parser: --no-air-descent-g0 -> 0, nothing -> None (= default ON)
    import argparse
    orig = argparse.ArgumentParser.parse_args

    def grab(self, args=None, namespace=None):
        ns = orig(self, args, namespace)
        raise _Parsed(ns)
    argparse.ArgumentParser.parse_args = grab
    try:
        for argv, want in ((["--no-air-descent-g0"], 0), ([], None),
                           (["--air-descent-g0", "1"], 1)):
            try:
                cli.main(["rough", "--step", "x.step", "--stock", "0", "1",
                          "0", "1", "0", "1", "--tool", "flat:12.686",
                          "--out", os.devnull, "--floor", "0"] + argv)
            except _Parsed as e:
                assert e.ns.air_descent_g0 == want, (argv, e.ns.air_descent_g0)
            else:
                raise AssertionError("parser not reached")
    finally:
        argparse.ArgumentParser.parse_args = orig
    print("PASS lva default ON; off via flag/env byte-identical; "
          "--no-air-descent-g0 parses to 0")


if __name__ == "__main__":
    test_lva_start_values()
    test_lva_margin_band()
    test_lva_default_on_and_off_switches()
