"""T20-style ball rest-rough for the material the big flat tool left.

Tasks RR1b + RR1c. Live stock more than `min_excess` mm above the part
cannot be removed by the finishing ball in one stepover; this generator
machines that rest with a ball:

  * zones: 8-connected components where
    live stock - max(exact part ball-CL, floor_z) > min_excess (>= 5 mm2);
  * levels: z = floor_z + rest_leave + k*stepdown that have leave-legal
    stock in the zone, PLUS a floor-hugging level t_f = min(part CL over
    the zone) + rest_leave so the deepest floor of every zone is cut to
    leave, not left as a stepdown terrace (RR1c: the bay leftover);
  * entry PER PASS, chosen by the pass's live depth (FE5 LiveStock), in
    this order (RR1c):
      1. live depth <= shallow (0.25): straight feed descent, no entry;
      2. in-pass ramp at ramp_angle: the SMALLEST L along the pass whose
         top clears with the FE5e top-clear rule (descent column at the
         ramp top verified live depth <= shallow);
      3. zig-zag along the zone's long axis at this level, only if every
         run >= tool diameter D (entry via 1/2 along the axis);
      4. SE2-verified side entry: descend at a column already cleared at
         this level (live depth <= shallow) and feed in horizontally
         through stock cleared at that level (the engine's SE2 rule);
      5. helix + floor circle at r >= min_helix_r (RR1b, zone entry);
      6. else REPORT the pass/zone (r_max, run length, depth) - no
         plunges, no smaller helix, never steeper than ramp_angle.
    Every entry records which step it took (stats["entry_steps"],
    stats["zones"][*]["entry_steps"]);
  * z-level contours at c = ae/2 stepping ae (or zig-zag runs), greedy-
    nearest pass order, rising in place between levels;
  * no axial plunges: every scored descent (pass start after a G0) is
    checked with the FE5 disk rule against LIVE stock (stamp_chord order,
    engine/entry_depth.py) and must stay <= shallow; links feed only along
    paths keeping leave above the exact part CL, else SE2/step-1 verified
    entry, else the pass is skipped and reported;
  * rapids (RR1c): a G0 may never pass through live stock. Leaving a
    pocket feeds out first to the ball-aware clear height at the column
    (disk_top), then retracts; every traverse is swept-sampled and raised
    to the highest disk_top along the path before moving;
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
# RR-A: top-clear limit for the step-2 ramp of a DESCENT re-entry (a lower
# level entered from the level just cleared). The live grid is now
# fine=min(stock cell, 0.1) (RR1c-5d (A)), at least as fine as the ZB
# judge's 0.1 grid, so this read is no longer an under-read: the bay groove
# ramp top measured 0.2571 mm on the 0.1 grid (0.2435 on the old 0.5 grid)
# against the scored ZB limit 0.5. 0.3 keeps a >= 0.2 mm margin to ZB; the
# shallow (0.25) gate stands for level entries, straight descents and SE2.
DEEP_TOP = 0.3


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


def find_zones(Sg, Zd, floor_z, min_excess, xs, ys, dropped=None,
               tool_d=0.0, link_ok=None):
    reach = np.maximum(Zd, floor_z)
    exc = np.where(np.isfinite(Sg) & (Sg > floor_z), Sg - reach, -1e3)
    mask = exc > min_excess
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    zones = []
    frags = []
    for k in range(1, n + 1):
        zz = lab == k
        area = float(zz.sum()) * CELL * CELL
        js, is_ = np.where(zz)
        rec = {
            "bbox": (float(xs[is_].min()), float(xs[is_].max()),
                     float(ys[js].min()), float(ys[js].max())),
            "area_mm2": round(area, 1),
            "volume_mm3": round(float(exc[zz].sum()) * CELL * CELL, 0),
            "stockmax": float(Sg[zz].max()),
            "mask": zz,
        }
        if area < 5.0:
            frags.append(rec)   # RR1c-4: plan fragments, never drop silently
            continue
        zones.append(rec)
    # RR1c-4b: merge a fragment within the tool DIAMETER D into the nearest
    # zone only when the bridge at its cutting Z is CL-legal and stock-clear
    # (link_ok); else it stays a mini-zone (entered, or reported as dropped).
    for f in sorted(frags, key=lambda z: -z["area_mm2"]):
        near = [(float(ndimage.distance_transform_edt(~z["mask"])[f["mask"]]
                       .min()) * CELL, z) for z in zones]
        d, z = min(near, key=lambda t_: t_[0]) if near else (1e30, None)
        if d <= tool_d + 1e-9 and z is not None and \
                (link_ok is None or link_ok(f, z)):
            m = z["mask"] | f["mask"]
            j2, i2 = np.nonzero(m)
            z.update({"mask": m, "stockmax": float(Sg[m].max()),
                     "area_mm2": round(float(m.sum()) * CELL * CELL, 1),
                     "volume_mm3": round(float(exc[m].sum()) * CELL * CELL, 0),
                     "bbox": (float(xs[i2].min()), float(xs[i2].max()),
                              float(ys[j2].min()), float(ys[j2].max()))})
        else:
            f["fragment"] = True   # lone mini-zone: entered or reported
            zones.append(f)
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


def zigzag_runs(reg, xs, ys, ae, min_run):
    """Straight runs along the region's long axis spaced ae apart; every
    run must be >= min_run long. Returns list of point lists (XY), each
    ordered along its own travel direction."""
    js, is_ = np.nonzero(reg)
    if len(js) < 2:
        return []
    x0v, x1v = float(xs[is_].min()), float(xs[is_].max())
    y0v, y1v = float(ys[js].min()), float(ys[js].max())
    horiz = (x1v - x0v) >= (y1v - y0v)
    runs = []
    lo, hi = (y0v, y1v) if horiz else (x0v, x1v)
    if hi - lo < ae - 1e-9:
        offs = [(lo + hi) / 2.0]      # strip narrower than ae: centre run
    else:
        offs = list(np.arange(lo + ae / 2.0, hi - ae / 2.0 + 1e-9, ae))
        if not offs or offs[-1] < hi - ae / 2.0 - 1e-9:
            offs.append(hi - ae / 2.0)
    for w in offs:
        if horiz:
            sel = np.abs(ys[js] - w) <= CELL / 2.0 + 1e-9
            cols = np.unique(is_[sel])
        else:
            sel = np.abs(xs[is_] - w) <= CELL / 2.0 + 1e-9
            cols = np.unique(js[sel])
        if len(cols) < 2:
            continue
        brk = np.nonzero(np.diff(cols) > 1)[0]
        groups = np.split(cols, brk + 1)
        for g in groups:
            if len(g) < 2:
                continue
            b = float(w)
            if horiz:
                a0, a1 = float(xs[g[0]]), float(xs[g[-1]])
                pts = [(a0, b), (a1, b)]
            else:
                # g indexes ROWS here: the run's extent is along ys, not xs
                a0, a1 = float(ys[g[0]]), float(ys[g[-1]])
                pts = [(b, a0), (b, a1)]
            if a1 - a0 >= min_run - 1e-9:
                runs.append(pts)
    return runs


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
               shallow=0.25, progress=None):
    """Plan the ball rest-rough. Returns (moves, stats); moves are dicts
    {'g': 0|1, 'x', 'y', 'z', 'f'} in tip-Z convention.

    shallow: RR1c step-1 live-depth limit (mm) - a pass start whose FE5
    disk depth against live stock is at or below this may be entered by a
    straight feed descent; the same limit sizes the FE5e top-clear rule of
    the in-pass ramp (step 2) and the SE2 descent column (step 4)."""
    kind, dia = tool
    R = dia / 2.0
    tanr = math.tan(math.radians(ramp_angle_deg))
    xs, ys = _grid(stock)
    Sg = _resample_stock(stock, xs, ys)
    Zraw = part_cl(surf, dia, xs, ys, workers)
    Zd = cl_dilated(Zraw)
    # the live grid is never coarser than the ZB estimator's (0.1): a coarse
    # input stock must not make the engine's own checks read under the gate
    live = fin.LiveStock(stock[0], stock[1], stock[2], stock[3], R,
                        fine=min(stock[3], fin.FINE))
    if clearance is None:
        clearance = float(np.nanmax(Sg[np.isfinite(Sg)])) + 2.0
    fragments = []

    def link_clear(fr, zn):
        """RR1c-4b fragment bridge at the cutting Z (fragment stockmax -
        leave): every bridge point CL+leave legal AND stock-clear - no live
        column deeper than zb_floor; fail closed on unjudged stock."""
        dt = ndimage.distance_transform_edt(~zn["mask"])
        fi, fj = np.unravel_index(int(np.argmin(
            np.where(fr["mask"], dt, 1e30))), dt.shape)
        dtf = ndimage.distance_transform_edt(~fr["mask"])
        zi_, zj_ = np.unravel_index(int(np.argmin(
            np.where(zn["mask"], dtf, 1e30))), dtf.shape)
        n8 = max(int(round(math.hypot(xs[zj_] - xs[fj],
                                       ys[zi_] - ys[fi]) / (CELL / 2))), 2)
        zc = fr["stockmax"] - rest_leave
        pts = [(xs[fj] + (xs[zj_] - xs[fj]) * q / n8,
                ys[fi] + (ys[zi_] - ys[fi]) * q / n8) for q in range(n8 + 1)]
        if any(live.disk_top(px, py) > zc + zb_floor for px, py in pts):
            return False
        v = batch_drop(surf, make_cutter("ball", dia), pts, threads=1)
        return all(math.isfinite(z_) and z_ <= zc - rest_leave + 0.005
                   for z_ in v)

    zones = find_zones(Sg, Zd, floor_z, min_excess, xs, ys, fragments,
                       tool_d=dia, link_ok=link_clear)

    moves = []
    stats = {"zones": [], "no_entry": [], "fragments_dropped": fragments,
             "cut_len": 0.0, "ramp_len": 0.0,
             "rapid_len": 0.0, "n_levels": 0, "entry_steps": {},
             "entries": [], "passes_skipped": [],
             "rr_ring_failed": [], "rr_axial_over": []}

    def g0r(x, y, z):
        prev = moves[-1] if moves else None
        if prev is not None:
            stats["rapid_len"] += math.hypot(x - prev["x"], y - prev["y"]) \
                + max(z - prev["z"], 0.0)
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

    def col_top(x, y):
        """Ball-aware lowest non-cutting tip Z at (x, y) vs LIVE stock;
        fail closed to the clearance plane when the column is unjudged."""
        h = live.disk_top(x, y)
        return clearance if not math.isfinite(h) else h

    def g0(x, y, z):
        """Rapid to (x, y, z) that can never collide with live stock
        (RR1c): feed out of the current column first when a vertical
        rapid would drag through standing material, traverse at a height
        swept-checked against disk_top along the whole path, then drop at
        the target column to its own ball-aware clear height."""
        prev = moves[-1] if moves else None
        if prev is None:
            g0r(x, y, z)
            return
        px, py, pz = prev["x"], prev["y"], prev["z"]
        h0 = col_top(px, py)
        if pz < h0 - 1e-9:
            g1(px, py, round(h0 + 0.01, 4), ramp_feed)
            pz = h0 + 0.01
        n = max(int(math.hypot(x - px, y - py) / CELL), 1)
        hp = -1e30
        for q in range(n + 1):
            t_ = q / n
            hp = max(hp, col_top(px + (x - px) * t_, py + (y - py) * t_))
        zh = max(z, h0 + 0.01)
        if math.isfinite(hp):
            zh = max(zh, hp + 0.01)
        if pz < zh - 1e-9:
            g0r(px, py, round(zh, 4))
            pz = zh
        # whole-G0 swept check (RR1b CF collisions): traverse horizontally at
        # the safe height FIRST, then drop at the target column - never one
        # diagonal G0, whose interior drags below standing stock tops.
        if abs(x - px) > 1e-9 or abs(y - py) > 1e-9:
            g0r(x, y, round(pz, 4))
        ht = col_top(x, y)
        # RR1c-5c: land 0.2 above the coarse live top, not 0.01 - at cell
        # 0.5 the planner's disk_top can under-read the true column top by
        # ~0.1 (a G0 drop then grazes live stock, rr1c2 CF bays).
        z_land = round(min(zh, ht + 0.2), 4)
        if z_land < pz - 1e-9:
            g0r(x, y, z_land)

    cutter_ball = make_cutter("ball", dia)

    def cl_ok(x, y, z):
        """Exact (continuous-triangle) part CL + rest leave at (x, y):
        v <= z - rest_leave + 0.005 (validate_exact). The stock grid alone
        misses walls between cell centres, so every ladder vertical descent
        column is checked against the exact CL too; fail closed."""
        v = batch_drop(surf, cutter_ball, [(x, y)], threads=1)[0]
        return math.isfinite(v) and v <= z - rest_leave + 0.005

    def cl_ok_path(pts):
        """Exact batched drop-cutter check for a whole EMITTED path (ramp
        interior, side-entry feed-in, helix, floor circle, feed link): every
        point keeps CL + rest_leave above exact CL (+0.005); fail closed on
        no contact. The 0.2 mm grid `legal` misses walls between cell
        centres, so emitted geometry never relies on it alone."""
        if not pts:
            return True
        v = batch_drop(surf, cutter_ball, [(p[0], p[1]) for p in pts],
                       threads=workers)
        return all(math.isfinite(zc) and zc <= p[2] - rest_leave + 0.005
                   for p, zc in zip(pts, v))

    def _record(zone_i, t, step, kind_s, depth):
        stats["entry_steps"][step] = stats["entry_steps"].get(step, 0) + 1
        stats["entries"].append({"zone": zone_i, "t": round(t, 3),
                                "step": step, "kind": kind_s,
                                "depth_mm": (round(depth, 3) if depth is not None
                                           and math.isfinite(depth) else None)})

    def step1(x, y, t, zi):
        """Straight feed descent: live depth <= shallow."""
        d = live.disk_depth(x, y, t)
        if not (math.isfinite(d) and d <= shallow):
            return False
        if not cl_ok(x, y, t):
            return False
        g0(x, y, clearance)
        g1(x, y, round(t, 4), ramp_feed)
        _record(zi, t, 1, "direct-descent", d)
        return True

    def step2(x, y, t, ux, uy, zi, deep=False):
        """In-pass ramp at ramp_angle: smallest L along +-u whose top
        satisfies the FE5e top-clear rule (descent column at the ramp top
        verified live depth <= shallow); the ramp is IN-PASS: its top and
        path stay inside the level region and leave-legal. deep: descent
        re-entry, top-clear limit DEEP_TOP (see constant)."""
        for sgn in (1.0, -1.0):
            if step2_dir(x, y, t, sgn * ux, sgn * uy, zi, deep):
                return True
        return False

    def step2_dir(x, y, t, ux, uy, zi, deep=False):
        top_lim = DEEP_TOP if deep else shallow
        L = CELL
        while L <= 80.0:
            ax, ay = x - ux * L, y - uy * L
            az = t + L * tanr
            if az >= clearance:
                return False
            i0 = int(round((ay - ys[0]) / CELL))
            j0 = int(round((ax - xs[0]) / CELL))
            inpass = (0 <= i0 < reg_cur.shape[0]
                     and 0 <= j0 < reg_cur.shape[1] and bool(reg_cur[i0, j0]))
            if inpass and cl_ok(ax, ay, az):
                d = live.disk_depth(ax, ay, az)
                if math.isfinite(d) and d <= top_lim:
                    n = max(int(L / CELL), 1)
                    rp = [(x - ux * L * (1.0 - q / n),
                         y - uy * L * (1.0 - q / n),
                         t + L * tanr * (1.0 - q / n))
                        for q in range(n + 1)]
                    if cl_ok_path(rp):
                        g0(ax, ay, clearance)
                        g1(ax, ay, round(az, 4), ramp_feed)
                        for q in range(1, n + 1):
                            g1(rp[q][0], rp[q][1], round(rp[q][2], 4),
                               ramp_feed)
                        _record(zi, t, 2, "in-pass-ramp %.1f deg L=%.1f"
                               % (ramp_angle_deg, L), d)
                        return True
            L += CELL
        return False

    def step4(x, y, t, zi):
        """SE2 side entry: descend at a nearby column already cleared at
        this level (live depth <= shallow) and feed in horizontally. Every
        descent column AND every feed-in point is checked against the EXACT
        part CL - 'stock cleared at this level' is NOT 'part-legal', so no
        point is ever skipped because its live stock is gone."""
        for dist in (2.0, 3.5, 5.0, 7.0, 9.0, 11.0, 13.0):
            for q in range(16):
                a = q * math.pi / 8.0
                sx, sy = x + dist * math.cos(a), y + dist * math.sin(a)
                d = live.disk_depth(sx, sy, t)
                if not (math.isfinite(d) and d <= shallow):
                    continue
                if not cl_ok(sx, sy, t):
                    continue
                n = max(int(dist / 0.2), 1)
                fp = [(sx + (x - sx) * w / n, sy + (y - sy) * w / n, t)
                     for w in range(n + 1)]
                if not cl_ok_path(fp):
                    continue
                g0(sx, sy, clearance)
                g1(sx, sy, round(t, 4), ramp_feed)
                m = max(int(dist / CELL), 1)
                for w in range(1, m + 1):
                    t_ = w / m
                    g1(sx + (x - sx) * t_, sy + (y - sy) * t_, round(t, 4),
                       ramp_feed)
                _record(zi, t, 4, "SE2 side-entry d=%.1f" % dist, d)
                return True
        return False

    def helix_entry(x, y, t, zi):
        """RR1b helix: bore at r_h = 0.8 * local inscribed radius from the
        live disk-top down to level t, then caller cuts the floor circle."""
        cand = [(x, y)]
        pk = ((Dz >= ndimage.maximum_filter(Dz, size=15))
              & (Dz >= min_helix_r / 0.8))
        pii, pjj = np.nonzero(pk & reg_cur)
        if len(pii):
            cand = [(float(xs[j0c]), float(ys[i0c]))
                    for i0c, j0c in zip(pii[np.argsort(-Dz[pii, pjj])[:6]],
                                       pjj[np.argsort(-Dz[pii, pjj])[:6]])]
        for cx0, cy0 in cand:
            rr = 0.8 * float(Dz[int(round((cy0 - ys[0]) / CELL)),
                               int(round((cx0 - xs[0]) / CELL))])
            rr = max(rr, min_helix_r)
            while rr >= min_helix_r:
                z_top = min(clearance, live.disk_top(cx0, cy0) - 0.01)
                if not math.isfinite(z_top) or z_top <= t:
                    break
                hp = helix_points(cx0, cy0, rr, z_top, t, ramp_angle_deg)
                if cl_ok_path(hp):
                    d0 = live.disk_depth(hp[1][0], hp[1][1], hp[1][2])
                    if math.isfinite(d0) and d0 <= zb_floor:
                        g0(cx0, cy0, clearance)
                        for px, py, pz in hp:
                            g1(px, py, round(pz, 4), ramp_feed)
                        _record(zi, t, 5, "helix %.1f deg r=%.3f"
                               % (ramp_angle_deg, rr), d0)
                        return (round(cx0, 4), round(cy0, 4), rr)
                rr *= 0.85
        return None

    Dz = None            # distance transform of the current level region
    reg_cur = None

    def enter(x, y, t, ux, uy, zi, deep=False):
        """ONE ladder entry (steps 1, 2, 4) used by both the zone entry and
        the per-pass links (RR1c_DIAG 3): shallow descent, in-pass ramp along
        (ux, uy) when a direction exists, SE2 side entry. deep: a descent
        re-entry from the level just cleared (step-2 top-clear DEEP_TOP)."""
        if step1(x, y, t, zi):
            return True
        if abs(ux) + abs(uy) > 0.5 and step2(x, y, t, ux, uy, zi, deep):
            return True
        return step4(x, y, t, zi)

    for zi, z in enumerate(zones):
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
                  & (Zraw[b0:b1, c0:c1] <= t - rest_leave + 0.005)
                  & z["mask"][b0:b1, c0:c1])
            if sub.any():
                reg = np.zeros_like(zdil)
                reg[b0:b1, c0:c1] = sub
                levels.append((round(t, 4), reg))
            t += stepdown
        # RR1c: floor-hugging level so the deepest part CL of the zone is
        # cut to leave instead of left as a stepdown terrace (the bay
        # leftover: 2.0-grid levels stopped ~0.6 mm above the bay floor).
        zmin = float(np.nanmin(Zraw[z["mask"]])) if np.isfinite(
            Zraw[z["mask"]]).any() else -1e30
        if math.isfinite(zmin) and zmin > -1e29:
            tf = round(zmin + rest_leave, 4)
            if tf >= floor_z + rest_leave and (
                    not levels or tf < levels[0][0] - 0.005):
                sub = ((Sg[b0:b1, c0:c1] >= tf + 0.01)
                     & (Zraw[b0:b1, c0:c1] <= tf - rest_leave + 0.005)
                     & z["mask"][b0:b1, c0:c1])
                if sub.any():
                    reg = np.zeros_like(zdil)
                    reg[b0:b1, c0:c1] = sub
                    levels.insert(0, (tf, reg))
        if not levels:
            stats["no_entry"].append({
                "bbox": z["bbox"], "area_mm2": z["area_mm2"],
                "volume_mm3": z["volume_mm3"], "r_max_cl": 0.0,
                "reason": "no leave-legal floor region at the deepest level"})
            if z.get("fragment"):
                fragments.append({"bbox": z["bbox"], "area_mm2": z["area_mm2"],
                                  "reason": "no leave-legal level, no entry"})
            continue

        # --- RR1c-4 ladder: enter at the HIGHEST level with a legal entry
        #     (same ladder/rules), then cut top-down; refused levels are
        entered = False
        mode = "rings"
        runs0 = None
        li0 = len(levels) - 1
        cx = cy = 0.0
        r_h = 0.0
        t0 = reg0 = None
        while li0 >= 0:
            t0, reg0 = levels[li0]
            Dz = ndimage.distance_transform_edt(reg0) * CELL
            reg_cur = reg0
            p0 = None
            cin = ae / 2.0 + max(Dz.max() - ae / 2.0, 0.0) // ae * ae
            for P, closed, _K in march_level(Dz, xs, ys, cin,
                                             comp=reg0):
                pts = [(float(a), float(b)) for a, b in P]
                if len(pts) >= 3:
                    p0 = pts + [pts[0]] if closed else pts
                    break
            if p0 is None:
                js0, is0 = np.nonzero(reg0)
                k0 = int(np.argmax(Dz[js0, is0]))
                p0 = [(float(xs[is0[k0]]), float(ys[js0[k0]]))]
            ux = uy = 0.0
            if len(p0) >= 2:
                dl = math.hypot(p0[1][0] - p0[0][0], p0[1][1] - p0[0][1])
                if dl > 1e-9:
                    ux, uy = ((p0[1][0] - p0[0][0]) / dl,
                             (p0[1][1] - p0[0][1]) / dl)
            if abs(ux) + abs(uy) == 0.0:
                # argmax-fallback p0 carries no direction: use the region's
                # own long axis for the step-2 ramp (RR1c_DIAG 1)
                jsr, isr = np.nonzero(reg0)
                if len(jsr) >= 2:
                    ux, uy = ((1.0, 0.0) if xs[isr].max() - xs[isr].min()
                             >= ys[jsr].max() - ys[jsr].min() else (0.0, 1.0))
            if len(levels) > 1 and li0 == len(levels) - 1:
                # RR1c-4b: a multi-level zone's entry is the BORE - the same
                # 2-deg helix + floor circle, top down to the LOWEST legal
                # level; time does not grow. No site: fall through reported.
                hc = helix_entry(p0[0][0], p0[0][1], levels[0][0], zi)
                if hc is not None:
                    entered = True
                    cx, cy, r_h = hc
                    mode = "bore"
            if not entered and enter(p0[0][0], p0[0][1], t0, ux, uy, zi):
                entered = True
            if not entered:
                # step 3: zig-zag along the zone's long axis (only if every
                # run >= D); enter the first run via steps 1/2 along the axis
                zig0 = zigzag_runs(reg0, xs, ys, ae, dia)
                if zig0:
                    horiz = abs(zig0[0][1][0] - zig0[0][0][0]) >= abs(
                        zig0[0][1][1] - zig0[0][0][1])
                    axu = (1.0, 0.0) if horiz else (0.0, 1.0)
                    runs0 = []
                    for i, r in enumerate(zig0):
                        forward = ((r[1][0] > r[0][0]) if horiz
                                 else (r[1][1] > r[0][1]))
                        runs0.append(r if (i % 2 == 0) == forward else r[::-1])
                    k0 = min(range(len(runs0)), key=lambda ki: math.hypot(
                        runs0[ki][0][0] - p0[0][0],
                        runs0[ki][0][1] - p0[0][1]))
                    rfirst = runs0[k0]
                    if enter(rfirst[0][0], rfirst[0][1], t0, axu[0], axu[1],
                            zi):
                        entered = True
                        mode = "zigzag"
            if not entered:
                hc = helix_entry(p0[0][0], p0[0][1], t0, zi)
                if hc is not None:
                    entered = True
                    cx, cy, r_h = hc
            if entered:
                break
            stats.setdefault("levels_unreachable", []).append({
                "zone": zi, "t": round(t0, 3),
                "r_max_cl": round(float(Dz.max()), 3),
                "live_depth_mm": (lambda dd: round(dd, 3) if math.isfinite(dd)
                                else None)(live.disk_depth(p0[0][0], p0[0][1],
                                                        t0))})
            li0 -= 1
        r_max = float(Dz.max())
        if not entered:
            stats["no_entry"].append({
                "bbox": z["bbox"], "area_mm2": z["area_mm2"],
                "volume_mm3": z["volume_mm3"], "r_max_cl": round(r_max, 3),
                "reason": "no legal entry: steps 1-5 all refused (r_max_cl="
                        "%.3f < min_helix_r=%.3f, no shallow column, ramp/"
                        "zigzag/SE2 blocked)" % (r_max, min_helix_r)})
            if z.get("fragment"):
                fragments.append({"bbox": z["bbox"], "area_mm2": z["area_mm2"],
                                  "reason": "lone mini-zone, no legal entry "
                                          "(r_max_cl=%.3f)" % r_max})
            continue

        tb = levels[0][0] if mode == "bore" else t0
        prev = (moves[-1]["x"], moves[-1]["y"], round(tb, 4))
        # floor circle at r_h on tb (step 5 companion), only where legal
        if r_h > 0.0:
            theta0 = math.atan2(prev[1] - cy, prev[0] - cx)
            rc = r_h
            while rc >= min_helix_r:
                cp = circle_points(cx, cy, rc, tb, theta0)
                if cl_ok_path(cp):
                    for px, py, pz in cp:
                        g1(px, py, pz, ramp_feed)
                    prev = (px, py, pz)
                    break
                rc *= 0.8

        n_levels = 0
        # RR1c-4: cut the zone's levels TOP-DOWN from the entered level; no
        # level cuts while higher-level stock stands above it; each lower
        # level is re-entered from the level just cleared (as RR1c-3).
        order = list(range(li0, -1, -1))
        for li, idx in enumerate(order):
            t, reg = levels[idx]
            if t - prev[2] > 1e-9:
                # bore mode: rise INSIDE the cleared bore to this level
                g1(prev[0], prev[1], round(t, 4), ramp_feed)
                prev = (prev[0], prev[1], round(t, 4))
            if mode == "bore" and t < prev[2] - 1e-9:
                # RR1c-4b: descend into each lower level INSIDE the bore -
                # strict CL at every point + live ZB floor on LIVE stock.
                bx, by = cx + r_h, cy
                n8 = max(int(math.hypot(bx - prev[0], by - prev[1]) / .25), 1)
                lp = [(prev[0] + (bx - prev[0]) * q / n8,
                      prev[1] + (by - prev[1]) * q / n8, prev[2])
                     for q in range(n8 + 1)]
                okd, dd = cl_ok_path(lp), 0.0
                if okd:
                    g1(bx, by, round(prev[2], 4), ramp_feed)
                    prev = (bx, by, round(prev[2], 4))
                while okd and prev[2] - t > 1e-9:
                    zn = max(t, round(prev[2] - (zb_floor - 0.05), 4))
                    dd = live.disk_depth(bx, by, zn)
                    okd = bool(cl_ok(bx, by, zn) and math.isfinite(dd)
                              and dd <= zb_floor)
                    if okd:
                        g1(bx, by, zn, ramp_feed)
                        prev = (bx, by, zn)
                if okd:
                    _record(zi, t, 5, "bore-descent", max(dd, 0.0))
            # a descent level is never a vertical drop at prev XY: the pass
            # loop re-enters it through the one enter() ladder below
            Dz = ndimage.distance_transform_edt(reg) * CELL
            reg_cur = reg
            maxc = float(Dz.max())
            # RR1c-5b: passes are FRONTS grown from the CLEARED side. C =
            # columns whose LIVE stock is clear at this Z (open boundary) plus
            # the seed bore; pass k = offset(C, ae/2 + k*ae) clipped to the
            # legal CL region, ascending c: each front's cleared side is C or
            # the previous front; the wall-hug comes LAST. No open edge and no
            # bore: inside-out fallback (engagement check reports raw slots).
            seed = Sg < t + 0.05
            if mode == "bore" and r_h > 0.0:
                seed = seed | (np.hypot(xs[None, :] - cx,
                                         ys[:, None] - cy) <= r_h + CELL)
            fronts = bool((seed & ~reg).any())
            F = ndimage.distance_transform_edt(~seed) * CELL if fronts else Dz
            rings = []
            clneed = []
            f1 = []
            c = ae / 2.0
            hch = ae / 2.0
            maxf = float(F[reg].max()) if reg.any() else 0.0
            if fronts:
                # RR1c-5d front 1 offset from cleared ground by the ball
                # chord at that edge: a1 = max live height above Z along the
                # cleared edge (planning LiveStock, no new grid), c0 = ae -
                # c(a1)/2 SIGNED (negative: CL INSIDE cleared ground), cf =
                # clip to the leave-legal CL grid; fronts at c0 + k*ae.
                e = reg & ~seed & ndimage.binary_dilation(seed)
                D = ndimage.distance_transform_edt(~e) * CELL
                m = (D <= R + 1e-9) & np.isfinite(Sg)
                a1 = float(np.max(Sg[m] - (R - np.sqrt(np.maximum(
                    R * R - D[m] * D[m], 0.0))))) - t if m.any() else 0.0
                hch = math.sqrt(max(a1 * (dia - a1), 0.0)) if a1 > 0.0 \
                    else ae / 2.0
                Sv = F - ndimage.distance_transform_edt(seed) * CELL
                cf = (reg | (seed & ndimage.binary_dilation(
                    reg, iterations=int(max(hch - ae / 2.0, 0.0) / CELL) + 2))
                    ) & np.isfinite(Zraw) & (Zraw <= t - rest_leave + 0.005)
                c = ae - hch
                maxf = float(Sv[cf].max()) if cf.any() else 0.0
            while c <= maxf + 1e-9:
                for P, closed, _K in march_level(Sv if fronts else F, xs,
                                                 ys, c, comp=cf if fronts else reg):
                    pts = [(float(a), float(b)) for a, b in P]
                    if len(pts) < 3:
                        continue
                    if closed:
                        pts = pts + [pts[0]]
                    rings.append(pts)
                    clneed.append(False)
                    f1.append(fronts and abs(c - (ae - hch)) < 1e-9)
                c += ae
            if not fronts:
                rings.reverse()  # RR1c-4 fallback: largest c first
            ring_seq = False
            if li == 0 and mode == "zigzag":
                paths = runs0 + rings          # zigzag first, then rings
                clneed = [False] * len(paths)
                f1 = [False] * len(runs0) + f1   # runs are never front 1
            else:
                paths = rings
                ring_seq = True    # keep the inside-out order (no greedy)
            if not paths:
                if maxc < ae / 2.0:
                    # RR1c-3b: thin level strip (max distance < ae/2). The
                    # iso at c = max(maxDz/2, CELL/2) over comp=reg has no
                    # valid marching-squares cell: every node inside the strip
                    # sits on the quantised Dz plateau (>= c) and every
                    # mixed-case cell straddles the boundary (corners outside
                    # comp), so RR1c-3 traced nothing and cut 0 mm (DIAG (a)).
                    # Trace that iso over a 1-cell DILATED comp instead: the
                    # ordered loop bounding the strip. Keep it only when every
                    # point stays leave-legal against the exact CL (on a
                    # concave floor the edges rise above CL + leave), else
                    # fall back to the axis zig-zag, whose centre run still
                    # hits a straight thin strip on its own centre line.
                    c_mid = max(maxc / 2.0, CELL / 2.0)
                    dil = ndimage.binary_dilation(reg, structure=np.ones((3, 3)))
                    for P, closed, _K in march_level(Dz, xs, ys, c_mid,
                                                    comp=dil):
                        pts = [(float(a), float(b)) for a, b in P]
                        if len(pts) < 2:
                            continue
                        if closed:
                            pts = pts + [pts[0]]
                        paths.append(pts)
                    if paths:
                        vp = batch_drop(surf, cutter_ball,
                                       [(a, b) for pth in paths for a, b in pth],
                                       threads=workers)
                        if not all(math.isfinite(zc) and zc <= t - rest_leave
                                 + 0.005 for zc in vp):
                            paths = []   # strip edges above CL + rest leave
                    if not paths:
                        paths = zigzag_runs(reg, xs, ys, ae, 2 * CELL)
                    clneed = [True] * len(paths)   # every point CL-checked
                else:
                    paths = zigzag_runs(reg, xs, ys, ae, 2 * CELL)
                    clneed = [False] * len(paths)
                f1 = [False] * len(paths)   # strip/zigzag paths are not fronts
            cut_here = 0
            skipped = 0
            # RR1c-5b engagement model: cleared at this Z (seed) + fronts
            clm = seed.copy()
            clmn = seed.copy()   # RR1c5d: near-groove mask for depth links
            dilk = int(round(ae / 2.0 / CELL)) + 1
            if len(f1) != len(paths):   # thin-strip / zigzag fallback paths
                stats.setdefault("rr_f1_mismatch", []).append(
                    {"zone": zi, "t": round(t, 3), "n_f1": len(f1),
                     "n_paths": len(paths)})
                f1 = [False] * len(paths)
            while paths:
                if ring_seq:
                    k = 0   # RR1c-4: rings stay inside-out, not greedy
                else:
                    k = min(range(len(paths)), key=lambda ki: math.hypot(
                        paths[ki][0][0] - prev[0], paths[ki][0][1] - prev[1]))
                pts = paths.pop(k)
                need_cl = clneed.pop(k)
                isf1 = f1.pop(k)
                d0 = math.hypot(pts[0][0] - prev[0], pts[0][1] - prev[1])
                if cut_here % 2:
                    pts = pts[::-1]
                if (math.hypot(pts[0][0] - prev[0], pts[0][1] - prev[1])
                        > 1e-6 or prev[2] - t > 1e-9):
                    # feed link only where the straight path keeps leave above
                    # the EXACT part CL (batched drop-cutter, same check as the
                    # passes); a descent link only at <= ramp_angle (in-pass,
                    # live depth ~ one stepdown); else the ONE RR1c ladder
                    # enter(), else skip.
                    n = max(int(d0 / 0.25), 1)
                    lp = [(prev[0] + (pts[0][0] - prev[0]) * q / n,
                         prev[1] + (pts[0][1] - prev[1]) * q / n, t)
                        for q in range(n + 1)]
                    dzd = prev[2] - t
                    # RR1c-5b: a feed link at depth must ALSO be stock-clear
                    # at the cutting Z (live disk, 0.05 tolerance) - a link
                    # may never cut; else the ladder below. RR1c-5c: a bore-
                    # seeded zone enters its level through the bore instead
                    # (RR1c-4b): from the bore circle at level Z after the in-
                    # bore rise/descent, a CL-checked feed-in replaces the
                    # ladder - the coarse live model hides the bore's uncut
                    # core, so step1 would plunge ~1.5 mm deep there.
                    onbore = (mode == "bore" and r_h > 0.0 and dzd <= 1e-9
                              and abs(math.hypot(prev[0] - cx, prev[1] - cy)
                                     - r_h) <= CELL)
                    lok = cl_ok_path(lp) and (onbore or all(
                        live.disk_top(px, py) <= t + 0.05
                        for px, py, _ in lp)) and (dzd <= 1e-9
                                                   or d0 * tanr >= dzd - 1e-9)
                    gok = all(clmn[int(round((py - ys[0]) / CELL)),
                                   int(round((px - xs[0]) / CELL))]
                              for px, py, _ in lp)
                    if lok and not gok:   # RR1c-5d guard sent it to the ladder
                        stats["rr_clmn_ladder"] = stats.get("rr_clmn_ladder", 0) + 1
                    if lok and gok:
                        g1(pts[0][0], pts[0][1], round(t, 4), ramp_feed)
                    else:
                        ldx = ldy = 0.0
                        if len(pts) >= 2:
                            dl = math.hypot(pts[1][0] - pts[0][0],
                                           pts[1][1] - pts[0][1])
                            if dl > 1e-9:
                                ldx, ldy = ((pts[1][0] - pts[0][0]) / dl,
                                          (pts[1][1] - pts[0][1]) / dl)
                        if dzd > 1e-9 and d0 > 1e-6:
                            # descent: the step-2 ramp must come down along
                            # the direction of travel FROM the level just
                            # cleared (its top sits in material that is
                            # already cut), not the contour tangent
                            ldx, ldy = ((pts[0][0] - prev[0]) / d0,
                                       (pts[0][1] - prev[1]) / d0)
                        ok = enter(pts[0][0], pts[0][1], t, ldx, ldy, zi,
                                   dzd > 1e-9)
                        if not ok and dzd > 1e-9:
                            # descent into a narrow strip: at the contour's
                            # start (its cap) the tangent runs ACROSS the
                            # strip - retry the ladder along the strip's own
                            # long axis, where a step-2 ramp fits inside it
                            jsr2, isr2 = np.nonzero(reg)
                            if len(jsr2) >= 2:
                                ax2 = ((1.0, 0.0) if xs[isr2].max() -
                                     xs[isr2].min() >= ys[jsr2].max() -
                                     ys[jsr2].min() else (0.0, 1.0))
                                ok = enter(pts[0][0], pts[0][1], t, ax2[0],
                                         ax2[1], zi, True)
                        if not ok:
                            skipped += 1
                            stats["passes_skipped"].append({
                                "zone": zi, "t": round(t, 3),
                                "xy": [round(pts[0][0], 2),
                                     round(pts[0][1], 2)],
                                "run_mm": round(sum(
                                    math.hypot(pts[i + 1][0] - pts[i][0],
                                             pts[i + 1][1] - pts[i][1])
                                    for i in range(len(pts) - 1)), 1),
                                "live_depth_mm": (lambda dd: round(dd, 3) if
                                               math.isfinite(dd) else None)(
                                    live.disk_depth(pts[0][0], pts[0][1], t))})
                            continue
                if need_cl and not cl_ok_path(
                        [(px, py, round(t, 4)) for px, py in pts]):
                    # every point of a centre-line pass goes through the same
                    # exact CL check as the passes; fail closed, skip it
                    skipped += 1
                    stats["passes_skipped"].append({
                        "zone": zi, "t": round(t, 3),
                        "xy": [round(pts[0][0], 2), round(pts[0][1], 2)],
                        "run_mm": round(sum(
                            math.hypot(pts[i + 1][0] - pts[i][0],
                                     pts[i + 1][1] - pts[i][1])
                            for i in range(len(pts) - 1)), 1),
                        "live_depth_mm": None,
                        "reason": "centre-line not CL-legal"})
                    continue
                jj = np.clip(np.rint((np.asarray([p[0] for p in pts])
                                       - xs[0]) / CELL).astype(int), 0,
                                       len(xs) - 1)
                ii = np.clip(np.rint((np.asarray([p[1] for p in pts])
                                       - ys[0]) / CELL).astype(int), 0,
                                       len(ys) - 1)
                pm = np.zeros_like(reg)
                pm[ii, jj] = True
                # engagement check (RR1c-5b): fronts stay within ae of
                # cleared ground; raw slots NEVER silent (rr_ring_failed).
                if ring_seq and fronts:
                    # RR1c-5d front 1: SIGNED dv, flag when dv+c(a1)/2>ae+CELL
                    # Sv is already in mm; the EDT is in cells
                    dv = Sv[ii, jj] if isf1 else ndimage.distance_transform_edt(
                        ~clm)[ii, jj] * CELL
                    kx = int(np.argmax(dv))
                    if float(dv[kx]) > ((ae - hch) if isf1 else ae) + CELL:
                        ad = live.disk_depth(pts[kx][0], pts[kx][1], t)
                        ad = ad if math.isfinite(ad) else 0.0
                        rc = math.sqrt(max(2.0 * R * ad - ad * ad, 0.0))
                        stats["rr_ring_failed"].append(
                            {"zone": zi, "t": round(t, 3), "place":
                             [round(pts[kx][0], 2), round(pts[kx][1], 2)],
                             "w_plan": round(float(dv[kx]) + rc, 3),
                             "ae_eq": round(2.0 * rc, 3)})
                clm |= ndimage.binary_dilation(pm, iterations=dilk)
                clmn |= ndimage.binary_dilation(pm, iterations=2)
                ad0 = live.disk_depth(pts[0][0], pts[0][1], t)
                if math.isfinite(ad0) and ad0 > stepdown + 1e-9:
                    stats["rr_axial_over"].append(
                        {"zone": zi, "t": round(t, 3), "place":
                         [round(pts[0][0], 2), round(pts[0][1], 2)],
                         "a": round(ad0, 3), "ap": stepdown})
                for (px, py) in pts[1:]:
                    g1(px, py, round(t, 4), cut_feed)
                prev = (pts[-1][0], pts[-1][1], round(t, 4))
                cut_here += 1
            if cut_here:
                n_levels += 1
                stats["n_levels"] += 1
        zone_steps = [e["step"] for e in stats["entries"] if e["zone"] == zi]
        stats["zones"].append({
            "bbox": z["bbox"], "area_mm2": z["area_mm2"],
            "volume_mm3": z["volume_mm3"], "r_max_cl": round(r_max, 3),
            "helix": r_h, "floor_tip_z": t0, "levels": n_levels,
            "entry_steps": zone_steps,
            "entry": "ladder steps %s" % (sorted(set(zone_steps)) or "-")})
        if progress:
            progress(stats)
    return moves, stats
