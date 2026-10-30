"""Task SP-K2 tests: the C kernel (verify/zkern/zcut.c) must reproduce the
per-sample Python block of zmap.simulate exactly.

Run with homebrew pytest, C path active (ZMAP_NO_CKERN unset). The full
verify/test_zmap.py suite is separately required to pass on BOTH paths
(see verify/SPK2_RESULTS.md for the two foreground runs).
"""
import ctypes
import json
import math
import os
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zmap   # noqa: E402
import zkern  # noqa: E402

KERN = zkern.load()
pytestmark = pytest.mark.skipif(KERN is None,
                                reason="C kernel not loaded (ZMAP_NO_CKERN?)")

CELL = 0.5
X0 = Y0 = -25.0
N = 100  # grid covers [-25, 25] x [-25, 25]
STOCK = (-25.0, 25.0, -25.0, 25.0, 0.0, 10.0)

NSAMPLES = int(os.environ.get("SPK2_NSAMPLES", "5000"))


# ---------------------------------------------------------------------------
# verbatim copy of the Python block (zmap.simulate, from
# `ilo, ihi = max(0, i0 - k)...` through the stock update). Only the
# move-level accumulators are re-routed through S (a SimpleNamespace) and
# `continue` becomes `return`; every arithmetic line is unchanged, plus S.*
# bookkeeping of the intermediate values the C kernel returns.
# ---------------------------------------------------------------------------
def _cut_ref(S, stock, xs, ys, nx, ny, i0, j0, k, sx, sy, sz, window, R, dz,
             ball_surf, surf_buf, cell, dx_t, dy_t):
    cutting = S.cutting
    engage_track = S.engage_track
    zb_on = S.zb_on
    ilo, ihi = max(0, i0 - k), min(nx, i0 + k + 1)
    jlo, jhi = max(0, j0 - k), min(ny, j0 + k + 1)
    if ilo >= ihi or jlo >= jhi:
        return
    gx = xs[ilo:ihi] - sx
    gy = ys[jlo:jhi] - sy
    win = stock[jlo:jhi, ilo:ihi]
    # no cell in reach is above the tool tip -> nothing to cut here
    if float(win.max()) <= sz + 1e-6:
        if cutting:
            S.air_length += S.seg_len
        return
    d = np.hypot(gx[None, :], gy[:, None])
    msk = d <= R + 1e-9
    if window is not None:
        msk &= window[jlo:jhi, ilo:ihi]
    if not msk.any():
        return
    if ball_surf:
        # exact dz(d) chain into scratch, then sz + dz (same ops)
        t = surf_buf[:gy.size, :gx.size]
        np.multiply(d, d, out=t)
        np.subtract(R * R, t, out=t)
        np.maximum(t, 0.0, out=t)
        np.sqrt(t, out=t)
        np.subtract(R, t, out=t)
        np.add(sz, t, out=t)
        newv = np.where(msk, t, np.inf)
    else:
        newv = np.where(msk, sz + dz(d), np.inf)
    cut = win - newv
    removed = float(np.sum(np.clip(cut, 0.0, None)))
    S.removed = removed
    if cutting and engage_track:
        nrem = int(np.count_nonzero(cut > zmap.REMOVE_EPS))
        S.nrem = nrem
        S.move_area += nrem * cell * cell
        if nrem:
            hb = np.minimum((cut[cut > zmap.REMOVE_EPS] / zmap.FWD_BIN_MM)
                            .astype(np.int64), zmap.FWD_NBINS - 1)
            hh = np.bincount(hb, minlength=zmap.FWD_NBINS).astype(np.uint32)
            S.move_hist = hh if S.move_hist is None else S.move_hist + hh
    if cutting and zb_on:
        cb = msk & np.isfinite(cut) & (cut > zmap.REMOVE_EPS)
        if cb.any():
            S.zb_vol += float(cut[cb].sum()) * cell * cell
        if S.zb_pre is not None:
            sub = S.zb_pre[jlo - S.zb_jlo:jhi - S.zb_jlo,
                           ilo - S.zb_ilo:ihi - S.zb_ilo]
            eb = msk & np.isfinite(sub) & (sub - newv > 0.01)
            if eb.any():
                S.zb_a = max(S.zb_a, float(np.max(sub[eb] - sz)))
                pu = (dx_t * gx[None, :] + dy_t * gy[:, None])[eb]
                pv = (-dy_t * gx[None, :] + dx_t * gy[:, None])[eb]
                S.zb_ext = max(S.zb_ext, float(pv.max() - pv.min()))
                S.zb_dext = max(S.zb_dext, math.hypot(
                    float(pu.max() - pu.min()), float(pv.max() - pv.min())))
    if cutting and engage_track:
        dmax = float(np.max(cut))
        S.dmax = dmax
        if np.isfinite(dmax) and dmax > S.move_max_depth:
            S.move_max_depth = dmax
    if cutting:
        msk_e = d <= R + 0.75 * cell
        if window is not None:
            msk_e &= window[jlo:jhi, ilo:ihi]
        engaged = (float(np.max(np.where(msk_e, win, -np.inf)))
                   > sz + 1e-6)
        S.engaged = engaged
        if engaged and engage_track:
            perp_x, perp_y = -dy_t, dx_t
            proj = (gx[None, :] * perp_x + gy[:, None] * perp_y)
            cells = msk_e & (win > sz + 1e-6)
            if cells.any():
                cproj = proj[cells]
                ew = float(cproj.max()) - float(cproj.min())
            else:
                ew = np.nan
            if not np.isfinite(ew):
                ew = 0.0
            ew = min(max(ew, 0.0), 2.0 * R)
            if ew > S.move_max_engage:
                S.move_max_engage = ew
        if removed > zmap.REMOVE_EPS:
            stock[jlo:jhi, ilo:ihi] = np.minimum(win, newv)
            S.updated = True
        if not engaged:
            S.air_length += S.seg_len
    else:  # rapid
        if np.any(cut > zmap.REMOVE_EPS):
            S.move_collided = True


