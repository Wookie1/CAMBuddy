"""Task BS1a: trochoidal channel clearing for the hug-ring residue.

Per level, AFTER all Adaptive2d regions and BEFORE the hug rings: a hug-ring
run whose engagement against the LIVE stock model would be full width (stock
standing on both sides of the ring, at the level's full stepdown) can never
be a thin skim - Adaptive2d never entered that channel (no start point / over
the load), so the ring would slot the whole channel cross-section at cutting
feed. Here those runs are cleared first with TROCHOIDAL loops along the
channel centre line:

  * the centre line is marched from the ring point into the channel side
    (isl_ok3 at every step) to the middle of the CL-allowed sliver;
  * loop radius from the local allowed half-width (the circle fits inside the
    sliver with margin), capped so it stays a small trochoid;
  * advance per loop chosen so the simulated ZE2 load (area removed / travel
    in every 1 mm window against the live stock, entry bore pre-cleared)
    stays at/below the steady bar with spike headroom - the judge's window
    size is replayed on the engine's stock grid, disk applied at every
    emitted sample (conservative);
  * every emitted centre is isl_ok3 (the same oracle class the rings use);
    the level's allowance post-check, hf backstop and the final CLCHECK
    still gate the moves; links/entries go through the existing enter_at
    paths (2-deg helix + HB1v2 floor circle, or the RP2_1 SE2 side entry).

Runs whose sliver is narrower than MIN_SLIVER cannot host a loop or the
r >= 1.903 helix: they are REPORTED (stats["band_blocked"]) and left to the
ring, never forced (no plunge).
"""
import math
import os

import numpy as np

# ZE2 bars (verify/zmap.py): full width = ae_eff >= 0.9 x dia; the roughing
# target is steady 2.032, spike 2.438. Engine-side targets sit under them
# for grid/quantisation margin.
FW_FRAC = 0.9
AE_SS = 1.85            # steady target per 1 mm window
AE_SPIKE = 2.25         # spike target per 1 mm window
MIN_SLIVER = 4.0        # CL-allowed sliver needed to host loops + entry
LOOP_R_MIN = 0.8
LOOP_R_MAX = 3.2
OVER_FACTOR = 2.0       # calibration: measured area/travel vs the analytic
                        # p*(R+r)/(pi*r) (supervisor: ~2.7x advance at r~2)
P_CAP = 0.36          # empirical spike cap: the fresh lens at the channel-side
                      # loop apex is cut in one ~1 mm window (~6 mm2 per mm of
                      # advance on a 12.686 flat) - keep advance small
MARCH_STEP = 0.25       # sliver march resolution

# BS1a addendum item 3 (report-only what-if): env overrides of the EXISTING
# parameters - unset, every default below is unchanged and behaviour is
# byte-identical to the judged run. BS1A_LOOP_R_MAX=99 sizes loop radius
# purely from the local CL room (half-width minus 0.15 clearance, no clamp);
# AE_SS/AE_SPIKE/P_CAP are the same knobs the tuner already has.
_WHATIF = bool(os.environ.get("BS1A_WHATIF"))
if _WHATIF:
    LOOP_R_MAX = float(os.environ.get("BS1A_LOOP_R_MAX", LOOP_R_MAX))
    AE_SS = float(os.environ.get("BS1A_AE_SS", AE_SS))
    AE_SPIKE = float(os.environ.get("BS1A_AE_SPIKE", AE_SPIKE))
    P_CAP = float(os.environ.get("BS1A_P_CAP", P_CAP))
_ADV = {"n": 0, "sum": 0.0, "max": 0.0}     # advance stats (what-if only)


def _march(p, ux, uy, isl_ok3, maxd):
    """largest d = k*MARCH_STEP with every sampled point island-legal
    (exclusive of p, inclusive of the last good one) along +u from p."""
    d = 0.0
    while d + MARCH_STEP <= maxd:
        dn = d + MARCH_STEP
        if not isl_ok3([(p[0] + ux * dn, p[1] + uy * dn)])[0]:
            break
        d = dn
    return d


