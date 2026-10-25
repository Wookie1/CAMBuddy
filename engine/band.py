"""Task BS1a3: trochoidal channel clearing for the hug-ring residue.

Per level, AFTER every Adaptive2d region has been emitted and milled: where
a ring's own ZE2 windows against that LIVE stock are full width (ae_eff >=
FW_FRAC x D, plus a small lead-in/out), the ring can never
be a thin skim - Adaptive2d never entered that channel (no start point / over
the load), so the ring would slot the whole channel cross-section at cutting
feed. Those stretches are cleared first with TROCHOIDAL loops along the
channel centre line; light / over-load-only windows stay with the ring (BS1b):

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
from contextvars import ContextVar

import numpy as np

# ZE2 bars (verify/zmap.py): full width = ae_eff >= 0.9 x dia; the roughing
# target is steady 2.032, spike 2.438. Engine-side targets sit under them
# for grid/quantisation margin.
FW_FRAC = 0.9
# BS1a3b: the selection triggers BELOW the judge's 0.9 x D - its replay of the
# ZE2 windows on the engine stock grid reads a little under zmap's grid
# (one 1.06 mm ring window at ae_eff 11.91 >= 11.42 slipped through on Core
# Front, Z 42.926); the judge's own threshold stays 0.9 x D
FW_TRIGGER = 0.85
AE_SS = 1.85            # steady target per 1 mm window
AE_SPIKE = 2.25         # spike target per 1 mm window
SPIKE_MM = 2.44         # judge overload bar (zmap OVERLOAD_WIDTH_MM)
DIR_COS = math.cos(math.radians(45.0))   # zmap AE2_DIR_MAX_DEG link rule
MIN_SLIVER = 4.0        # CL-allowed sliver needed to host loops + entry
LOOP_R_MIN = 0.8
LOOP_R_MAX = 3.2
OVER_FACTOR = 2.0       # calibration: measured area/travel vs the analytic
                        # p*(R+r)/(pi*r) (supervisor: ~2.7x advance at r~2)
P_CAP = 0.36          # empirical spike cap: the fresh lens at the channel-side
                      # loop apex is cut in one ~1 mm window (~6 mm2 per mm of
                      # advance on a 12.686 flat) - keep advance small
MARCH_STEP = 0.25       # sliver march resolution
FW_LEAD_PTS = 3         # lead-in/out (x 0.4 mm) around a full-width run
class bore_context:     # BS1a4d-f: SCOPED bore fn (no bare module global):
    _B = ContextVar("bs1a4d_borefn", default=None)
    def __init__(self, fn): self._t = bore_context._B.set(fn)
    def __enter__(self): return self
    def __exit__(self, *e): bore_context._B.reset(self._t)


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


def _split_at_jumps(isl_ok3, pts):
    """BS1a4c-2: split a band path at every chord failing a segment-sampled
    CL check (every <= 0.25 mm, the way validate_exact samples segments)."""
    out = [[pts[0]]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(math.dist(a, b) / 0.25)))
        if all(isl_ok3([(a[0] + (b[0] - a[0]) * t / n,
                          a[1] + (b[1] - a[1]) * t / n)
                         for t in range(n + 1)])):
            out[-1].append(b)
        else:
            out.append([b])
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


def _simulate(path, stock, z, tool_r, cell, bore_r, ends=None, *, bore_xy=None,
              entry="bore"):
    """Replay ZE2 windowing on the engine stock grid: move-aligned windows of
    path travel; a window's area = distinct cells whose live top stands above
    z + 0.05 and that first fall under the cutter disk (applied at every
    emitted point) inside it. The entry bore (disk bore_r about the start or
    bore_xy - BS1a4d (c) helix centre) is
    pre-cleared when entry="bore"; "side"/"link" not (BS1a4d6c). Returns the
    list of per-window ae_eff estimates (mm); ends collects each window's
    cumulative end-of-window travel (zmap _ae2_windows: moves merge until the
    window reaches 1 mm, a move >= 1 mm is its own window)."""
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
    bx, by = (bore_xy[:2] if bore_xy else path[0][:2])
    ci, cj = stock._ci(bx) - i0, stock._cj(by) - j0
    # BS1a4d6c: pre-clear only the emitted entry's footprint (see entry).
    for dj, di in (offs_b if entry == "bore" else ()):
        a, b = ci + di, cj + dj
        if 0 <= a < stand.shape[1] and 0 <= b < stand.shape[0]:
            stand[b, a] = False
    wins = []
    acc_area = 0.0
    acc_len = 0.0
    tot = 0.0
    prev = (path[0][0], path[0][1])   # BS1a4 Fix 2: the first move is a
    # real move: its length enters window 0 (zmap's _ae2_windows counts every
    # horizontal feed move), so engine windows close where zmap's close.
    pdir = None
    for (x, y) in path[1:]:
        step_len = math.dist(prev, (x, y))
        tot += step_len
        if step_len > 1e-9:
            d = ((x - prev[0]) / step_len, (y - prev[1]) / step_len)
            if pdir is not None and d[0] * pdir[0] + d[1] * pdir[1] < DIR_COS:
                acc_area = 0.0       # >45 deg chord break (zmap link rule):
                acc_len = 0.0        # the sub-1 mm fragment is dropped there
            pdir = d
        ci, cj = stock._ci(x) - i0, stock._cj(y) - j0
        removed = 0
        for dj, di in offs:
            a, b = ci + di, cj + dj
            if 0 <= a < stand.shape[1] and 0 <= b < stand.shape[0] \
                    and stand[b, a]:
                removed += 1
                stand[b, a] = False
        area = removed * cell * cell
        acc_area += area
        acc_len += step_len
        if acc_len >= 1.0:                 # move-aligned windows (judge)
            wins.append(acc_area)
            if ends is not None:
                ends.append(tot)
            acc_area = 0.0
            acc_len = 0.0
        prev = (x, y)
    return wins


def entry_credit(stock, p0, z, tool_r):
    """BS1a4c honest entry credit (bs1b f3f2165): tool_r only where standing
    stock under the start disk forces a helix at emit; else 0."""
    k = int(math.ceil(tool_r / stock.cell))
    ci, cj = stock._ci(p0[0]), stock._cj(p0[1])
    for dj in range(-k, k + 1):
        for di in range(-k, k + 1):
            if (di * di + dj * dj) * stock.cell ** 2 <= tool_r * tool_r \
                    and 0 <= ci + di < stock.nx and 0 <= cj + dj < stock.ny \
                    and stock.top[cj + dj, ci + di] > z + 0.05:
                return tool_r
    return 0.0


def _opt_key(wins, ends, fw_min):
    """BS1a4b rank key for the lightest option of a gate-failing region:
    fewest full-width windows at cutting feed, then lowest max ae, then
    shortest travel in windows over SPIKE_MM - all on aligned _simulate
    windows."""
    over = sum((ends[i] - (ends[i - 1] if i else 0.0))
               for i, v in enumerate(wins) if v > SPIKE_MM)
    return (sum(1 for v in wins if v >= fw_min), max(wins), over)


def shrink_ladder(seg, stock, z, tool_r, cell, credit=None, dropopt=None,
                  borefn=None):
    """BS1a4d: channel_regions' shrink ladder AND Fix 1's lightest-option
    ranking as one callable, so the emit-time credit-0 re-plan (a0) reuses
    them: credit 0.0 on the LIVE stock vs drop-ring, same _opt_key rank
    (FW windows at cutting feed, then max ae, then travel over SPIKE_MM).
    credit None = entry_credit at each level's own start; with a borefn the
    credit is the real bore footprint (BS1a4d (c)). Returns
    (option, path-or-None, wins, best_area, gate_ok)."""
    opts = []
    best_area = 0.0
    gate_ok = False
    for shrink in (1.0, 0.75, 0.55, 0.4):
        shrunk = [tuple(s[:4]) + (s[4] * shrink,) for s in seg]
        path, _r = _trochoid(shrunk, tool_r)
        if len(path) < 6:
            break
        we = []
        cr = (entry_credit(stock, path[0], z, tool_r) if credit is None
              else credit)
        bxy = borefn(path[0], z) if (cr > 1e-9 and borefn) else None
        if borefn and not bxy:
            cr = 0.0   # BS1a4d4 (c): no predicted bore = unbacked credit
        wins = _simulate(path, stock, z, tool_r, cell,
                        cr + (bxy[2] if bxy else 0.0), we, bore_xy=bxy,
                        entry="bore" if cr > 1e-9 else "side")
        if not wins:
            break
        best_area = max(best_area, sum(wins))
        opts.append((shrink, path, wins, we))
        if max(wins) <= AE_SPIKE and sorted(wins)[
                max(0, int(0.95 * len(wins)) - 1)] <= AE_SS:
            gate_ok = True
            break
    if gate_ok:
        return ("shrink%g" % opts[-1][0], opts[-1][1], opts[-1][2],
                best_area, True)
    cand = [(_opt_key(w, e, FW_TRIGGER * 2.0 * tool_r), "shrink%g" % s,
             p, w) for (s, p, w, e) in opts]
    if dropopt is not None:
        cand.append(dropopt)
    _k, opt, path, wins = min(cand, key=lambda c: c[0])
    return opt, path, wins, best_area, False


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
    """rings: hug_regions output for this level; stock is the LIVE model AFTER
    this level's Adaptive2d regions have been emitted and milled. Per ring
    path the ZE2 windows are replayed on that live stock (entry bore
    pre-cleared) and ONLY the full-width stretches - windows with ae_eff >=
    FW_FRAC x D, plus a FW_LEAD_PTS-sample lead-in/out - are trochoided;
    light / over-load-only windows are left to the ring (BS1b's job). stats
    gets n_band_regions / band_cut_len_mm / band_cl_len_mm / band_blocked."""
    borefn = bore_context._B.get()   # BS1a4d-f: set by rough.py, or None
    regions = []
    if not rings:
        return regions
    fw_min = FW_TRIGGER * 2.0 * tool_r
    done = np.zeros((stock.ny, stock.nx), dtype=bool)
    blocked = []
    cl_len = 0.0
    for res in rings:
        for (kind, pts) in res["paths"]:
            if kind != "cutting" or len(pts) < 2:
                continue
            dense = _resample(pts, step=0.4)
            wb = []
            wins = _simulate(pts, stock, z, tool_r, cell, 1.3 * tool_r, wb,
                             entry="bore")
            if not wins:
                continue
            drop_opt = (_opt_key(wins, wb, fw_min), "drop_ring", None, wins)
            # a dense sample is judged by the same window zmap will use:
            arc = [0.0]
            for a, b in zip(dense[:-1], dense[1:]):
                arc.append(arc[-1] + math.dist(a[:2], b[:2]))
            mark = [False] * len(dense)
            w = 0
            for i, s in enumerate(arc):
                while w < len(wb) and wb[w] < s:
                    w += 1
                if w >= len(wins):
                    break                       # trailing < 1 mm: judge drops it
                if wins[w] < fw_min:
                    continue
                lo = max(0, i - FW_LEAD_PTS)
                hi = min(len(dense), i + FW_LEAD_PTS + 1)
                for k in range(lo, hi):
                    mark[k] = True
            if not any(mark):
                continue
            cl = _centreline(dense, isl_ok3, tool_r, leave)
            prev_bad = None
            for i, s in enumerate(cl):
                if mark[i] and s is None:      # FW spot, no CL room to host
                    if (prev_bad is None
                            or math.dist(prev_bad, dense[i][:2]) > 2.0):
                        blocked.append((round(dense[i][0], 2),
                                      round(dense[i][1], 2)))
                prev_bad = (dense[i][:2] if mark[i] and s is None else None)
            segs = []
            cur = []
            for i, s in enumerate(cl):
                if s is None or not mark[i]:
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
                opt, path, wins, best_area, gate_ok = shrink_ladder(
                    seg, stock, z, tool_r, cell, None, drop_opt, borefn)
                if not gate_ok:
                    # BS1a4b: every level failed; Fix 1's lightest option was
                    # chosen in shrink_ladder. Never silent: place, Z, area,
                    # option and engine max ae into failed_region_emitted.
                    if stats is not None:
                        stats.setdefault("failed_region_emitted", []).append(
                            {"x": round(seg[0][0], 3), "y": round(seg[0][1], 3),
                             "z": round(z, 3), "area": round(best_area, 2),
                             "option": opt,
                             "max_ae": round(max(wins), 3) if wins else None})
                    if path is None:
                        continue   # dropped: stock stays live for the ring
                good = isl_ok3([(round(x, 4), round(y, 4))
                               for (x, y) in path])
                pts_out = [(round(p[0], 4), round(p[1], 4))
                           for p, g in zip(path, good) if g]
                if len(pts_out) < 4:
                    continue
                pieces = _split_at_jumps(isl_ok3, pts_out)   # BS1a4c-2
                if stats is not None:      # stubs: no legal join -> reject,
                    lbl = opt + " split"   # BS1a4d: opt set on both routes
                    fre = stats.setdefault("failed_region_emitted", [])
                    for pc in pieces:
                        if len(pc) < 4:
                            fre.append({"x": round(pc[0][0], 3),
                                      "y": round(pc[0][1], 3), "z": round(z, 3),
                                      "area": round(best_area, 2),
                                      "option": lbl})
                pieces = [pc for pc in pieces if len(pc) >= 4]
                if not pieces:
                    continue   # every piece a stub: nothing emitted, ring's
                for s in seg:      # stock stays live; done-marking would lie
                    i, j = stock._ci(s[0]), stock._cj(s[1])
                    if 0 <= i < stock.nx and 0 <= j < stock.ny:
                        done[j, i] = True
                cl_len += length
                for pc in pieces:  # BS1a4c-2: piece = own region, own ladder
                    regions.append({"start": list(pc[0]), "helix": None,
                                   "paths": [["cutting", pc]]})
                    regions[-1]["credit"] = entry_credit(stock, pc[0], z,
                                                        tool_r)  # back at emit
                    if borefn and regions[-1]["credit"] > 1e-9:
                        # BS1a4d4: the bore the predictor accepted IS the entry
                        _b = borefn(pc[0], z)
                        if _b:
                            regions[-1]["bore"] = (round(pc[0][0], 4),
                                                   round(pc[0][1], 4)) + _b
                            b0 = borefn(path[0], z) or (0.0, 0.0, -9.0)
                            if max(abs(u - v) for u, v in zip(_b, b0)) > 1e-6:
                                regions[-1]["replan0"] = 2
                                if stats is not None:
                                    stats.setdefault("credit_fallback",
                                        []).append((pc[0][0], pc[0][1],
                                        round(z, 3), "plan0_splitbore"))
                        else:   # BS1a4d4 (c): unbacked -> credit 0, listed
                            regions[-1]["credit"] = 0.0
                            # planned with a bore at path[0] the piece won't
                            # get: re-checked at emit at credit 0 (plan0_split)
                            sp = bool(borefn(path[0], z))
                            regions[-1]["replan0"] = sp
                            if stats is not None:
                                stats.setdefault("credit_fallback", []).append(
                                    (round(pc[0][0], 4), round(pc[0][1], 4),
                                     round(z, 3), "plan0_split" if sp
                                     else "plan0_nobore"))
                    regions[-1]["seg"] = seg        # BS1a4d (a0): centre line
                    regions[-1]["dropkey"] = drop_opt[0]   # + ring rank key
    if stats is not None:
        stats["n_band_regions"] = stats.get("n_band_regions", 0) + len(regions)
        # BS1a4b: every region that failed its gate at every shrink level is
        # listed here with the option chosen for it - never silent.
        stats.setdefault("failed_region_emitted", [])
        stats["band_cut_len_mm"] = round(
            stats.get("band_cut_len_mm", 0.0)
            + sum(sum(math.dist(a, b)
                      for a, b in zip(r["paths"][0][1][:-1],
                                     r["paths"][0][1][1:]))
                  for r in regions), 1)
        stats["band_cl_len_mm"] = round(
            stats.get("band_cl_len_mm", 0.0) + cl_len, 1)
        if blocked:
            stats.setdefault("band_blocked", []).extend(
                (round(z, 3), b[0], b[1]) for b in blocked[:40])
    return regions
