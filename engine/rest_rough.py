"""T20-style ball rest-rough for the material the big flat tool left.

Task RR1b. Live stock more than `min_excess` mm above the part cannot be
removed by the finishing ball in one stepover; this generator machines that
rest with a ball:

  * zones: 8-connected components where
    live stock - max(exact part ball-CL, floor_z) > min_excess (>= 5 mm2);
  * entry per zone: one helix at r_h = 0.8 * r_max, where r_max is the
    largest inscribed CL-circle radius of the leave-legal region at the
    deepest ENTERABLE level (FE5 rule); deeper levels whose r_max is below
    min_helix_r are skipped and reported. r_max < min_helix_r for every
    level -> the zone is REPORTED (no legal entry), never drilled or forced;
  * then one flat floor circle at r_h (ramp feed, only if legal) and
    z-level contours at c = ae/2 stepping ae, greedy-nearest pass order,
    rising in place between levels;
  * no axial plunges: every scored descent (pass start after a G0) is
    checked with the FE5 disk rule against LIVE stock (stamp_chord order,
    engine/entry_depth.py) and must stay <= zb_floor; links feed only along
    paths keeping leave above the exact part CL, else verified rapid +
    landing check, else the pass is skipped;
  * fail closed: every feed path point must sit leave above the exact part
    ball-CL (validate_exact, 0.005 mm) before posting.

Z convention: tip Z everywhere (matches the posted NC and zmap). Every T20
value is a parameter - no machine numbers live here; the connector holds
defaults.
"""
import math

import numpy as np
from scipy import ndimage

from . import entry_depth as fin
from .finish import batch_drop, make_cutter, march_level

CELL = 0.2          # mm, zone/contour grid (stock is max-resampled to this)


def _grid(stock):
    A, x0, y0, cell = stock
    xs = x0 + (np.arange(int((A.shape[1] * cell) / CELL)) + 0.5) * CELL
    ys = y0 + (np.arange(int((A.shape[0] * cell) / CELL)) + 0.5) * CELL
    return xs, ys


def _resample_stock(stock, xs, ys):
    """Conservative max-resample of the stock map onto (xs, ys)."""
    A, x0, y0, cell = stock
    Af = np.where(np.isfinite(A), A, -np.inf)
    k = max(int(round(CELL / cell)), 1)
    ix = np.clip(((xs - x0) / cell).astype(int), 0, A.shape[1] - 1)
    iy = np.clip(((ys - y0) / cell).astype(int), 0, A.shape[0] - 1)
    Sg = np.full((len(ys), len(xs)), -np.inf)
    for dj in range(k):
        jj = np.clip(iy[:, None] + dj, 0, A.shape[0] - 1)
        ii = np.clip(ix[None, :] + dj, 0, A.shape[1] - 1)
        Sg = np.maximum(Sg, Af[jj, ii])
    return Sg


def part_cl(surf, dia, xs, ys, workers=1):
    """Exact ball tip-CL of the part on (xs, ys) (nan = no contact)."""
    X, Y = np.meshgrid(xs, ys)
    xy = np.column_stack([X.ravel(), Y.ravel()])
    z = batch_drop(surf, make_cutter("ball", dia), xy, threads=workers)
    return z.reshape(X.shape)


def cl_dilated(Z):
    """3x3 max filter: a point counts only where every neighbour allows
    the ball (conservative view used for zone detection)."""
    return ndimage.maximum_filter(np.where(np.isfinite(Z), Z, -1e30), size=3)


def _at(G, xs, ys, x, y):
    j = int(round((x - xs[0]) / CELL))
    i = int(round((y - ys[0]) / CELL))
    if 0 <= i < G.shape[0] and 0 <= j < G.shape[1]:
        return float(G[i, j])
    return -1e30