def _vp(a):
    return a.ctypes.data_as(ctypes.c_void_p)


def _cut_c(stock, xs, ys, nx, ny, i0, j0, k, sx, sy, sz, R, tool_id, corner,
           wm, cutting, engage_track, zb_on, cell, dx_t, dy_t,
           pre, pre_st, pre_i0, pre_j0):
    zout = zkern.ZOut()
    zb_state = (ctypes.c_double * 4)()
    hist = (ctypes.c_uint32 * zkern.FWD_NBINS)()
    nscr = (2 * k + 1) * (2 * k + 1)
    scr_v = (ctypes.c_double * nscr)()
    scr_m = (ctypes.c_ubyte * nscr)()
    KERN.zcut_sample(_vp(stock), nx, ny, i0, j0, k, _vp(xs), _vp(ys),
                     sx, sy, sz, R, tool_id, corner,
                     _vp(wm) if wm is not None else None,
                     int(cutting), int(engage_track), int(zb_on), cell,
                     zmap.REMOVE_EPS, zmap.FWD_BIN_MM, dx_t, dy_t,
                     _vp(pre) if pre is not None else None,
                     pre_st, pre_i0, pre_j0,
                     ctypes.cast(zb_state, ctypes.c_void_p),
                     ctypes.cast(hist, ctypes.c_void_p),
                     ctypes.cast(scr_v, ctypes.c_void_p),
                     ctypes.cast(scr_m, ctypes.c_void_p),
                     ctypes.byref(zout))
    return zout, np.frombuffer(hist, dtype=np.uint32).copy(), zb_state[:]


def _close(x, y):
    if x == y:
        return True
    if isinstance(x, float) and isinstance(y, float) \
            and math.isnan(x) and math.isnan(y):
        return True
    if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
        return x == y
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))


