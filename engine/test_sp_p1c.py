#!/usr/bin/env python3
"""Task SP-P1C tests: the bucket-grid / y-strip culled island_clear_fn and
the batched band._march must return EXACTLY the old booleans / floats.

Run: python3 engine/test_sp_p1c.py  (not pytest; exit 0 = all pass).

This file keeps a VERBATIM copy of the OLD island_clear_fn / _inside_loops /
_pt_seg_dist_np / _march (main @ 562bf68) as *_ref and compares element-wise.
The mutation self-checks patch the NEW source string IN MEMORY only
(textwrap-patched, exec'd) - the working tree is never touched.
"""
import inspect
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")

from engine import band as B  # noqa: E402
from engine import rough as R  # noqa: E402

MARCH_STEP = 0.25   # verbatim constant as the old band._march used it


# ---------------- verbatim OLD code (main @ 562bf68) ----------------

def _pt_seg_dist_np_ref(P, A, B):
    """(N,2) points vs (M,2) segment ends A,B -> (N,M) point-segment dist."""
    import numpy as np
    AB = B - A
    AP = P[:, None, :] - A[None, :, :]
    L2 = np.maximum((AB * AB).sum(axis=1)[None, :], 1e-12)
    t = np.clip((AP * AB[None, :, :]).sum(axis=2) / L2, 0.0, 1.0)
    d = AP - t[:, :, None] * AB[None, :, :]
    return np.sqrt((d * d).sum(axis=2))


def _inside_loops_ref(P, loops, chunk=512):
    import numpy as np
    tot = np.zeros(len(P), dtype=np.int64)
    for lp in loops:
        L = np.asarray(lp, dtype=float)
        if len(L) < 3:
            continue
        x, y = L[:, 0], L[:, 1]
        xn, yn = np.roll(x, -1), np.roll(y, -1)
        for s in range(0, len(P), chunk):
            blk = P[s:s + chunk]
            py = blk[:, 1][:, None]
            cross = (y[None, :] > py) != (yn[None, :] > py)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = x[None, :] + (py - y[None, :]) * (xn[None, :] - x[None, :]) \
                       / (yn[None, :] - y[None, :])
            hit = cross & (blk[:, 0][:, None] < xint)
            tot[s:s + chunk] += hit.sum(axis=1)
    return (tot % 2) == 1


# aliases so the verbatim copies above run unmodified in this module
_pt_seg_dist_np = _pt_seg_dist_np_ref
_inside_loops = _inside_loops_ref


def island_clear_fn_ref(islands, req):
    import numpy as np
    segs = []
    for lp in islands:
        L = np.asarray(lp, dtype=float)
        if len(L) < 2:
            continue
        segs.append(np.stack([L, np.roll(L, -1, axis=0)], axis=1))
    if not segs:
        return lambda pts: [True] * len(pts)
    AB = np.concatenate(segs, axis=0)          # (nseg, 2, 2)
    A = AB[:, 0, :]
    B = AB[:, 1, :]

    def f(pts):
        P = np.asarray(pts, dtype=float)
        out = np.full(len(P), np.inf)
        for s in range(0, len(P), 512):
            blk = P[s:s + 512]
            d = _pt_seg_dist_np(blk, A, AB[:, 1, :])
            out[s:s + 512] = d.min(axis=1)
        ins = _inside_loops(P, [lp for lp in islands if len(lp) >= 3])
        return [bool(v >= req) and not i for v, i in zip(out, ins)]
    return f


def _march_ref(p, ux, uy, isl_ok3, maxd):
    d = 0.0
    while d + MARCH_STEP <= maxd:
        dn = d + MARCH_STEP
        if not isl_ok3([(p[0] + ux * dn, p[1] + uy * dn)])[0]:
            break
        d = dn
    return d


# ---------------- scenario / point generators ----------------

