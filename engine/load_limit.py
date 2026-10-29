"""FL-LOAD: optional rough feed limiter (default OFF).

limit_feeds() replays the EMITTED rough moves into the engine's own 0.1 mm
stock move by move (the flat/corner disk stamping of entry_depth.replay_stock;
G0 never cuts) and measures every feed move against the stock BEFORE it:
ae = plan area of the cells it removes / its length (each cell once, live
stock), a = deepest removed column. Feed moves combine into ZE2-form windows
(minimal runs of >= 1 mm travel; a rapid, a Z change, a feed change or a
direction change > 45 deg ends a window; a sub-1 mm tail merges into its
neighbour). Per window the load is James's rule (ZE2L):

    load = ae_eff * a * F / (2.032 * 19.05 * Fcut)

Where load > 1.2 and the window is not an allowed floor turn (carries a
helix_pitch, a <= helix_pitch + 0.05 and load <= 1.2 - ZE2F2), the window's
feed drops to F * 1.2 / load - never raised, never below the floor of 25% of
Fcut (when the floor binds the window counts as floor_bound). Only F words
change: the XYZ path is identical. Returns (new_moves, stats) with stats
{windows_slowed, mm_slowed, min_feed, floor_bound}.
"""
import math
import os

import numpy as np

from engine import ckern as _ckern
from engine import entry_depth

FINE = entry_depth.FINE            # 0.1 mm, the judge's cell
LOAD_MAX = 1.2                     # ZE2L: window load above this is over-limit
PITCH_TOL = 0.05                   # ZE2F2: a <= pitch + 0.05 marks a floor turn
WINDOW_MM = 1.0                    # ZE2: minimal window travel
DIR_COS = math.cos(math.radians(45.0))   # ZE2: direction change cap
DESIGN_AE = 2.032                  # the load rule's reference ae / a mm
DESIGN_STEPDOWN = 19.05
REMOVE_EPS = 1e-9                  # zmap's air threshold (mm removed)
CARRY_EXTRA_MM = 1.0               # ZE2F2: helix-pitch carry margin
FEED_FLOOR_FRAC = 0.25             # feed floor: 25% of the cutting feed
# The judge (zmap --load-rule) re-measures the slowed program independently;
# its window areas run ~1% above this engine-side replay. One fixed margin
# for trigger and target (coordinator): slow when load > 1.2 x MARGIN, to
# 1.2 x MARGIN, so the judge's load lands at or below 1.2.
MARGIN = 0.97


def _helix_radius(run):
    """Mean radius of a descending run about its XY centroid (0 if none)."""
    if len(run) < 4:
        return 0.0
    P = np.asarray(run, dtype=float)
    c = P[:, :2].mean(axis=0)
    return float(np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]).mean())


def _helix_pitch(run):
    """Measured pitch (Z drop per full turn) of a descending feed run, or
    None when it is not a helix (fewer than 4 points, radius under 0.05 mm -
    a straight plunge/ramp - or no XY travel or no descent)."""
    if len(run) < 4:
        return None
    P = np.asarray(run, dtype=float)
    c = P[:, :2].mean(axis=0)
    r = float(np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]).mean())
    arc = float(np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1])).sum())
    dz = float(P[0, 2] - P[-1, 2])
    if r < 0.05 or arc <= 1e-9 or dz <= 0.0:
        return None
    return round(dz / (arc / (2.0 * math.pi * r)), 4)


_CKERN = _ckern.get_lib()      # SP-K1: compiled twin of _stamp_move, or None
_CKERN_PRINTED = False


def _ckern_for_call():
    """The kernel library for this call: None while STEVECAM_NO_CKERN is set
    (or the .dylib is missing); prints the chosen path once."""
    global _CKERN_PRINTED
    use = None if os.environ.get("STEVECAM_NO_CKERN") else _CKERN
    if not _CKERN_PRINTED:
        print("load_limit._stamp_move: %s kernel"
              % ("compiled C (ckern)" if use is not None else "Python"))
        _CKERN_PRINTED = True
    return use