def _one_sample(rng, idx):
    """One random sample; return a list of mismatch strings ([] == match)."""
    bad = []
    tool = str(rng.choice(["flat", "bull", "ball"]))
    dia = float(rng.choice([4.0, 6.0, 9.525, 12.0]))
    R = dia / 2.0
    corner = float(rng.uniform(0.01, R - 0.01)) if tool == "bull" else 0.0
    cell = float(rng.uniform(0.3, 1.2))
    nx = int(rng.integers(8, 40))
    ny = int(rng.integers(8, 40))
    x0 = float(rng.uniform(-7.0, 7.0))
    y0 = float(rng.uniform(-7.0, 7.0))
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    stock = rng.uniform(-2.0, 12.0, size=(ny, nx))
    a = rng.random(size=(ny, nx))
    stock[a < 0.05] = -np.inf                  # cleared cells
    stock[(a >= 0.05) & (a < 0.08)] = np.inf   # +inf cells (SP-K2 brief)
    window = None
    if rng.random() < 0.4:                     # with a window mask
        window = rng.random(size=(ny, nx)) < rng.uniform(0.2, 0.9)
        stock[~window] = -np.inf
    k = int(math.ceil(R / cell)) + 1
    i0 = int(rng.integers(0, nx))
    j0 = int(rng.integers(0, ny))
    if rng.random() < 0.3:                     # clip windows at grid edges
        i0 = int(rng.choice([0, nx - 1]))
        j0 = int(rng.choice([0, ny - 1]))
    sx = float(xs[i0] + rng.uniform(-0.75, 0.75) * cell)
    sy = float(ys[j0] + rng.uniform(-0.75, 0.75) * cell)
    sz = float(rng.uniform(-1.0, 11.0))
    cutting = bool(rng.random() < 0.75)
    engage_track = bool(rng.random() < 0.7)
    zb_on = engage_track and tool == "ball"
    th = float(rng.uniform(0.0, 2.0 * math.pi))
    dx_t, dy_t = math.cos(th), math.sin(th)
    seg_len = float(rng.uniform(0.01, 0.5))
    pre = None
    pre_st = pre_i0 = pre_j0 = 0
    if zb_on:                                  # pre-move snapshot, as simulate
        pre_i0 = max(0, i0 - k)
        pre_j0 = max(0, j0 - k)
        pre_i1 = min(nx, i0 + k + 1)
        pre_j1 = min(ny, j0 + k + 1)
        if pre_i0 < pre_i1 and pre_j0 < pre_j1:
            pre = stock[pre_j0:pre_j1, pre_i0:pre_i1].copy()
            pre_st = pre_i1 - pre_i0
    wm = np.ascontiguousarray(window, dtype=np.uint8) if window is not None \
        else None
    stock_py = stock.copy()
    stock_c = stock.copy()
    S = SimpleNamespace(
        cutting=cutting, engage_track=engage_track, zb_on=zb_on,
        seg_len=seg_len, air_length=0.0, move_area=0.0, move_hist=None,
        move_max_depth=-np.inf, move_max_engage=-np.inf,
        move_collided=False, zb_vol=0.0, zb_a=0.0, zb_ext=0.0, zb_dext=0.0,
        zb_pre=pre, zb_ilo=pre_i0, zb_jlo=pre_j0,
        removed=None, nrem=None, dmax=None, engaged=None, updated=False)
    with np.errstate(invalid="ignore", over="ignore"):
        _cut_ref(S, stock_py, xs, ys, nx, ny, i0, j0, k, sx, sy, sz, window,
                 R, zmap.tool_dz(tool, dia, corner), tool == "ball",
                 np.empty((2 * k + 1, 2 * k + 1)), cell, dx_t, dy_t)
    zout, hist, zb = _cut_c(stock_c, xs, ys, nx, ny, i0, j0, k, sx, sy, sz,
                            R, {"flat": 0, "bull": 1, "ball": 2}[tool],
                            corner, wm, cutting, engage_track, zb_on, cell,
                            dx_t, dy_t, pre, pre_st, pre_i0, pre_j0)
    if stock_c.tobytes() != stock_py.tobytes():
        bad.append("stock window bytes differ")
    if zout.air != (1 if S.air_length != 0.0 else 0):
        bad.append("air %d vs %r" % (zout.air, S.air_length))
    if bool(zout.collided) != S.move_collided:
        bad.append("collided %d vs %r" % (zout.collided, S.move_collided))
    if S.removed is not None:
        if not _close(zout.removed, S.removed):
            bad.append("removed %.17g vs %.17g" % (zout.removed, S.removed))
        if (zout.updated if S.removed > zmap.REMOVE_EPS and cutting
                else 0) != (1 if S.updated else 0):
            bad.append("updated flag %d vs %r" % (zout.updated, S.updated))
    if cutting:
        if engage_track and S.nrem is not None:
            if zout.nrem != S.nrem:
                bad.append("nrem %d vs %r" % (zout.nrem, S.nrem))
            if zout.hist_any != (1 if S.nrem else 0):
                bad.append("hist_any %d vs nrem %r"
                           % (zout.hist_any, S.nrem))
            want = S.move_hist if S.move_hist is not None \
                else np.zeros(zmap.FWD_NBINS, dtype=np.uint32)
            if not np.array_equal(hist, want):
                bad.append("hist differs (nrem=%r)" % S.nrem)
            if S.dmax is not None:
                if zout.dmax_valid != int(np.isfinite(S.dmax)):
                    bad.append("dmax_valid %d vs %r"
                               % (zout.dmax_valid, S.dmax))
                if np.isfinite(S.dmax) and zout.dmax != S.dmax:
                    bad.append("dmax %.17g vs %.17g" % (zout.dmax, S.dmax))
            want_e = S.move_max_engage   # -inf unless an ew was folded in
            if zout.ew_valid != (0 if math.isinf(want_e) else 1):
                bad.append("ew_valid %d vs %r" % (zout.ew_valid, want_e))
            if not math.isinf(want_e) and zout.ew != want_e:
                bad.append("ew %.17g vs %.17g" % (zout.ew, want_e))
        if S.engaged is not None and bool(zout.engaged) != S.engaged:
            bad.append("engaged %d vs %r" % (zout.engaged, S.engaged))
        if zb_on:
            if not _close(zb[0], S.zb_vol):
                bad.append("zb_vol %.17g vs %.17g" % (zb[0], S.zb_vol))
            # zb_dext goes through math.hypot (CPython's correctly-rounded
            # version) vs libm hypot in C: last-bit float difference,
            # judged at the 1e-9 bar. zb_a/zb_ext are pure max/min: exact.
            if not _close(zb[3], S.zb_dext):
                bad.append("zb_dext %.17g vs %.17g" % (zb[3], S.zb_dext))
            for got, want, nm in ((zb[1], S.zb_a, "zb_a"),
                                  (zb[2], S.zb_ext, "zb_ext")):
                if got != want:
                    bad.append("%s %.17g vs %.17g" % (nm, got, want))
    return bad