def _resample(pts, step=0.4):
    out = [pts[0]]
    need = step
    for a, b in zip(pts[:-1], pts[1:]):
        seg = math.dist(a, b)
        if seg < 1e-9:
            continue
        d = need
        while d <= seg:
            t = d / seg
            out.append((a[0] + (b[0] - a[0]) * t,
                       a[1] + (b[1] - a[1]) * t))
            d += step
        need = d - seg
    if math.dist(out[-1], pts[-1]) > 1e-9:
        out.append(pts[-1])
    return out


def _centreline(pts, isl_ok3, tool_r, leave):
    """For each resampled ring point march both normals; return one entry per
    point on the sliver centre line - (cx, cy, tx, ty, half_width) - or None
    where the channel-side sliver is too narrow (blocked spot)."""
    maxd = tool_r + leave + 3.0
    out = []
    n = len(pts)
    for i in range(n):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, n - 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        L = math.hypot(tx, ty)
        if L < 1e-9:
            out.append(None)
            continue
        tx, ty = tx / L, ty / L
        nx, ny = -ty, tx
        dp = _march(pts[i], nx, ny, isl_ok3, maxd)
        dm = _march(pts[i], -nx, -ny, isl_ok3, maxd)
        if dp > dm:
            d_ch, sgn = dp, 1.0
        else:
            d_ch, sgn = dm, -1.0
        # cap: a "channel" wider than R+leave on the far side is open
        # territory (e.g. past an island end), not a sliver to centre loops in
        d_ch = min(d_ch, tool_r + leave)
        d_wall = min(dp, dm)
        if d_ch < MIN_SLIVER:
            out.append(None)
            continue
        hw = (d_ch + d_wall) / 2.0
        off = (d_ch - d_wall) / 2.0
        out.append((pts[i][0] + sgn * nx * off, pts[i][1] + sgn * ny * off,
                   tx, ty, hw))
    return out


def _advance(r, tool_r):
    """advance per loop so the analytic crescent area/travel stays under the
    steady bar with the empirical OVER_FACTOR calibration."""
    p = AE_SS * math.pi * r / ((tool_r + r) * OVER_FACTOR)
    return max(LOOP_R_MIN * 0.3, min(p, P_CAP))


def _simulate(path, stock, z, tool_r, cell, bore_r):
    """Replay ZE2 windowing on the engine stock grid: fixed 1 mm windows of
    path travel; a window's area = distinct cells whose live top stands above
    z + 0.05 and that first fall under the cutter disk (applied at every
    emitted point) inside it. The entry bore (disk bore_r about the start) is
    pre-cleared - the helix + floor circle cut it at entry feed. Returns the
    list of per-window ae_eff estimates (mm)."""
    k = int(math.ceil(tool_r / cell))
    offs = [(dj, di) for dj in range(-k, k + 1) for di in range(-k, k + 1)
            if (dj * dj + di * di) * cell * cell <= tool_r * tool_r]
    kb = int(math.ceil(bore_r / cell))
    offs_b = [(dj, di) for dj in range(-kb, kb + 1)
              for di in range(-kb, kb + 1)
              if (dj * dj + di * di) * cell * cell <= bore_r * bore_r]
    i0 = max(min(stock._ci(p[0]) for p in path) - k - 1, 0)
    i1 = min(max(stock._ci(p[0]) for p in path) + k + 2, stock.nx)
    j0 = max(min(stock._cj(p[1]) for p in path) - k - 1, 0)
    j1 = min(max(stock._cj(p[1]) for p in path) + k + 2, stock.ny)
    if i0 >= i1 or j0 >= j1:
        return []
    stand = stock.top[j0:j1, i0:i1] > z + 0.05
    ci, cj = stock._ci(path[0][0]) - i0, stock._cj(path[0][1]) - j0
    for dj, di in offs_b:
        a, b = ci + di, cj + dj
        if 0 <= a < stand.shape[1] and 0 <= b < stand.shape[0]:
            stand[b, a] = False
    wins = []
    acc_area = 0.0
    acc_len = 0.0
    prev = None
    for (x, y) in path[1:]:
        step_len = math.dist(prev, (x, y)) if prev is not None else 0.0
        ci, cj = stock._ci(x) - i0, stock._cj(y) - j0
        removed = 0
        for dj, di in offs:
            a, b = ci + di, cj + dj
            if 0 <= a < stand.shape[1] and 0 <= b < stand.shape[0] \
                    and stand[b, a]:
                removed += 1
                stand[b, a] = False
        area = removed * cell * cell
        if prev is None:                       # first move: all into window
            acc_area += area
            acc_len += 0.0
        else:
            if acc_len + step_len >= 1.0 and step_len > 1e-9:
                frac = (1.0 - acc_len) / step_len
                win_area = acc_area + area * frac
                wins.append(win_area)
                rest = 1.0 - frac
                acc_area = area * rest
                acc_len = step_len * rest
            else:
                acc_area += area
                acc_len += step_len
        prev = (x, y)
    return wins