def _stamp_move(L, x0, y0, fine, R, cr, a0, kR, pad2, p, cur):
    """Stamp one G1 move into L (the replay_stock disk profile: flat inside
    R - cr, the corner torus beyond; G0 never cuts - caller) sampled at
    <= fine/4, and measure what it removed against the LIVE stock BEFORE it:
    (area, depth) = (plan area of cells removed, each counted once, deepest
    removed column)."""
    _lib = _ckern_for_call()
    if _lib is not None:
        return _ckern.stamp_move(L, x0, y0, fine, R, cr, a0, kR, pad2, p,
                                 cur, REMOVE_EPS)
    dx, dy, dz = (cur[k] - p[k] for k in range(3))
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    n = 1 if length <= 0.0 else max(2, int(math.ceil(length / (fine / 4.0))))
    H, W = L.shape
    area = 0.0
    depth = 0.0
    for t in np.linspace(0.0, 1.0, n + 1):
        sx, sy, sz = p[0] + dx * t, p[1] + dy * t, p[2] + dz * t
        ci = int(math.floor((sx - x0) / fine)) + pad2
        cj = int(math.floor((sy - y0) / fine)) + pad2
        i0, i1 = max(0, ci - kR), min(W, ci + kR + 1)
        j0, j1 = max(0, cj - kR), min(H, cj + kR + 1)
        if i0 >= i1 or j0 >= j1:
            continue
        gx = x0 + ((np.arange(i0, i1) - pad2) + 0.5) * fine - sx
        gy = y0 + ((np.arange(j0, j1) - pad2) + 0.5) * fine - sy
        dd = np.hypot(gx[None, :], gy[:, None])
        m = dd <= R + 1e-9
        if cr:
            o = np.maximum(dd - a0, 0.0)
            surf = cr - np.sqrt(np.maximum(cr * cr - o * o, 0.0))
        else:
            surf = 0.0
        newv = np.where(m, sz + surf, np.inf)
        w = L[j0:j1, i0:i1]
        cut = w - newv
        nrem = int(np.count_nonzero(cut > REMOVE_EPS))
        if nrem:
            area += nrem * fine * fine
            dmax = float(np.max(cut))
            if np.isfinite(dmax) and dmax > depth:
                depth = dmax
        np.minimum(w, newv, out=w)
    return area, depth


def _windows(recs):
    """ZE2 windowing (zmap._ae2_windows without the report-only width/hist
    fields): minimal runs of >= 1 mm travel of consecutive horizontal feed
    moves at the same Z and feed, direction change <= 45 deg; a sub-1 mm
    tail merges into the kept window before it (else after; none: dropped).
    Each window carries the move indices it covers."""
    windows, tails, cur = [], [], None

    def close(w):
        if w["length_mm"] >= WINDOW_MM:
            windows.append(w)
        else:
            tails.append((w, len(windows)))

    for e in recs:
        link = (cur is not None and e["idx"] == cur["idx"] + 1
                and e["z"] == cur["z"] and e["feed"] == cur["feed"]
                and e["dx"] * cur["dx"] + e["dy"] * cur["dy"] >= DIR_COS)
        if not link:
            if cur is not None:
                close(cur)
            cur = {"idx": e["idx"], "z": e["z"], "dx": e["dx"], "dy": e["dy"],
                   "area_mm2": e["area_mm2"], "length_mm": e["length_mm"],
                   "a": e["depth_mm"], "feed": e["feed"],
                   "helix_pitch": e["helix_pitch"], "move_idxs": [e["idx"]]}
        else:
            cur["idx"] = e["idx"]
            cur["dx"], cur["dy"] = e["dx"], e["dy"]
            cur["area_mm2"] += e["area_mm2"]
            cur["length_mm"] += e["length_mm"]
            cur["a"] = max(cur["a"], e["depth_mm"])
            cur["move_idxs"].append(e["idx"])
        if cur["length_mm"] >= WINDOW_MM:
            close(cur)
            cur = None
    if cur is not None:
        close(cur)
    for w, n in tails:
        tgt = windows[n - 1] if n else (windows[0] if windows else None)
        if tgt is None:
            continue
        tgt["area_mm2"] += w["area_mm2"]
        tgt["length_mm"] += w["length_mm"]
        tgt["a"] = max(tgt["a"], w["a"])
        tgt["move_idxs"] = tgt["move_idxs"] + w["move_idxs"]
    return windows