def test_c_kernel_matches_python_block_5000_samples():
    """5,000 random samples (flat/bull/ball, windows clipped at the grid
    edges, with and without a window mask, +-inf stock cells): the stock
    grid must be tobytes-identical and all returned values within the bar."""
    rng = np.random.default_rng(20261029)
    fails = []
    for idx in range(NSAMPLES):
        try:
            bad = _one_sample(rng, idx)
        except Exception as e:  # count a crash as a mismatch, keep going
            bad = ["exception: %r" % e]
        if bad:
            fails.append((idx, bad))
    assert not fails, ("%d/%d samples mismatched; first: %r"
                       % (len(fails), NSAMPLES, fails[:3]))


# ---------------------------------------------------------------------------
# report JSON: zcut_kernel flag + identical verdicts on the judge's faults
# ---------------------------------------------------------------------------

def _cli(tmp_path, gcode, part, cell, x0, y0, stock_box, extra, no_c):
    npf = tmp_path / "p.npy"
    np.save(npf, part)
    with open(tmp_path / "p.json", "w") as f:
        json.dump({"cell": cell, "x0": x0, "y0": y0, "tess_tol": 0.01}, f)
    ngc = tmp_path / "p.ngc"
    ngc.write_text(gcode)
    out = tmp_path / ("rep%s.json" % ("py" if no_c else "c"))
    env = dict(os.environ)
    if no_c:
        env["ZMAP_NO_CKERN"] = "1"
    else:
        env.pop("ZMAP_NO_CKERN", None)
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "zmap.py"), str(ngc),
         "--part", str(npf), "--stock"] + [str(v) for v in stock_box]
        + extra + ["--out-json", str(out)],
        capture_output=True, text=True, env=env)
    assert r.returncode in (0, 1), r.stderr
    with open(out) as f:
        return r.returncode, json.load(f)


def _diff_json(a, b, path="", out=None):
    """Key-by-key: ints/flags/lists of ints identical; floats rel/abs 1e-9."""
    if out is None:
        out = []
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out.append((path, "keys differ", sorted(set(a) ^ set(b))))
            return out
        for key in a:
            _diff_json(a[key], b[key], path + "/" + str(key), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "len", (len(a), len(b))))
            return out
        for i, (u, v) in enumerate(zip(a, b)):
            _diff_json(u, v, "%s/%d" % (path, i), out)
    elif isinstance(a, bool) or isinstance(b, bool) or \
            isinstance(a, str) or isinstance(b, str) or \
            a is None or b is None:
        if a != b:
            out.append((path, a, b))
    elif isinstance(a, int) and isinstance(b, int):
        if a != b:
            out.append((path, a, b))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not _close(a, b):
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def _block_part():
    xs = X0 + (np.arange(N) + 0.5) * CELL
    return np.where((np.abs(xs)[None, :] <= 15.0)
                    & (np.abs(xs)[:, None] <= 15.0), 10.0, 0.0)