def _trochoid(seg, tool_r):
    """Parametric trochoid along the centre-line segment: point(s, t) =
    C(s) + r(s) * (cos t * n(s) + sin t * t(s)), one loop per advance p(r).
    seg entries are (x, y, tx, ty, half_width) at ~0.4 mm spacing. Returns
    (points, r_max)."""
    ls = [0.0]
    for a, b in zip(seg[:-1], seg[1:]):
        ls.append(ls[-1] + math.dist(a[:2], b[:2]))
    S = ls[-1]
    if S <= 0:
        return [], 0.0

    def at(s):
        s = min(max(s, 0.0), S)
        k = 0
        while k + 2 < len(ls) and ls[k + 1] <= s:
            k += 1
        a, b = seg[k], seg[min(k + 1, len(seg) - 1)]
        span = ls[k + 1] - ls[k] if k + 1 < len(ls) else 0.0
        t = 0.0 if span < 1e-9 else min(max((s - ls[k]) / span, 0.0), 1.0)
        hw = min(a[4], b[4])
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                a[2], a[3], hw)

    out = []
    s = 0.0
    t = 0.0
    rmax = 0.0
    k = 0                       # loop index (radial ramp)
    while s < S - 1e-9:
        rt = max(LOOP_R_MIN, min(at(s)[4] - 0.15, LOOP_R_MAX))
        # radial ramp: growing r by dr adds an annulus ~ 2*pi*(R+r)*dr whose
        # share per window must stay under the steady bar: dr <= AE*r/(R+r)
        r_used = min(rt, LOOP_R_MIN + 0.5 * AE_SS * k * rt / (tool_r + rt))
        p = _advance(r_used, tool_r)
        if _WHATIF:
            _ADV["n"] += 1
            _ADV["sum"] += p
            _ADV["max"] = max(_ADV["max"], p)
        dt = 0.35 / max(r_used, LOOP_R_MIN)   # ~0.35 mm arc/point
        n = max(8, int(math.ceil(2.0 * math.pi / dt)))
        for i in range(n + 1):
            tt = t + i * 2.0 * math.pi / n
            ss = min(s + p * i / n, S)
            cc = at(ss)
            r = max(LOOP_R_MIN, min(cc[4] - 0.15, LOOP_R_MAX))
            r = min(r, r_used)
            rmax = max(rmax, r)
            out.append((cc[0] + r * (math.cos(tt) * (-cc[3])
                                    + math.sin(tt) * cc[2]),
                        cc[1] + r * (math.cos(tt) * cc[2]
                                    + math.sin(tt) * cc[3])))
        t += 2.0 * math.pi
        s += p
        k += 1
    clean = []
    for q in out:
        if not clean or math.dist(clean[-1], q) > 1e-6:
            clean.append(q)
    return clean, rmax