def _rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _loop_sets(rng):
    """30 loop sets: annulus, self-touching vertex, horizontal edges,
    integer/half-integer aligned rects, open (len<3) loops, long edges,
    random polygons at random offsets (negative and large coords)."""
    sets = []
    # 0: annulus (outer square + inner hole loop)
    sets.append([_rect(100.5, -50.25, 20.0, 20.0),
                 _rect(106.5, -44.25, 8.0, 8.0)])
    # 1: self-touching vertex (figure-eight) + small rect
    sets.append([[(0.0, 0.0), (4.0, 0.0), (2.0, 1.0), (4.0, 2.0),
                  (0.0, 2.0), (2.0, 1.0)], _rect(-3.0, 6.0, 1.0, 1.0)])
    # 2: integer-aligned rect (edges exactly on bucket/strip boundaries)
    sets.append([_rect(-10.0, -7.0, 6.0, 5.0), _rect(2.0, 3.0, 3.0, 4.0)])
    # 3: half-integer rect + horizontal-edge-only zigzag loop
    sets.append([_rect(0.5, 0.5, 5.5, 4.5),
                 [(0.0, 0.0), (6.0, 0.0), (6.0, 2.0), (3.0, 2.0),
                  (3.0, 1.0), (0.0, 1.0)]])
    sets.append([_rect(0.0, 0.0, 2.0, 2.0), [(0.0, 0.0), (5.0, 0.0)],
                 [(1.0, 1.0)]])   # open 2-pt loop + 1-pt loop + rect
    for k in range(5, 30):
        isl = []
        for _ in range(int(rng.integers(1, 5))):
            cx = float(rng.uniform(-200.0, 900.0))
            cy = float(rng.uniform(-150.0, 150.0))
            n = int(rng.integers(3, 12))
            r = float(rng.uniform(0.5, 15.0))
            lp = []
            for v in range(n):
                a = 2.0 * math.pi * v / n + rng.uniform(-0.3, 0.3)
                rr = r * rng.uniform(0.4, 1.3)
                x = cx + rr * math.cos(a)
                y = cy + rr * math.sin(a)
                if rng.random() < 0.25:
                    y = float(round(y))          # horizontal-ish / integer y
                if rng.random() < 0.10:
                    x = float(round(x * 2.0)) / 2.0
                lp.append((x, y))
            if rng.random() < 0.25 and len(lp) >= 5:
                lp[len(lp) // 2] = lp[0]        # self-touching vertex
            if rng.random() < 0.20:             # long edge (spans buckets)
                lp.append((cx + r * 40.0, cy))
            if rng.random() < 0.15:             # open loop
                isl.append(lp[:2])
            isl.append(lp)
        if rng.random() < 0.3:                  # annulus pairing
            isl.append(_rect(cx - 1.0, cy - 1.0, 2.0, 2.0))
        sets.append(isl)
    return sets


def _all_segments(islands):
    segs = []
    for lp in islands:
        L = np.asarray(lp, dtype=float)
        if len(L) < 2:
            continue
        A = L
        Bv = np.roll(L, -1, axis=0)
        segs.extend(zip(A, Bv))
    return segs


def _points_for(islands, rng, n_rand=16000):
    """random cloud + every vertex + horizontal-edge midpoints + exact
    req +-1e-12 distance points + bucket/strip boundary points + far away."""
    P = [tuple(map(float, lp[k])) for lp in islands for k in range(len(lp))]
    segs = _all_segments(islands)
    xs = np.concatenate([np.asarray(lp, dtype=float)[:, 0]
                         for lp in islands if len(lp) >= 2])
    ys = np.concatenate([np.asarray(lp, dtype=float)[:, 1]
                         for lp in islands if len(lp) >= 2])
    x0, x1 = float(xs.min()) - 3.0, float(xs.max()) + 3.0
    y0, y1 = float(ys.min()) - 3.0, float(ys.max()) + 3.0
    P += list(map(tuple, rng.uniform([x0, y0], [x1, y1], size=(n_rand, 2))))
    # midpoints of horizontal edges + of all edges
    for (a, b) in segs:
        if a[1] == b[1]:
            P.append(((a[0] + b[0]) / 2.0, a[1]))
    # exact-distance points: req, req+-1e-12, both sides, foot at t=0/1/rand
    for req in (0.0, 0.01, 0.03):
        for _ in range(160):
            (a, b) = segs[int(rng.integers(len(segs)))]
            t = float(rng.choice([0.0, 1.0, rng.random()]))
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L < 1e-12:
                continue
            nx_, ny_ = -dy / L, dx / L
            fx, fy = ax + dx * t, ay + dy * t
            for off in (req + 1e-12, req - 1e-12, req):
                for sgn in (1.0, -1.0):
                    P.append((fx + sgn * nx_ * off, fy + sgn * ny_ * off))
    # bucket boundaries (x integer) + strip boundaries (y integer) + both
    for _ in range(1200):
        P.append((float(int(rng.integers(int(math.floor(x0)),
                                         int(math.ceil(x1))))),
                  float(rng.uniform(y0, y1))))
        P.append((float(rng.uniform(x0, x1)),
                  float(int(rng.integers(int(math.floor(y0)),
                                         int(math.ceil(y1)))))))
    for _ in range(400):
        P.append((float(int(rng.integers(int(math.floor(x0)),
                                         int(math.ceil(x1))))),
                  float(int(rng.integers(int(math.floor(y0)),
                                         int(math.ceil(y1)))))))
    # far outside the grid
    for _ in range(400):
        s = rng.choice([1, -1], size=2)
        P.append((x1 + 5.0 + rng.random() * 300.0 if s[0] > 0
                  else x0 - 5.0 - rng.random() * 300.0,
                  y1 + 5.0 + rng.random() * 300.0 if s[1] > 0
                  else y0 - 5.0 - rng.random() * 300.0))
    return np.asarray(P, dtype=float), (x0, x1, y0, y1)


def _mismatch_count(isl_fn, sets_points, reqs=(0.0, 0.01, 0.03)):
    """element-wise mismatches of isl_fn vs island_clear_fn_ref."""
    tot = 0
    for islands, P in sets_points:
        for req in reqs:
            f_new = isl_fn(islands, req)
            f_ref = island_clear_fn_ref(islands, req)
            a = np.asarray(f_new(P), dtype=bool)
            b = np.asarray(f_ref(P), dtype=bool)
            assert a.shape == b.shape, (a.shape, b.shape)
            tot += int((a != b).sum())
    return tot


# ---------------- tests ----------------

def test_property_identical():
    rng = np.random.default_rng(20261029)
    sets = _loop_sets(rng)
    assert len(sets) == 30
    sp = [(isl, _points_for(isl, rng)[0]) for isl in sets]
    n = sum(len(P) for _, P in sp)
    tot = _mismatch_count(R.island_clear_fn, sp)
    assert tot == 0, "property test: %d mismatches" % tot
    print("PASS property: 30 sets, %d pts total, req 0.0/0.01/0.03, "
          "0 mismatches" % n)


def test_march_identical():
    rng = np.random.default_rng(555)
    sets = _loop_sets(np.random.default_rng(20261029))
    bad = 0
    nray = 2000
    for i in range(nray):
        islands = sets[i % len(sets)]
        f = R.island_clear_fn(islands, 0.03)
        xs = np.concatenate([np.asarray(lp, dtype=float)[:, 0]
                             for lp in islands if len(lp) >= 2])
        ys = np.concatenate([np.asarray(lp, dtype=float)[:, 1]
                             for lp in islands if len(lp) >= 2])
        p = (float(rng.uniform(xs.min() - 2, xs.max() + 2)),
             float(rng.uniform(ys.min() - 2, ys.max() + 2)))
        a = rng.uniform(0.0, 2.0 * math.pi)
        ux, uy = math.cos(a), math.sin(a)
        maxd = float(rng.uniform(0.0, 8.0))
        d1 = B._march(p, ux, uy, f, maxd)
        d2 = _march_ref(p, ux, uy, f, maxd)
        if d1 != d2 or type(d1) is not type(d2):
            bad += 1
    assert bad == 0, "march: %d/%d rays differ" % (bad, nray)
    print("PASS march: 2000 rays, identical floats")


def _patched_island_clear_fn(patches):
    src = inspect.getsource(R.island_clear_fn)
    for old, new in patches:
        assert src.count(old) == 1, "mutation anchor not unique: %r" % old
        src = src.replace(old, new)
    ns = {"_pt_seg_dist_np": R._pt_seg_dist_np}
    exec(compile(src, "<mutated island_clear_fn>", "exec"), ns)
    return ns["island_clear_fn"]


def _mutated_mismatch_count(patches):
    rng = np.random.default_rng(20261029)
    sets = _loop_sets(rng)
    sp = [(isl, _points_for(isl, rng)[0]) for isl in sets]
    return _mismatch_count(_patched_island_clear_fn(patches), sp)


def test_mutation_bucket_margin():
    """(a) bucket margin req + 1e-6 -> req - 0.5: MUST break the property
    test (mismatch count > 0). In-memory patch only - tree untouched."""
    n = _mutated_mismatch_count([("m = req + 1e-6", "m = req - 0.5")])
    assert n > 0, "mutation (a) NOT caught (0 mismatches)"
    print("PASS mutation (a) bucket margin req+1e-6 -> req-0.5: "
          "mismatch count = %d" % n)


def test_mutation_strip_halfopen():
    """(b) strip margin dropped + strips half-open: MUST break."""
    n = _mutated_mismatch_count([
        ("sj0 = np.floor(np.minimum(ey, eyn) - 1e-9).astype(np.int64)",
         "sj0 = np.floor(np.minimum(ey, eyn)).astype(np.int64)"),
        ("sj1 = np.floor(np.maximum(ey, eyn) + 1e-9).astype(np.int64)",
         "sj1 = np.floor(np.maximum(ey, eyn)).astype(np.int64)"),
        ("for j in range(int(sj0[e]), int(sj1[e]) + 1):",
         "for j in range(int(sj0[e]), int(sj1[e])):")])
    assert n > 0, "mutation (b) NOT caught (0 mismatches)"
    print("PASS mutation (b) strip margin dropped + half-open strips: "
          "mismatch count = %d" % n)


def test_list_semantics_and_empty():
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    f = R.island_clear_fn([sq], 2.0)
    r = f([(5.0, 5.0), (100.0, 100.0), (0.0, 5.0), (1.0, 5.0)])
    assert isinstance(r, list) and all(type(x) is bool for x in r)
    g = R.island_clear_fn([], 2.0)
    assert g([(1.0, 2.0)]) == [True] and g([]) == []
    assert f([]) == []
    assert r == [False, True, False, False]
    print("PASS list semantics + empty islands")


if __name__ == "__main__":
    test_list_semantics_and_empty()
    test_property_identical()
    test_march_identical()
    test_mutation_bucket_margin()
    test_mutation_strip_halfopen()
    print("SP-P1C ALL PASS")
    sys.exit(0)