GOUGE_GCODE = """G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z8. F100.
G1 X20. Y0. F500.
"""
SLOT_GCODE = """G21 G90 F500
G0 X-20. Y0. Z20.
G1 Z5. F100.
G1 X20. Y0. F500.
"""
PLUNGE_GCODE = """G21 G90 F500
G0 X0. Y0. Z20.
G1 Z0.5 F100.
G1 X10. Y0. F500.
"""
D_ZB = 9.525
CELL_B = 0.05
NB = 400
X0_B = Y0_B = -10.0
STOCK_B = (-10.0, 10.0, -10.0, 10.0, 0.0, 10.0)
BALL_SLOT_GCODE = ("G21 G90 F500\nG0 X-5.0000 Y0.0000 Z12.\n"
                   "G1 X-5.0000 Y0.0000 Z8.0000 F100.\n"
                   "G1 X5.0000 Y0.0000 F500.\n")


def test_fault_programs_identical_on_both_paths(tmp_path):
    """The injected-fault programs (gouge, full-width slot, axial plunge,
    ball slot via ZE2B) must give IDENTICAL gate counts and reports on the
    C and Python paths (floats within rel/abs 1e-9; zcut_kernel excluded)."""
    cases = [
        ("gouge", GOUGE_GCODE, _block_part(), CELL, X0, Y0, STOCK,
         ["--tool", "flat", "--dia", "6.0"]),
        ("slot", SLOT_GCODE, _block_part(), CELL, X0, Y0, STOCK,
         ["--tool", "flat", "--dia", "6.0", "--engage-max", "5.0"]),
        ("plunge", PLUNGE_GCODE, _block_part(), CELL, X0, Y0, STOCK,
         ["--tool", "flat", "--dia", "6.0"]),
        ("ball_slot", BALL_SLOT_GCODE, np.zeros((NB, NB)), CELL_B, X0_B,
         Y0_B, STOCK_B,
         ["--tool", "ball", "--dia", str(D_ZB), "--engage-max", "2.286"]),
    ]
    problems = []
    counts = {}
    for name, gc, part, cell, x0, y0, box, extra in cases:
        rc_c, rep_c = _cli(tmp_path, gc, part, cell, x0, y0, box, extra,
                           no_c=False)
        rc_p, rep_p = _cli(tmp_path, gc, part, cell, x0, y0, box, extra,
                           no_c=True)
        assert rep_c["zcut_kernel"] == "c", rep_c["zcut_kernel"]
        assert rep_p["zcut_kernel"] == "python", rep_p["zcut_kernel"]
        if rc_c != rc_p:
            problems.append(("/exit_code", rc_c, rc_p))
        rep_c.pop("zcut_kernel")
        rep_p.pop("zcut_kernel")
        bad = _diff_json(rep_c, rep_p, name)
        problems.extend(bad)
        counts[name] = {
            "rc": (rc_c, rc_p),
            "gouges": (rep_c["gouges"]["count"], rep_p["gouges"]["count"]),
            "rapids": (rep_c["rapid_collisions"]["count"],
                       rep_p["rapid_collisions"]["count"]),
            "axial": (rep_c["axial_plunges"]["count"],
                      rep_p["axial_plunges"]["count"]),
        }
        eng = rep_c.get("engagement")
        if eng:
            counts[name]["eng"] = (eng["count"],
                                   rep_p["engagement"]["count"])
            if "ze2b" in eng:
                counts[name]["ze2b_full"] = (
                    eng["ze2b"]["full_width"]["count"],
                    rep_p["engagement"]["ze2b"]["full_width"]["count"])
                counts[name]["ze2b_over"] = (
                    eng["ze2b"]["overload"]["count"],
                    rep_p["engagement"]["ze2b"]["overload"]["count"])
    print("gate counts (c, python):", json.dumps(counts, sort_keys=True))
    assert not problems, ("%d report fields outside the bar: %r"
                          % (len(problems), problems[:10]))