def find_zones(Sg, Zd, floor_z, min_excess, xs, ys):
    reach = np.maximum(Zd, floor_z)
    exc = np.where(np.isfinite(Sg) & (Sg > floor_z), Sg - reach, -1e3)
    mask = exc > min_excess
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    zones = []
    for k in range(1, n + 1):
        zz = lab == k
        area = float(zz.sum()) * CELL * CELL
        if area < 5.0:
            continue
        js, is_ = np.where(zz)
        zones.append({
            "bbox": (float(xs[is_].min()), float(xs[is_].max()),
                    float(ys[js].min()), float(ys[js].max())),
            "area_mm2": round(area, 1),
            "volume_mm3": round(float(exc[zz].sum()) * CELL * CELL, 0),
            "stockmax": float(Sg[zz].max()),
            "mask": zz,
        })
    zones.sort(key=lambda z: -z["area_mm2"])
    return zones


def helix_points(cx, cy, r, z_top, z_bot, ramp_deg):
    pitch = max(2.0 * math.pi * r * math.tan(math.radians(ramp_deg)), 1e-9)
    turns = max((z_top - z_bot) / pitch, 1.0 / 24.0)
    n = max(int(turns * 24), 2)
    return [(cx + r * math.cos(2.0 * math.pi * k / n),
             cy + r * math.sin(2.0 * math.pi * k / n),
             z_top - (z_top - z_bot) * k / n) for k in range(n + 1)]


def circle_points(cx, cy, r, z, theta0=0.0):
    n = max(int(2.0 * math.pi * r / 0.5), 16)
    return [(cx + r * math.cos(theta0 + 2.0 * math.pi * k / n),
             cy + r * math.sin(theta0 + 2.0 * math.pi * k / n), z)
            for k in range(n + 1)]





def validate_exact(surf, dia, moves, leave, workers=1):
    """(count, worst_mm) of feed path points below exact part CL + leave
    by more than 0.005 mm; no-contact points count as violations. Each
    move is sampled every 0.25 mm along its path, not just at endpoints."""
    pts, src = [], []
    prev = None
    for m in moves:
        if m["g"] != 1:
            prev = m
            continue
        if prev is not None and prev["g"] == 1:
            n = max(int(math.hypot(m["x"] - prev["x"], m["y"] - prev["y"])
                        / 0.25), 1)
            for q in range(1, n):
                pts.append((prev["x"] + (m["x"] - prev["x"]) * q / n,
                          prev["y"] + (m["y"] - prev["y"]) * q / n,
                          prev["z"] + (m["z"] - prev["z"]) * q / n))
        pts.append((m["x"], m["y"], m["z"]))
    if not pts:
        return 0, 0.0
    Z = batch_drop(surf, make_cutter("ball", dia),
                   [(p[0], p[1]) for p in pts], threads=workers)
    bad, worst = 0, 0.0
    for (x, y, z), v in zip(pts, Z):
        if not math.isfinite(v):
            bad += 1
            worst = max(worst, float("inf"))
            continue
        slack = z - (v + leave)
        if slack < -0.005:
            bad += 1
            worst = max(worst, -slack)
    return bad, worst


