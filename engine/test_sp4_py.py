"""SP4-PY: band._simulate's vectorised disk stamp is exact - the per-window
ae list and window ends equal the pre-vectorisation implementation (kept
verbatim below as _simulate_ref, from 44b28d7) on random stocks and paths,
including grid edges, every entry mode, bores and approaches. Runnable
directly or under pytest (numpy only)."""
import math
import os
import random
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.band import _simulate, DIR_COS  # noqa: E402,F401
from engine.stock import StockField  # noqa: E402


def _simulate_ref(path, stock, z, tool_r, cell, bore_r, ends=None, *, bore_xy=None,
              entry="bore", approach=None, eps=0.05):
    """Replay ZE2 windowing on the engine stock grid: move-aligned windows of
    path travel; a window's area = distinct cells whose live top stands above
    z + 0.05 and that first fall under the cutter disk (applied at every
    emitted point) inside it. The entry bore (disk bore_r about the start or
    bore_xy - BS1a4d (c) helix centre) is
    pre-cleared when entry="bore"; "side"/"link" not (BS1a4d6c). Returns the
    list of per-window ae_eff estimates (mm); ends collects each window's
    cumulative end-of-window travel (zmap _ae2_windows: moves merge until the
    window reaches 1 mm, a move >= 1 mm is its own window; ZG2 tails merge).
    approach (BS1a4d6d): the emitted entry move's start point; for
    "side"/"link" it is replayed as the first move into path[0]."""
    if approach is not None and entry in ("side", "link"):
        # BS1a4d6d: the emitter FEEDS INTO path[0] from `approach`; replay
        # that move through the live stock so window 0 holds the approach's
        # own engagement, not the whole standing start disk.
        path = [tuple(approach[:2])] + list(path)
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
    stand = stock.top[j0:j1, i0:i1] > z + eps
    bx, by = (bore_xy[:2] if bore_xy else path[0][:2])
    ci, cj = stock._ci(bx) - i0, stock._cj(by) - j0
    # BS1a4d6c: pre-clear only the emitted entry's footprint (see entry).
    for dj, di in (offs_b if entry == "bore" else ()):
        a, b = ci + di, cj + dj
        if 0 <= a < stand.shape[1] and 0 <= b < stand.shape[0]:
            stand[b, a] = False
    wins = []
    tails = []           # ZG2: (sub-1 mm area, len(wins) when its chain broke)
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
                if acc_len > 0.0:    # >45 deg chord break (zmap ZG2): the
                    tails.append((acc_area, len(wins)))  # sub-1 mm fragment
                    acc_area = 0.0   # keeps its place, merges into a
                    acc_len = 0.0    # kept neighbour after the loop
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
    if acc_len > 0.0:
        tails.append((acc_area, len(wins)))  # ZG2: path-end tail
    for area, n in tails:                    # ZG2 merge: last kept window
        k = n - 1 if n else (0 if wins else -1)   # of its chain, else first
        if k >= 0:                           # kept; none: stays ungated
            wins[k] += area
    return wins


def _case(rng):
    box = (0.0, rng.uniform(20, 60), 0.0, rng.uniform(15, 40), 0.0, 20.0)
    sf = StockField(box, cell=0.5)
    sf.top = np.where(sf.inb, rng.uniform(5, 20), -np.inf)
    for _ in range(rng.randint(0, 6)):           # pockets already cleared
        x0, y0 = rng.uniform(0, box[1]), rng.uniform(0, box[3])
        i0, j0 = sf._ci(x0), sf._cj(y0)
        sf.top[max(j0 - 6, 0):j0 + 6, max(i0 - 6, 0):i0 + 6] = rng.uniform(0, 9)
    n = rng.randint(2, 60)
    x, y = rng.uniform(-8, box[1] + 8), rng.uniform(-8, box[3] + 8)
    path = []
    for _ in range(n):
        x += rng.uniform(-2.5, 2.5); y += rng.uniform(-2.5, 2.5)
        path.append((x, y))
    kw = dict(entry=rng.choice(["bore", "side", "link"]),
              eps=rng.choice([0.0, 0.05]))
    if rng.random() < 0.3:
        kw["bore_xy"] = (path[0][0] + 1.0, path[0][1], 0.0)
    if rng.random() < 0.3:
        kw["approach"] = (path[0][0] - 3.0, path[0][1] + 1.0)
    return sf, path, rng.uniform(4, 12), rng.choice([3.175, 6.343]), \
        rng.choice([0.0, 2.5, 5.07]), kw


def test_vectorised_simulate_matches_reference():
    rng = random.Random(20261101)
    for t in range(300):
        sf, path, z, r, br, kw = _case(rng)
        e1, e2 = [], []
        a = _simulate(path, sf, z, r, sf.cell, br, e1, **kw)
        b = _simulate_ref(path, sf, z, r, sf.cell, br, e2, **kw)
        assert a == b and e1 == e2, (t, a[:5], b[:5])
    print("PASS sp4_py simulate: 300 random cases identical")


if __name__ == "__main__":
    test_vectorised_simulate_matches_reference()