def channel_regions(rings, stock, isl_ok3, z, tool_r, leave, cell,
                    stats=None):
    """rings: hug_regions output for this level (before emission, live stock
    at start of level). Returns trochoidal channel-clear region dicts to emit
    BEFORE the rings. stats gets n_band_regions / band_cut_len_mm /
    band_blocked [(z, x, y), ...]."""
    from engine.rough import _strip_engage
    regions = []
    if not rings:
        return regions
    fw_min = FW_FRAC * 2.0 * tool_r
    done = np.zeros((stock.ny, stock.nx), dtype=bool)
    blocked = []
    for res in rings:
        for (kind, pts) in res["paths"]:
            if kind != "cutting" or len(pts) < 2:
                continue
            eng = _strip_engage(stock, pts, z, tool_r)
            if eng < fw_min:
                continue
            dense = _resample(pts, step=0.4)
            cl = _centreline(dense, isl_ok3, tool_r, leave)
            prev_bad = None
            for i, s in enumerate(cl):
                if s is None:
                    if (prev_bad is None
                            or math.dist(prev_bad, dense[i][:2]) > 2.0):
                        blocked.append((round(dense[i][0], 2),
                                      round(dense[i][1], 2)))
                    prev_bad = dense[i][:2]
            segs = []
            cur = []
            for s in cl:
                if s is None:
                    if len(cur) >= 4:
                        segs.append(cur)
                    cur = []
                else:
                    cur.append(list(s))
            if len(cur) >= 4:
                segs.append(cur)
            for seg in segs:
                length = sum(math.dist(seg[i][:2], seg[i + 1][:2])
                             for i in range(len(seg) - 1))
                if length < 2.0 * tool_r:
                    continue       # run shorter than D: zig-zag not allowed
                hits = sum(1 for s in seg[::4]
                           if 0 <= stock._ci(s[0]) < stock.nx
                           and 0 <= stock._cj(s[1]) < stock.ny
                           and done[stock._cj(s[1]), stock._ci(s[0])])
                tot = max(1, len(seg[::4]))
                if hits > 0.5 * tot:
                    continue       # opposite wall's ring of the same channel
                for shrink in (1.0, 0.75, 0.55, 0.4):
                    shrunk = [tuple(s[:4]) + (s[4] * shrink,) for s in seg]
                    path, rmax = _trochoid(shrunk, tool_r)
                    if len(path) < 6:
                        break
                    wins = _simulate(path, stock, z, tool_r, cell,
                                    1.3 * tool_r)   # smallest helix tier bore
                    if not wins:
                        break
                    spike = max(wins)
                    ss = sorted(wins)[max(0, int(0.95 * len(wins)) - 1)]
                    if ss <= AE_SS and spike <= AE_SPIKE:
                        break
                good = isl_ok3([(round(x, 4), round(y, 4))
                               for (x, y) in path])
                pts_out = [(round(p[0], 4), round(p[1], 4))
                           for p, g in zip(path, good) if g]
                if len(pts_out) < 4:
                    continue
                for s in seg:
                    i, j = stock._ci(s[0]), stock._cj(s[1])
                    if 0 <= i < stock.nx and 0 <= j < stock.ny:
                        done[j, i] = True
                regions.append({"start": list(pts_out[0]), "helix": None,
                               "paths": [["cutting", pts_out]]})
    if stats is not None:
        stats["n_band_regions"] = stats.get("n_band_regions", 0) + len(regions)
        stats["band_cut_len_mm"] = round(
            stats.get("band_cut_len_mm", 0.0)
            + sum(sum(math.dist(a, b)
                      for a, b in zip(r["paths"][0][1][:-1],
                                     r["paths"][0][1][1:]))
                  for r in regions), 1)
        if blocked:
            stats.setdefault("band_blocked", []).extend(
                (round(z, 3), b[0], b[1]) for b in blocked[:40])
        if _WHATIF and _ADV["n"]:
            stats["band_advance_mean_mm"] = round(
                _ADV["sum"] / _ADV["n"], 3)
            stats["band_advance_max_mm"] = round(_ADV["max"], 3)
    return regions