def limit_feeds(moves, dia, corner, box, top_z, cut_feed, fine=FINE,
                return_stock=False):
    """Slow the feed on over-loaded ZE2 windows of an emitted rough move
    list (see module docstring). Returns (new_moves, stats); only F words
    change. SP-P1A: return_stock=True also returns (A, x0, y0, fine), the
    final replayed stock - identical to entry_depth.replay_stock of the same
    moves (only F words differ), so the CLI skips that second replay."""
    R = float(dia) / 2.0
    cr = min(float(corner), R) if corner else 0.0
    a0 = R - cr
    kR = int(math.ceil(R / fine))
    pad2 = kR + 1 + 2 * kR + 2          # entry_depth.replay_stock's pad2
    xmn, xmx, ymn, ymx = (float(v) for v in box[:4])
    x0, y0 = xmn - R, ymn - R
    cx = x0 + (np.arange(int(math.ceil((xmx - xmn + 2 * R) / fine))) + .5) * fine
    cy = y0 + (np.arange(int(math.ceil((ymx - ymn + 2 * R) / fine))) + .5) * fine
    F = np.where(((cx >= xmn - 1e-9) & (cx <= xmx + 1e-9))[None, :]
                 & ((cy >= ymn - 1e-9) & (cy <= ymx + 1e-9))[:, None],
                 float(top_z), -np.inf)
    L = np.pad(F, pad2, constant_values=-np.inf)

    out = [dict(m) for m in moves]
    recs = []
    desc_run, hp_carry, pos = [], None, None
    for mi, mv in enumerate(moves):
        cur = tuple(pos[i] if mv.get(k) is None else mv[k]
                    for i, k in enumerate("xyz")) \
            if pos is not None else (mv.get("x"), mv.get("y"), mv.get("z"))
        if None in cur:
            cur = tuple(v if v is not None else 0.0 for v in cur)
        if pos is not None and mv["g"] == 1:
            area, depth = _stamp_move(L, x0, y0, fine, R, cr, a0, kR, pad2,
                                      pos, cur)
            dx, dy, dz = (cur[k] - pos[k] for k in range(3))
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if abs(dz) <= 1e-6 and length > 0.0:
                # ZE2F2: the pitch of the helix just made carries to the
                # contiguous run at its bottom Z and feed (bounded)
                hp = _helix_pitch(desc_run)
                if hp is not None:
                    hp_carry = [hp, round(cur[2], 3), mv.get("f"),
                                2.0 * math.pi * _helix_radius(desc_run)
                                + CARRY_EXTRA_MM, length]
                elif (hp_carry is not None
                      and hp_carry[1] == round(cur[2], 3)
                      and hp_carry[2] == mv.get("f")
                      and hp_carry[4] + length <= hp_carry[3]):
                    hp = hp_carry[0]
                    hp_carry[4] += length
                else:
                    hp = None
                    hp_carry = None
                lxy = math.hypot(dx, dy)
                ux, uy = (dx / lxy, dy / lxy) if lxy > 1e-9 else (1.0, 0.0)
                recs.append({"idx": mi, "z": round(cur[2], 3),
                             "feed": mv.get("f"), "dx": ux, "dy": uy,
                             "length_mm": length, "area_mm2": area,
                             "depth_mm": depth, "helix_pitch": hp})
            if cur[2] < pos[2] - 1e-6:
                if math.hypot(dx, dy) <= 1e-6:
                    desc_run = [(cur[0], cur[1], cur[2])]
                else:
                    if not desc_run:
                        desc_run.append((pos[0], pos[1], pos[2]))
                    desc_run.append((cur[0], cur[1], cur[2]))
            else:
                desc_run = []
            if hp_carry is not None and not (
                    abs(cur[2] - pos[2]) <= 1e-6
                    and round(cur[2], 3) == hp_carry[1]
                    and mv.get("f") == hp_carry[2]):
                hp_carry = None
        else:
            desc_run, hp_carry = [], None
        pos = cur

    ref = DESIGN_AE * DESIGN_STEPDOWN * float(cut_feed)
    floor = FEED_FLOOR_FRAC * float(cut_feed)
    slowed = mm = 0
    floor_bound = 0
    for w in _windows(recs):
        ae_eff = round(w["area_mm2"] / w["length_mm"], 4)
        feed = w["feed"] or cut_feed
        load = round(ae_eff * w["a"] * feed / ref, 4)
        allowed = (w["helix_pitch"] is not None
                   and w["a"] <= w["helix_pitch"] + PITCH_TOL
                   and load <= LOAD_MAX)
        if load <= LOAD_MAX * MARGIN or allowed:
            continue
        slowed += 1
        mm += w["length_mm"]
        hit_floor = False
        for mi in w["move_idxs"]:
            f0 = out[mi].get("f") or cut_feed
            f_new = f0 * LOAD_MAX * MARGIN / load
            if f_new < floor:
                f_new = floor
                hit_floor = True
            out[mi]["f"] = f_new
        if hit_floor:
            floor_bound += 1
    feeds = [mv["f"] for mv in out if mv["g"] == 1 and mv.get("f")]
    stats = {"windows_slowed": slowed,
             "mm_slowed": round(mm, 3),
             "min_feed": min(feeds) if feeds else None,
             "floor_bound": floor_bound}
    if return_stock:
        return out, stats, (L[pad2:-pad2, pad2:-pad2].copy(), x0, y0, fine)
    return out, stats
