"""Arc fitting for the LNC post (opt-in ``arcs=True`` / ``post --arcs``).

Rules (docs/lnc5800_post_spec.md A1-A8): runs of >= 4 consecutive G01 moves
at one Z and one feed become G17 arcs when every original point and chord is
within ARC_TOL of the arc, the radius is in [R_MIN, R_MAX] and the sweep is
<= 180 deg in one direction. No helical arcs, no full circles, no R form.
Pure geometry, no numpy; units are whatever the caller passes (the post works
in input units and converts the mm limits).
"""
import math

ARC_TOL = 0.002            # mm: max distance original path <-> arc
ARC_END_MISMATCH = 0.0005  # mm: |r_start - r_end| after rounding (A6; manual gives no 50048 default)
R_MIN, R_MAX = 0.1, 500.0  # mm
MIN_MOVES = 4
_ANG_EPS = 1e-9


def circle3(a, b, c):
    """Circle through three XY points -> (cx, cy, r), None if collinear."""
    ax, ay = a
    bx, by = b
    qx, qy = c
    d = 2.0 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, qx * qx + qy * qy
    cx = (a2 * (by - qy) + b2 * (qy - ay) + c2 * (ay - by)) / d
    cy = (a2 * (qx - bx) + b2 * (ax - qx) + c2 * (bx - ax)) / d
    return cx, cy, math.hypot(ax - cx, ay - cy)


def arc_check(pts, cx, cy, r):
    """Points ``pts`` (XY, in path order) against the arc about (cx, cy) of
    radius r. Returns (ccw, sweep_rad, dev) or None when the points do not run
    one way round with a sweep <= pi. ``dev`` bounds the distance between the
    polyline and the arc: vertex residual, and per chord the larger end
    residual plus the chord sagitta (conservative)."""
    angs = [math.atan2(y - cy, x - cx) for x, y in pts]
    total, sign = 0.0, 0
    for a0, a1 in zip(angs, angs[1:]):
        d = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi
        s = 1 if d > 0 else (-1 if d < 0 else 0)
        if s == 0 or (sign and s != sign):
            return None
        sign = s
        total += d
    sweep = abs(total)
    if sweep > math.pi + _ANG_EPS:
        return None
    res = [abs(math.hypot(x - cx, y - cy) - r) for x, y in pts]
    dev = max(res)
    for k in range(len(pts) - 1):
        c = math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
        sag = r - math.sqrt(max(r * r - c * c / 4.0, 0.0))
        dev = max(dev, max(res[k], res[k + 1]) + sag)
    return sign > 0, sweep, dev


def fit_polyline(pts, tol=ARC_TOL, rmin=R_MIN, rmax=R_MAX, min_moves=MIN_MOVES):
    """Greedy fit over XY points. Returns arcs as tuples
    (i0, i1, cx, cy, r, ccw, dev) covering pts[i0..i1] (>= min_moves segments).
    ponytail: circle through first/middle/last point, greedy extend until the
    first failure, O(L^2) per arc; a least-squares fit would catch a few more."""
    out, n, s = [], len(pts), 0
    while s + min_moves < n:
        best, e = None, s + min_moves
        while e < n:
            c = circle3(pts[s], pts[(s + e) // 2], pts[e])
            if c is None or not rmin <= c[2] <= rmax:
                break
            chk = arc_check(pts[s:e + 1], *c)
            if chk is None or chk[2] > tol:
                break
            best = (s, e) + c + (chk[0], chk[2])
            e += 1
        if best:
            out.append(best)
            s = best[1]
        else:
            s += 1
    return out


def fit_moves(moves, tol=ARC_TOL, rmin=R_MIN, rmax=R_MAX):
    """Replace fittable G01 runs in a neutral move list with arc moves
    ``{"g": 2|3, "x", "y", "z", "f", "cx", "cy", "src": [original moves]}``
    (centre absolute, same units as the moves). Everything else is passed
    through unchanged (same dict objects)."""
    out, i, n = [], 0, len(moves)
    prev = None
    while i < n:
        mv = moves[i]
        # a run starts at prev (planar with the run) and needs XYZ known
        j = i
        if prev is not None and None not in prev:
            z0, f0 = prev[2], mv.get("f")
            while (j < n and moves[j].get("g", 1) == 1
                   and moves[j].get("f") == f0
                   and None not in (moves[j].get("x"), moves[j].get("y"))
                   and moves[j].get("z") is not None
                   and abs(moves[j]["z"] - z0) <= 1e-9):
                j += 1
        if j - i < MIN_MOVES:
            out.append(mv)
            old = prev or (None, None, None)
            prev = tuple(mv.get(a) if mv.get(a) is not None else o
                         for a, o in zip("xyz", old))
            i += 1
            continue
        run = moves[i:j]
        pts = [prev[:2]] + [(m["x"], m["y"]) for m in run]
        k = 0                              # next point index to emit up to
        for i0, i1, cx, cy, r, ccw, dev in fit_polyline(pts, tol, rmin, rmax):
            out.extend(run[k:i0])
            last = run[i1 - 1]
            out.append({"g": 3 if ccw else 2, "x": last["x"], "y": last["y"],
                        "z": last["z"], "f": last.get("f"), "cx": cx,
                        "cy": cy, "src": run[i0:i1]})
            k = i1
        out.extend(run[k:])
        last = run[-1]
        prev = (last["x"], last["y"], last["z"])
        i = j
    return out
