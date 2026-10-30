"""Task SP-K2C tests: the fast per-move C loop (verify/zkern/zcut.c with
squared-radius cell classification, per-row column bounds and cannot-cut
skips) must reproduce the Python per-move loop exactly.

Run with homebrew/VibeCAD pytest, C path active (ZMAP_NO_CKERN unset).
The existing verify/test_zmap.py is separately required to pass on BOTH
paths (C and ZMAP_NO_CKERN=1); the first test below re-runs SP-K2B's
2,000-move generator (shank/holder hits and exact argmin ties) through
the new culled loop.
"""
import math
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zmap            # noqa: E402
import zkern           # noqa: E402
import test_sp_k2b as k2b  # noqa: E402

KERN = zkern.load()
pytestmark = pytest.mark.skipif(KERN is None,
                                reason="C kernel not loaded (ZMAP_NO_CKERN?)")

NMOVES = int(os.environ.get("SPK2C_NMOVES", "2000"))

_diff = k2b._diff
_simulate_both = k2b._simulate_both


# ---------------------------------------------------------------------------
# 1) SP-K2B's 2,000-move generator (shank/holder hits and argmin ties) run
#    through the new culled loop, chained move by move.
# ---------------------------------------------------------------------------

def test_k2b_generator_2000_moves_fast_loop_equals_python():
    """Same 10-scene / 2,000-move plan as test_sp_k2b.py (flat/bull/ball,
    near mask on/off, grid-edge clipping, shank AND holder ON, exact
    cell-corner argmin ties every 25th move, ridge chains): after EVERY
    move the stock grids must be byte-identical and every report field
    within the bar."""
    plan = [
        ("flat0", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "flat", False, None),
        ("flatW", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "flat", True, None),
        ("bull0", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "bull", False, None),
        ("ballW", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "ball", True, None),
        ("ball0", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0, 10.0),
         "ball", False, None),
        ("tie_flat", 0.5, 0.0, 0.0, (0.0, 18.0, 0.0, 18.0, -2.0, 10.0),
         "flat", False, None),
        ("tie_ballW", 0.5, 0.0, 0.0, (0.0, 18.0, 0.0, 18.0, -2.0, 10.0),
         "ball", True, None),
        ("tie_bull0", 0.5, 0.0, 0.0, (0.0, 18.0, 0.0, 18.0, -2.0, 10.0),
         "bull", False, None),
        ("ridge_flat", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0,
                                           10.0), "flat", False, 12.0),
        ("ridge_ballW", 0.5, -18.0, -18.0, (-18.0, 18.0, -18.0, 18.0, -2.0,
                                            10.0), "ball", True, 12.0),
    ]
    total = NMOVES
    per = total // 10
    all_fails = []
    stats = dict(moves=0, shank_hits=0, holder_hits=0, rapids=0,
                 tie_checked=0, plunge=0)
    for ci, (tag, cell, x0, y0, box, tool, won, ridge) in enumerate(plan):
        rng = np.random.default_rng(20261029 + ci)
        if ridge is not None:
            nx = int(round((box[1] - box[0]) / cell))
            ny = int(round((box[3] - box[2]) / cell))
            part0 = k2b._mk_part(nx, ny, cell, x0, y0, ridge_x=ridge)
            xs = x0 + (np.arange(nx) + 0.5) * cell
            ys = y0 + (np.arange(ny) + 0.5) * cell
            cx, cy = x0 + nx * cell / 2.0, y0 + ny * cell / 2.0
            keep = ((np.abs(xs - cx)[None, :] <= 6.0)
                    & (np.abs(ys - cy)[:, None] <= 6.0))
            ridge_keep = np.broadcast_to(
                (np.abs(xs - ridge)[None, :] <= cell), (ny, nx))
            stock0 = np.where(keep | ridge_keep, box[5], 0.0)
        else:
            stock0 = None
        fails, st = k2b._run_chain("k2c_" + tag, rng, per, cell, x0, y0, box,
                                   tool, won, ridge_x=ridge, stock0=stock0)
        all_fails.extend(fails)
        for key in stats:
            stats[key] += st[key]
    print("SP-K2C k2b-generator stats:", stats)
    assert not all_fails, ("%d mismatch entries in %d moves; first: %r"
                           % (len(all_fails), stats["moves"], all_fails[:3]))
    assert stats["shank_hits"] >= max(10, NMOVES // 50), \
        "chain built too few shank hits"
    assert stats["holder_hits"] >= max(10, NMOVES // 50), \
        "chain built too few holder hits"
    assert stats["tie_checked"] >= max(8, NMOVES // 250), \
        "no exact argmin ties were checked"


# ---------------------------------------------------------------------------
# 2) 300+ moves constructed so that a CELL CENTRE SITS EXACTLY ON (or within
#    one ulp of, or one small step inside/outside) every radius the kernel
#    block uses: tool R + 1e-9, engagement R + 0.75*cell, shank
#    Rs + 0.75*cell, holder Rh, the bull inner radius a = R - corner and
#    the ball dd-clamp radius R. Also the cannot-cut boundary w = sz
#    exactly and a hair above, and +inf/NaN cells on the mask edges.
#
#    Geometry: x0 = y0 = 0, cell = 0.5 (power of two, so cell centres are
#    exact); the sample XY is (xs[ic] - r, ys[jc]) so the cell (jc, ic) is
#    at gy = 0 and gx = xs[ic] - sx = r up to one ulp of the subtraction;
#    d = hypot(gx, 0) = |gx|. The -1e-3 engagement-margin mutation is
#    sensitive to the +0.001 (DSMALL) offsets: outside the 1e-9 band but
#    inside a 1e-3 band.
# ---------------------------------------------------------------------------

CELL = 0.5
NX = NY = 40
X0 = Y0 = 0.0
BOX = (0.0, NX * CELL, 0.0, NY * CELL, 0.0, 10.0)
DIA = 6.0                      # R = 3.0
R = DIA / 2.0
CORNER = 1.5                   # bull corner; a = 1.5
SHANK_DIA = 8.0                # Rs = 4.0
HOLDER = [[0.0, 50.0, 4.0, 5.0]]   # Rh = max r + HOLDER_CLEAR = 6.0
FLUTE = 3.0
STICKOUT = 2.0                 # nose = tip + 2 < column top 6 -> holder hits
IC = JC = 20                   # boundary cell (row, col)

XS = X0 + (np.arange(NX) + 0.5) * CELL
YS = Y0 + (np.arange(NY) + 0.5) * CELL
YC = YS[JC]

RM = R + 1e-9                  # tool mask radius
RE = R + 0.75 * CELL           # engagement mask radius  (3.375)
PAD = SHANK_DIA / 2.0 + 0.75 * CELL   # shank mask radius (4.375)
RH = 6.0                       # holder envelope radius
AA = R - CORNER                # bull inner radius      (1.5)
RBALL = R                      # ball dd-clamp radius   (3.0)

DBIG = 0.05                    # >> the 1e-9 band: definite side
DSMALL = 0.001                 # outside the 1e-9 band, inside a -1e-3 band
TALL = 6.0                     # column top
ZDEEP = 2.0                    # tip well under the column top
ZSKIM = TALL - 2e-6            # tiny cut 2e-6 (cannot-cut mutation bait)

PART = np.zeros((NY, NX))

# window mask: disc of radius 10 cells around the boundary cell; the
# sample centre itself is outside the window but inside the dilated near
# mask, the boundary cell is inside.
WINDOW = ((XS[None, :] - XS[IC]) ** 2
          + (YS[:, None] - YC) ** 2) <= (10.0 * CELL) ** 2
WINDOW_X = WINDOW.copy()
WINDOW_X[JC, IC] = False       # window EXCLUDES the boundary cell


def _kw(tool, window=None):
    kw = dict(tool=tool, dia=DIA,
              corner=CORNER if tool == "bull" else 0.0,
              flute=FLUTE, shank_dia=SHANK_DIA, holder=HOLDER,
              stickout=STICKOUT, engage_max=2.0)
    if window is not None:
        kw["window"] = window
    return kw


def _stock(extra=None, base=0.0, tall_at_edge=True, tall=TALL):
    st = np.full((NY, NX), base)
    if tall_at_edge:
        st[JC, IC] = tall
    if extra:
        for (j, i, v) in extra:
            st[j, i] = v
    return st


def _fmt(v):
    return "%.17g" % v


def _plunge(sx, sy, z1):
    return ("G0 X%s Y%s Z25.\nG1 X%s Y%s Z%s F200."
            % (_fmt(sx), _fmt(sy), _fmt(sx), _fmt(sy), _fmt(z1)))


def _horiz(sx0, sx1, sy, z1):
    return ("G0 X%s Y%s Z25.\nG1 X%s Y%s Z%s F200.\nG1 X%s Y%s F300."
            % (_fmt(sx0), _fmt(sy), _fmt(sx0), _fmt(sy), _fmt(z1),
               _fmt(sx1), _fmt(sy)))


def _rapid_graze(sxm, yline):
    """horizontal rapid at Z2 grazing the boundary cell at distance
    |yline - ys[JC]| (one sample lands at x = xs[IC] exactly: 2 mm chord,
    cell/4 = 0.125 sampling, t = 0.5 exact)."""
    return ("G0 X%s Y%s Z2.\nG0 X%s Y%s Z2."
            % (_fmt(sxm - 1.0), _fmt(yline), _fmt(sxm + 1.0), _fmt(yline)))


def _cases():
    """Yield (tag, tool, window_or_None, gcode, stock_init, start)."""
    radii = [("Rm", RM), ("Re", RE), ("shank", PAD), ("holder", RH)]
    offs = [("in", -DBIG), ("insm", -DSMALL), ("exact", 0.0),
            ("outsm", DSMALL), ("out", DBIG)]
    # A: flat, deep + skim plunges on every radius edge (no window)
    for rn, rv in radii:
        for on, ov in offs:
            for zl, zz in (("deep", ZDEEP), ("skim", ZSKIM)):
                sx = XS[IC] - (rv + ov)
                yield ("flat_%s_%s_%s" % (rn, on, zl), "flat", None,
                       _plunge(sx, YC, zz), _stock(), [sx, YC, 25.0])
    # A2: flat with window mask (boundary cell inside window)
    for rn, rv in radii:
        for on, ov in (("in", -DBIG), ("exact", 0.0), ("out", DBIG)):
            sx = XS[IC] - (rv + ov)
            yield ("flatW_%s_%s" % (rn, on), "flat", WINDOW,
                   _plunge(sx, YC, ZDEEP), _stock(), [sx, YC, 25.0])
    # A3: flat, window EXCLUDES the boundary cell (mask-AND interaction)
    for rn, rv in radii:
        for on, ov in (("in", -DBIG), ("exact", 0.0)):
            sx = XS[IC] - (rv + ov)
            yield ("flatWx_%s_%s" % (rn, on), "flat", WINDOW_X,
                   _plunge(sx, YC, ZDEEP), _stock(), [sx, YC, 25.0])
    # B: ball radii + the dd-clamp radius; deep, and edge-nocut (tip low,
    # column under the sphere so every processed cell cuts < 0 and dmax
    # stays < 0: the nocut cells still need exact v for dmax)
    ball_radii = radii + [("clamp", RBALL)]
    for rn, rv in ball_radii:
        for on, ov in offs:
            sx = XS[IC] - (rv + ov)
            yield ("ball_%s_%s_deep" % (rn, on), "ball", None,
                   _plunge(sx, YC, ZDEEP), _stock(), [sx, YC, 25.0])
            yield ("ball_%s_%s_low" % (rn, on), "ball", None,
                   _plunge(sx, YC, 0.2), _stock(tall=2.5), [sx, YC, 25.0])
    # B2: ball with window
    for rn, rv in ball_radii:
        for on, ov in (("in", -DBIG), ("exact", 0.0), ("out", DBIG)):
            sx = XS[IC] - (rv + ov)
            yield ("ballW_%s_%s" % (rn, on), "ball", WINDOW,
                   _plunge(sx, YC, ZDEEP), _stock(), [sx, YC, 25.0])
    # C: bull radii + the inner radius a (torus band edge)
    bull_radii = radii + [("band", AA)]
    for rn, rv in bull_radii:
        for on, ov in offs:
            sx = XS[IC] - (rv + ov)
            yield ("bull_%s_%s_deep" % (rn, on), "bull", None,
                   _plunge(sx, YC, ZDEEP), _stock(), [sx, YC, 25.0])
            yield ("bull_%s_%s_skim" % (rn, on), "bull", None,
                   _plunge(sx, YC, ZSKIM), _stock(), [sx, YC, 25.0])
    # C2: bull with window
    for rn, rv in bull_radii:
        for on, ov in (("in", -DBIG), ("exact", 0.0), ("out", DBIG)):
            sx = XS[IC] - (rv + ov)
            yield ("bullW_%s_%s" % (rn, on), "bull", WINDOW,
                   _plunge(sx, YC, ZDEEP), _stock(), [sx, YC, 25.0])
    # D: cannot-cut boundary: column top sz - h, exactly sz, + a hair
    # (a helper cell at sz + 2e-6 forces the block to run)
    sx = XS[IC] - (R - DBIG)
    extra = [(JC + 1, IC, ZDEEP + 2e-6)]
    for dt in (-1e-9, 0.0, 1e-9, 5e-7, 1e-6):
        yield ("nocut_dt%g" % dt, "flat", None,
               _plunge(sx, YC, ZDEEP),
               _stock(extra=extra, tall=ZDEEP + dt), [sx, YC, 25.0])
    # E: +inf / NaN cells on the mask edge and at a far distance (marker)
    for rn, rv in (("Rm", RM), ("Re", RE), ("far", RH)):
        sx = XS[IC] - rv
        yield ("marker_inf_%s" % rn, "flat", None,
               _plunge(sx, YC, ZDEEP),
               _stock(tall_at_edge=False, extra=[(JC, IC, np.inf)]),
               [sx, YC, 25.0])
        yield ("marker_nan_%s" % rn, "flat", None,
               _plunge(sx, YC, ZDEEP),
               _stock(tall_at_edge=False, extra=[(JC, IC, np.nan)]),
               [sx, YC, 25.0])
    # F: horizontal feeds sweeping across the radius edges at depth
    for rn, rv in (("Rm", RM), ("Re", RE), ("holder", RH)):
        sx = XS[IC] - rv
        yield ("horiz_%s" % rn, "flat", None,
               _horiz(sx - 0.6, sx + 0.6, YC, ZDEEP), _stock(),
               [sx - 0.6, YC, 25.0])
    # G: rapids grazing the boundary cell at every mask radius edge
    for rn, rv in (("Rm", RM), ("Rmsm", RM + DSMALL), ("Re", RE),
                   ("out", RH)):
        yield ("rapid_%s" % rn, "flat", None,
               _rapid_graze(XS[IC], YC + rv), _stock(),
               [XS[IC] - 1.0, YC + rv, 25.0])
    # H: DIAGONAL exact boundaries: the cell sits at (r*cos45, r*sin45)
    # from the sample, so s = gx^2 + gy^2 decides near the margin band
    c45 = math.sqrt(0.5)
    diag_radii = [("Rm", RM), ("Re", RE), ("shank", PAD), ("holder", RH),
                  ("band", AA), ("clamp", RBALL)]
    for rn, rv in diag_radii:
        for on, ov in (("in", -DBIG), ("exact", 0.0), ("out", DBIG)):
            sx = XS[IC] - (rv + ov) * c45
            sy = YC - (rv + ov) * c45
            tool = "ball" if rn == "clamp" else ("bull" if rn == "band"
                                                 else "flat")
            yield ("diag_%s_%s" % (rn, on), tool, None,
                   _plunge(sx, sy, ZDEEP), _stock(), [sx, sy, 25.0])
    # I: z at the tip-vs-column-top boundary (early-out / nocut edges)
    for rn, rv in (("Rm", RM), ("Re", RE), ("band", AA), ("clamp", RBALL)):
        for zs, zt in (("at", TALL), ("hair", TALL - 1.000001e-6)):
            sx = XS[IC] - rv
            tool = "ball" if rn == "clamp" else ("bull" if rn == "band"
                                                 else "flat")
            yield ("ztip_%s_%s" % (rn, zs), tool, None,
                   _plunge(sx, YC, zt), _stock(), [sx, YC, 25.0])
    # J: ball edge-nocut (low tip, column under the sphere) with window
    for rn, rv in ball_radii:
        for on, ov in (("in", -DBIG), ("exact", 0.0), ("out", DBIG)):
            sx = XS[IC] - (rv + ov)
            yield ("ballWlow_%s_%s" % (rn, on), "ball", WINDOW,
                   _plunge(sx, YC, 0.2), _stock(tall=2.5), [sx, YC, 25.0])
    # K: bull edge-nocut low-tip variants on every radius edge
    for rn, rv in bull_radii:
        for on, ov in offs:
            sx = XS[IC] - (rv + ov)
            yield ("bull_%s_%s_low" % (rn, on), "bull", None,
                   _plunge(sx, YC, 0.2), _stock(tall=2.5), [sx, YC, 25.0])
    # L: horizontal feeds on ball and bull across Rm/Re edges
    for tool in ("ball", "bull"):
        for rn, rv in (("Rm", RM), ("Re", RE)):
            sx = XS[IC] - rv
            yield ("horiz_%s_%s" % (tool, rn), tool, None,
                   _horiz(sx - 0.6, sx + 0.6, YC, ZDEEP), _stock(),
                   [sx - 0.6, YC, 25.0])
    # M: +inf/NaN edge cells with a window mask (marker x mask-AND)
    for rn, rv in (("Rm", RM), ("Re", RE)):
        sx = XS[IC] - rv
        yield ("markerW_inf_%s" % rn, "flat", WINDOW,
               _plunge(sx, YC, ZDEEP),
               _stock(tall_at_edge=False, extra=[(JC, IC, np.inf)]),
               [sx, YC, 25.0])
        yield ("markerW_nan_%s" % rn, "flat", WINDOW,
               _plunge(sx, YC, ZDEEP),
               _stock(tall_at_edge=False, extra=[(JC, IC, np.nan)]),
               [sx, YC, 25.0])
    # N: ball cannot-cut boundary w = sz +- hairs at d = Rm - 0.05
    sx = XS[IC] - (R - DBIG)
    for dt in (-1e-9, 0.0, 1e-9, 5e-7, 1e-6):
        yield ("ball_nocut_dt%g" % dt, "ball", None,
               _plunge(sx, YC, ZDEEP),
               _stock(extra=[(JC + 1, IC, ZDEEP + 2e-6)], tall=ZDEEP + dt),
               [sx, YC, 25.0])
    # O: flat skim (2e-6 cut) with window, inside/outside every radius
    for rn, rv in radii:
        for on, ov in (("in", -DBIG), ("out", DBIG)):
            sx = XS[IC] - (rv + ov)
            yield ("flatWskim_%s_%s" % (rn, on), "flat", WINDOW,
                   _plunge(sx, YC, ZSKIM), _stock(), [sx, YC, 25.0])
    # P: diagonal low-tip (edge-nocut) for ball and bull surfaces
    for rn, rv in (("clamp", RBALL), ("band", AA), ("Rm", RM)):
        for on, ov in (("in", -DBIG), ("exact", 0.0), ("out", DBIG)):
            sx = XS[IC] - (rv + ov) * c45
            sy = YC - (rv + ov) * c45
            tool = "ball" if rn == "clamp" else ("bull" if rn == "band"
                                                 else "flat")
            yield ("diaglow_%s_%s" % (rn, on), tool, None,
                   _plunge(sx, sy, 0.2), _stock(tall=2.5), [sx, sy, 25.0])


def _run_case(case):
    tag, tool, win, gc, st0, start = case
    prog = zmap.parse_gcode("G21 G90\n" + gc + "\n")
    kw = _kw(tool, win)
    rep_c, rep_p = _simulate_both(prog, PART, CELL, X0, Y0, BOX, kw,
                                  st0.copy(), st0.copy(), list(start))
    out = []
    if rep_c["zcut_kernel"] != "c" or rep_p["zcut_kernel"] != "python":
        out.append((tag, "kernel flag"))
    if rep_c["stock"].tobytes() != rep_p["stock"].tobytes():
        out.append((tag, "stock bytes differ"))
    if rep_p["stock"].tobytes() != st0.tobytes() and \
            rep_c["stock"].tobytes() == st0.tobytes():
        out.append((tag, "C path cut nothing, python cut"))
    rep_c.pop("zcut_kernel")
    rep_p.pop("zcut_kernel")
    # stock is checked byte-wise above; np.array_equal would call every
    # NaN cell a difference even when the grids are bit-identical
    rc2 = {k: v for k, v in rep_c.items() if k != "stock"}
    rp2 = {k: v for k, v in rep_p.items() if k != "stock"}
    bad = _diff(rc2, rp2, tag)
    if bad:
        out.append((tag, bad[:6]))
    return out, rep_c


def test_300_exact_radius_moves_fast_loop_equals_python():
    """Constructed moves with a cell centre exactly ON every radius (tool
    R+1e-9, engagement R+0.75*cell, shank Rs+0.75*cell, holder Rh, bull
    inner a, ball clamp R) plus a small step inside/outside each, the
    cannot-cut boundary w = sz +- hairs, and +inf/NaN edge cells: stock
    byte-identical and every report field within the bar after every
    move."""
    cases = list(_cases())
    assert len(cases) >= 300, "constructed only %d moves" % len(cases)
    fails = []
    stats = dict(moves=0, cuts=0, shank=0, holder=0, engage=0, rap=0,
                 ball_low=0)
    for case in cases:
        tag = case[0]
        st0 = case[4]
        bad, rep_c = _run_case(case)
        fails.extend(bad)
        if rep_c["stock"].tobytes() != st0.tobytes():
            stats["cuts"] += 1
        if (rep_c["over_flute"] or {}).get("count", 0) > 0:
            stats["shank"] += 1
        if (rep_c["holder_hits"] or {}).get("count", 0) > 0:
            stats["holder"] += 1
        eng = rep_c.get("engagement") or {}
        if rep_c["air_fraction"] < 1.0 or eng.get("max_mm", 0.0) > 0.0:
            stats["engage"] += 1
        if rep_c["rapid_collisions"]["count"] > 0:
            stats["rap"] += 1
        if tag.startswith("ball_") and tag.endswith("_low"):
            stats["ball_low"] += 1
        stats["moves"] += 1
    print("SP-K2C exact-radius stats:", stats, "cases:", len(cases))
    assert not fails, ("%d/%d constructed moves mismatched; first: %r"
                       % (len(fails), stats["moves"], fails[:3]))
    assert stats["cuts"] >= 60, "too few cutting cases: %r" % stats
    assert stats["shank"] >= 20, "too few shank hits: %r" % stats
    assert stats["holder"] >= 20, "too few holder hits: %r" % stats
    assert stats["engage"] >= 20, "too few engagements: %r" % stats
    assert stats["rap"] >= 2, "too few rapid collisions: %r" % stats
    assert stats["ball_low"] >= 10, "no ball edge-nocut cases: %r" % stats


# ---------------------------------------------------------------------------
# 3) pinned cannot-cut / boundary expectations on the Python side, so a
#    shared C+Python mistake is caught too (these also certify the
#    mutation counts reported in SPK2C_RESULTS.md are real).
# ---------------------------------------------------------------------------

def test_exact_expected_values_on_boundary_cells():
    """Pinned expectations (Python-path truth): a cell at d = Rm - 0.05
    cuts; at d = Rm + 0.001 it does NOT cut; a cell at d = Re - 0.001
    engages, at d = Re + 0.001 nothing engages; a cell at d = Rh - 0.05
    gives a holder hit, at d = Rh + 0.05 not; w = sz exactly removes
    nothing while the block still runs."""
    def run(tag, sx, z1, stock):
        prog = zmap.parse_gcode("G21 G90\n" + _plunge(sx, YC, z1) + "\n")
        rep = zmap.simulate(prog, PART, CELL, X0, Y0, BOX,
                            stock_init=stock.copy(), start=[sx, YC, 25.0],
                            **_kw("flat"))
        return rep

    checks = []
    r_in = run("pin_cut_in", XS[IC] - (RM - DBIG), ZDEEP, _stock())
    r_out = run("pin_cut_out", XS[IC] - (RM + DSMALL), ZDEEP, _stock())
    checks.append(("cut at Rm-0.05",
                   r_in["stock"].tobytes() != _stock().tobytes()))
    checks.append(("no cut at Rm+0.001",
                   r_out["stock"].tobytes() == _stock().tobytes()))
    r_eg = run("pin_eng_in", XS[IC] - (RE - DSMALL), ZDEEP, _stock())
    r_ng = run("pin_eng_out", XS[IC] - (RE + DSMALL), ZDEEP, _stock())
    # engaged samples are NOT counted as air: a single engaged cell has a
    # zero-width chord, so engagement is observed through air_fraction
    # (tolerated: air_length is a repeated float sum, ~1e-16 off the move
    # length even when EVERY sample is air)
    checks.append(("engages at Re-0.001", r_eg["air_fraction"] < 0.999))
    checks.append(("no engage at Re+0.001", r_ng["air_fraction"] > 0.99999))
    r_hh = run("pin_hold_in", XS[IC] - (RH - DBIG), ZDEEP, _stock())
    r_hn = run("pin_hold_out", XS[IC] - (RH + DBIG), ZDEEP, _stock())
    checks.append(("holder hit at Rh-0.05",
                   (r_hh["holder_hits"] or {}).get("count", 0) > 0))
    checks.append(("no holder hit at Rh+0.05",
                   (r_hn["holder_hits"] or {}).get("count", 0) == 0))
    # w = sz exactly (helper cell at sz + 2e-6 forces the block): the
    # exact-height column must be untouched, the helper cell cut down.
    st = _stock(extra=[(JC + 1, IC, ZDEEP + 2e-6)], tall=ZDEEP)
    r_eq = run("pin_w_eq_sz", XS[IC] - (R - DBIG), ZDEEP, st)
    checks.append(("w=sz column untouched",
                   r_eq["stock"][JC, IC] == ZDEEP))
    checks.append(("helper cell cut",
                   r_eq["stock"][JC + 1, IC] <= ZDEEP + 1e-12))
    bad = [name for name, ok in checks if not ok]
    assert not bad, "pinned expectations violated: %r" % bad