def rest_rough(surf, stock, tool, floor_z, stepdown, ae, rest_leave,
               min_excess, min_helix_r, ramp_angle_deg, cut_feed, ramp_feed,
               clearance=None, zb_floor=0.5, margin=0.02, workers=1,
               progress=None):
    """Plan the ball rest-rough. Returns (moves, stats); moves are dicts
    {'g': 0|1, 'x', 'y', 'z', 'f'} in tip-Z convention."""
    kind, dia = tool
    R = dia / 2.0
    xs, ys = _grid(stock)
    Sg = _resample_stock(stock, xs, ys)
    Zraw = part_cl(surf, dia, xs, ys, workers)
    Zd = cl_dilated(Zraw)
    live = fin.LiveStock(stock[0], stock[1], stock[2], stock[3], R,
                        fine=stock[3])
    if clearance is None:
        clearance = float(np.nanmax(Sg[np.isfinite(Sg)])) + 2.0
    zones = find_zones(Sg, Zd, floor_z, min_excess, xs, ys)

    moves = []
    stats = {"zones": [], "no_entry": [], "cut_len": 0.0, "ramp_len": 0.0,
             "rapid_len": 0.0, "n_levels": 0}

    def g0(x, y, z):
        prev = moves[-1] if moves else None
        if prev is not None:
            stats["rapid_len"] += math.hypot(x - prev["x"], y - prev["y"])
            if z > prev["z"] + 1e-9:
                # retract vertically first, then traverse at the clearance
                # plane: a combined X-Y-Z rapid is a diagonal through stock
                moves.append({"g": 0, "x": prev["x"], "y": prev["y"],
                            "z": round(z, 4)})
        moves.append({"g": 0, "x": round(x, 4), "y": round(y, 4),
                     "z": round(z, 4)})

    def g1(x, y, z, f):
        if moves:
            prev = moves[-1]
            L = math.hypot(x - prev["x"], y - prev["y"]) \
                + abs(z - prev["z"])
            stats["cut_len" if f >= cut_feed else "ramp_len"] += L
            live.stamp_chord((prev["x"], prev["y"], prev["z"]), (x, y, z))
        moves.append({"g": 1, "x": round(x, 4), "y": round(y, 4),
                     "z": round(z, 4), "f": f})

    for z in zones:
        # centres must sit on the zone itself: R-dilation admitted foreign
        # floor cells whose links crossed fins and polluted r_max anchoring
        zdil = ndimage.binary_dilation(z["mask"], structure=np.ones((3, 3)),
                                      iterations=2)
        js_, is_ = np.nonzero(zdil)
        b0, b1 = int(js_.min()), int(js_.max()) + 1
        c0, c1 = int(is_.min()), int(is_.max()) + 1
        levels = []
        t = floor_z + rest_leave
        while t <= z["stockmax"] - 0.01 + 1e-9:
            sub = ((Sg[b0:b1, c0:c1] >= t + 0.01)
                  & (Zraw[b0:b1, c0:c1] <= t - rest_leave + 0.005))
            if sub.any():
                reg = np.zeros_like(zdil)
                reg[b0:b1, c0:c1] = sub
                levels.append((round(t, 4), reg))
            t += stepdown
        if not levels:
            stats["no_entry"].append({
                "bbox": z["bbox"], "area_mm2": z["area_mm2"],
                "volume_mm3": z["volume_mm3"], "r_max_cl": 0.0,
                "reason": "no leave-legal floor region at the deepest level"})
            continue
        sk = 0
        while levels:
            t0, reg0 = levels[0]
            D0 = ndimage.distance_transform_edt(reg0) * CELL
            r_max = float(D0.max())
            if r_max >= min_helix_r:
                break
            levels.pop(0)  # narrow deep strip: T20 cannot enter it legally
            sk += 1
        if not levels:
            stats["no_entry"].append({
                "bbox": z["bbox"], "area_mm2": z["area_mm2"],
                "volume_mm3": z["volume_mm3"], "r_max_cl": round(r_max, 3),
                "reason": "no legal entry: largest inscribed CL circle "
                        "r_max=%.3f mm < min_helix_r=%.3f mm"
                        % (r_max, min_helix_r)})
            continue
        if sk:
            stats.setdefault("levels_unreachable", []).append(
                {"bbox": z["bbox"], "n_deep_levels_skipped": sk})

        # --- entry: helix at r_h = 0.8 * local inscribed radius from the
        #     live disk-top to the deepest level (2 deg, self-clearing; only
        #     the first segment is a scored entry, starts within zb_floor) ---
        hel = None
        r_h = 0.0
        cx = cy = 0.0
        pk = ((D0 >= ndimage.maximum_filter(D0, size=15))
              & (D0 >= min_helix_r / 0.8))
        pii, pjj = np.nonzero(pk)
        if len(pii):
            cand_order = np.argsort(-D0[pii, pjj])[:6]
            for oi in cand_order:
                i0c, j0c = pii[oi], pjj[oi]
                cx0, cy0 = float(xs[j0c]), float(ys[i0c])
                rr = 0.8 * float(D0[i0c, j0c])
                while rr >= min_helix_r:
                    z_top = min(clearance, live.disk_top(cx0, cy0) - 0.01)
                    if not math.isfinite(z_top) or z_top <= t0:
                        break
                    cand = helix_points(cx0, cy0, rr, z_top, t0,
                                       ramp_angle_deg)
                    if all(_at(Zraw, xs, ys, px, py) <= pz - rest_leave + 0.005
                           for px, py, pz in cand):
                        d0 = live.disk_depth(cand[1][0], cand[1][1],
                                            cand[1][2])
                        if math.isfinite(d0) and d0 <= zb_floor:
                            hel, r_h, cx, cy = cand, rr, cx0, cy0
                            break
                    rr *= 0.85
                if hel is not None:
                    break
        if hel is None:
            stats["no_entry"].append({
                "bbox": z["bbox"], "area_mm2": z["area_mm2"],
                "volume_mm3": z["volume_mm3"], "r_max_cl": round(r_max, 3),
                "reason": "no legal entry: helix at r_h would break leave "
                        "or the first descent exceeds zb_floor"})
            continue
        r_h = round(r_h, 3)
        g0(cx, cy, clearance)
        for px, py, pz in hel:
            g1(px, py, round(pz, 4), ramp_feed)
        prev = (hel[-1][0], hel[-1][1], round(t0, 4))

        # --- deepest first: floor circle at r_h on t0 (ramp feed), rings
        #     greedy-nearest; rise one stepdown in place between levels ---
        n_levels = 0
        for li, (t, reg) in enumerate(levels):
            if li:
                g1(prev[0], prev[1], t, ramp_feed)
            if t == t0:
                # one flat floor circle at the deepest level (ramp feed),
                # only where it keeps leave: shrink radius, else omit
                theta0 = math.atan2(prev[1] - cy, prev[0] - cx)
                rc = r_h
                while rc >= min_helix_r:
                    cp = circle_points(cx, cy, rc, t0, theta0)
                    if all(_at(Zraw, xs, ys, px, py) <= t0 - rest_leave + 0.005
                           for px, py, pz in cp):
                        for px, py, pz in cp:
                            g1(px, py, pz, ramp_feed)
                        prev = (px, py, pz)
                        break
                    rc *= 0.8
            Dt = ndimage.distance_transform_edt(reg) * CELL
            maxc = float(Dt.max())
            rings = []
            c = ae / 2.0
            while c <= maxc + 1e-9:
                for P, closed, _K in march_level(Dt, xs, ys, c, comp=reg):
                    pts = [(float(a), float(b)) for a, b in P]
                    if len(pts) < 3:
                        continue
                    if closed:
                        pts = pts + [pts[0]]
                    rings.append(pts)
                c += ae
            cut_here = 0
            skipped = 0
            while rings:
                k, d0 = min(
                    ((ki, math.hypot(r[0][0] - prev[0], r[0][1] - prev[1]))
                     for ki, r in enumerate(rings)), key=lambda t_: t_[1])
                pts = rings.pop(k)
                if cut_here % 2:
                    pts = pts[::-1]
                if math.hypot(pts[0][0] - prev[0], pts[0][1] - prev[1]) > 1e-6:
                    # feed link only where the straight path keeps leave above
                    # the exact part CL; else verified rapid + descent at the
                    # the landing point; else skip this pass.
                    n = max(int(d0 / 0.25), 1)
                    clear = all(
                        _at(Zraw, xs, ys,
                          prev[0] + (pts[0][0] - prev[0]) * q / n,
                          prev[1] + (pts[0][1] - prev[1]) * q / n)
                        <= t - rest_leave + 0.005 for q in range(n + 1))
                    if clear:
                        g1(pts[0][0], pts[0][1], t, ramp_feed)
                    else:
                        dd = live.disk_depth(pts[0][0], pts[0][1], t)
                        if not (math.isfinite(dd) and dd <= zb_floor):
                            skipped += 1
                            continue
                        g0(pts[0][0], pts[0][1], clearance)
                        g1(pts[0][0], pts[0][1], t, ramp_feed)
                for (px, py) in pts[1:]:
                    g1(px, py, t, cut_feed)
                prev = (pts[-1][0], pts[-1][1], t)
                cut_here += 1
            if cut_here:
                n_levels += 1
                stats["n_levels"] += 1
        stats["zones"].append({
            "bbox": z["bbox"], "area_mm2": z["area_mm2"],
            "volume_mm3": z["volume_mm3"], "r_max_cl": round(r_max, 3),
            "helix": r_h, "floor_tip_z": t0, "levels": n_levels,
            "entry": "helix %.1f deg + floor circle" % ramp_angle_deg})
        if progress:
            progress(stats)
    return moves, stats
