"""FE5 step 0: engine-side LIVE-STOCK entry-depth estimator (diagnostic).

Tracks the post-roughing stock (--stock-from heightfield) resampled to a
0.1 mm grid CONSERVATIVELY (each fine cell = max of the source cells it
overlaps, never lower than the source; cells straddling the part outline /
data boundary take the max of the covering cells that have data). Every
finish move in EMIT ORDER mills the ball's exact swept-chord envelope into
that live stock (the FE4 stamp model); at each descending feed move's end
(the descent onto a pass start) the entry depth is reported as
max(stock - (z + dz(d))) over ball-footprint cells before the move cuts -
the ZB gate's own formula, from engine-side data only (no verify/zmap).
An entry whose footprint has no stock data (outside the grid) is reported
DEEP (depth = inf): fail closed.
"""
import math
import re

import numpy as np

FINE = 0.1          # mm, estimator grid pitch (matches the judge's cell)
# FE5 (a): ZB's domain - descents steeper than MAX_RAMP_DEG are entries
# (pass starts plunge vertically, so they qualify; in-pass descents at or
# below this angle are NOT scored by ZB and must not be scored here)
MAX_RAMP_DEG = 15.0
_TOK = re.compile(r"([A-Z])\s*(-?\d*\.?\d*)")


def parse_nc(path):
    """Modal LNC parse -> [{'g':0|1,'x','y','z','line'}] in mm. Skips
    tool/home plumbing (G43/G49/G28/G53) and comments; emits only changed
    XYZ moves once a modal motion code is known. G20 scales XY/Z by 25.4
    (the posted rough program is inch); G21 resets to mm."""
    moves, g, x, y, z = [], None, None, None, None
    sc = 1.0
    with open(path) as fh:
        for ln, raw in enumerate(fh, 1):
            s = raw.split("(")[0].replace("%", "").strip()
            if not s:
                continue
            words = {}
            for k, v in _TOK.findall(s):
                if v in ("", "-", "."):
                    continue
                words.setdefault(k, float(v))
            gi = words.get("G")
            if gi is not None:
                gi = int(gi)
                if gi == 20:
                    sc = 25.4
                elif gi == 21:
                    sc = 1.0
                if gi in (28, 43, 49, 53):
                    continue  # tool change / home / machine-coord plumbing
                if gi in (0, 1):
                    g = gi
            if g is None:
                continue
            nx = words.get("X", x)
            ny = words.get("Y", y)
            nz = words.get("Z", z)
            if "X" in words:
                nx = nx * sc
            if "Y" in words:
                ny = ny * sc
            if "Z" in words:
                nz = nz * sc
            changed = (nx, ny, nz) != (x, y, z)
            x, y, z = nx, ny, nz
            if nz is None or nx is None or ny is None or not changed:
                continue  # no complete XYZ position yet
            moves.append({"g": g, "x": nx, "y": ny, "z": nz, "line": ln})
            x, y, z = nx, ny, nz
    return moves


def load_heightfield(path):
    """Stock .npy (+ .json sidecar x0/y0/cell) -> (A, x0, y0, cell)."""
    import json
    import os
    stem = path[:-4] if path.endswith(".npy") else path
    A = np.load(stem + ".npy")
    with open(os.path.join(os.path.dirname(stem),
                           os.path.basename(stem) + ".json")) as fh:
        meta = json.load(fh)
    return A, float(meta["x0"]), float(meta["y0"]), float(meta["cell"])


def resample_fine(A, x0, y0, cell, fine=FINE, margin=0.0):
    """Conservative resample to `fine` mm: each fine cell = max of the
    source cells overlapping it (nan = no data). Never lower than source.
    FE5h: margin > 0 (coarse sources only) first box-dilates the source by
    Chebyshev radius ceil(margin/cell) (data-preserving max pool): the
    coarse lattice alone hides sub-cell high-stock rim slivers the fine
    judge keeps, under-reading entries (TB chain: 1.1303 mm plunge)."""
    ny, nx = A.shape
    nxf = int(round(nx * cell / fine))
    nyf = int(round(ny * cell / fine))
    cx = x0 + (np.arange(nxf) + 0.5) * fine
    cy = y0 + (np.arange(nyf) + 0.5) * fine
    ix = np.floor((cx - 0.5 * fine - x0) / cell).astype(np.int64)
    iy = np.floor((cy - 0.5 * fine - y0) / cell).astype(np.int64)
    ix = np.clip(ix, 0, nx - 1)
    iy = np.clip(iy, 0, ny - 1)
    kx = ((cx + 0.5 * fine - x0) / cell > ix) & (ix + 1 < nx)
    ky = ((cy + 0.5 * fine - y0) / cell > iy) & (iy + 1 < ny)
    Af = np.where(np.isfinite(A), A, -np.inf)
    if margin > 0.0 and cell > fine:
        for _ in range(int(math.ceil(margin / cell))):
            pad = np.full((ny + 2, nx + 2), -np.inf)
            pad[1:-1, 1:-1] = Af
            o = pad[1:-1, 1:-1].copy()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    o = np.maximum(o, pad[1 + dy:ny + 1 + dy,
                                          1 + dx:nx + 1 + dx])
            Af = np.where(np.isfinite(Af), o, -np.inf)
    b00 = Af[np.ix_(iy, ix)]
    b10 = np.where(kx[None, :], Af[np.ix_(iy, np.minimum(ix + 1, nx - 1))],
                   -np.inf)
    b01 = np.where(ky[:, None], Af[np.ix_(np.minimum(iy + 1, ny - 1), ix)],
                   -np.inf)
    b11 = np.where(kx[None, :] & ky[:, None],
                   Af[np.ix_(np.minimum(iy + 1, ny - 1),
                            np.minimum(ix + 1, nx - 1))], -np.inf)
    return np.maximum(np.maximum(b00, b10), np.maximum(b01, b11))


class LiveStock:
    """Live material heightfield on the fine grid, milled by the ball's
    swept envelope in emit order. No-data cells are -inf."""

    def __init__(self, A, x0, y0, cell, R, fine=FINE, margin=0.0):
        F = resample_fine(A, x0, y0, cell, fine, margin=margin)
        self.R = float(R)
        self.f = fine
        self.x0, self.y0 = x0, y0
        self.kR = int(math.ceil(self.R / fine))
        self.pad = self.kR + 1     # L is F padded by pad cells all around
        self.L = np.pad(F, self.pad, constant_values=-np.inf)

    def with_radius(self, R):
        """Same live grid seen with a different ball radius (rest tool)."""
        if R > self.R:
            raise ValueError("radius %g exceeds the padded grid" % R)
        s = object.__new__(LiveStock)
        # L stays shared: it is padded by the ORIGINAL pad, so pad must be
        # carried over - re-deriving it from the smaller R shifts every
        # window by (pad - new kR - 1) cells (FE5: rest read the WRONG
        # stock, ~3.2 mm off)
        s.R, s.f, s.x0, s.y0, s.L = float(R), self.f, self.x0, self.y0, \
            self.L
        s.kR = int(math.ceil(s.R / s.f))
        s.pad = self.pad
        assert s.kR + 1 <= s.pad
        return s

    def _win(self, x, y):
        """Window of +/- (kR+1) cells around the cell containing (x, y)
        (zmap-style floor indexing), plus its origin in L coordinates."""
        qk = self.kR + 1
        ci = int(math.floor((x - self.x0) / self.f)) + self.pad
        cj = int(math.floor((y - self.y0) / self.f)) + self.pad
        if ci - qk < 0 or cj - qk < 0 or cj + qk >= self.L.shape[0] \
                or ci + qk >= self.L.shape[1]:
            return None, 0, 0
        return (self.L[cj - qk:cj + qk + 1, ci - qk:ci + qk + 1],
                cj - qk, ci - qk)

    def _grid_xy(self, j0, i0, nj, ni, x, y):
        """Cell-center offsets from (x, y) for the window at (j0, i0)
        (L indices; L column c <-> F column c - pad)."""
        gx = self.x0 + (np.arange(i0, i0 + ni) - self.pad + 0.5) * self.f \
            - x
        gy = self.y0 + (np.arange(j0, j0 + nj) - self.pad + 0.5) * self.f \
            - y
        return np.meshgrid(gx, gy)

    def disk_depth(self, x, y, z):
        """ZB-formula depth at (x, y) for a ball tip at z against the LIVE
        stock: max(stock - (z + dz(d))) over footprint cells with data;
        inf = cannot tell (fail closed)."""
        w, j0, i0 = self._win(x, y)
        if w is None:
            return math.inf
        dxg, dyg = self._grid_xy(j0, i0, w.shape[0], w.shape[1], x, y)
        d2 = dxg * dxg + dyg * dyg
        m = (d2 <= self.R * self.R + 1e-9) & np.isfinite(w)
        if not m.any():
            return math.inf
        v = w[m] - (self.R - np.sqrt(np.maximum(self.R * self.R - d2[m],
                                                0.0)))
        return float(np.max(v)) - z

    def disk_top(self, x, y):
        """Highest ball-surface clearance Z at (x, y) against the LIVE stock:
        the lowest feed z whose ball footprint removes nothing
        (max(stock - dz(d)) over cells with data); inf = cannot tell."""
        w, j0, i0 = self._win(x, y)
        if w is None:
            return math.inf
        dxg, dyg = self._grid_xy(j0, i0, w.shape[0], w.shape[1], x, y)
        d2 = dxg * dxg + dyg * dyg
        m = (d2 <= self.R * self.R + 1e-9) & np.isfinite(w)
        if not m.any():
            return math.inf
        return float(np.max(w[m] - (self.R - np.sqrt(
            np.maximum(self.R * self.R - d2[m], 0.0)))))

    def stamp_chord(self, a, b):
        """Mill the exact swept-ball envelope of feed move a->b into the
        live stock (the FE4 chord model; vertical moves included)."""
        ax, ay, az = float(a[0]), float(a[1]), float(a[2])
        vx, vy = float(b[0]) - ax, float(b[1]) - ay
        kR = self.kR
        L = self.L
        Rb, f = self.R, self.f
        Lxy = math.hypot(vx, vy)
        ci = int(math.floor((ax - self.x0) / f)) + self.pad
        cj = int(math.floor((ay - self.y0) / f)) + self.pad
        if Lxy <= 1e-9:
            w, j0, i0 = self._win(ax, ay)
            if w is None:
                return
            dxg, dyg = self._grid_xy(j0, i0, w.shape[0], w.shape[1], ax, ay)
            d2 = dxg * dxg + dyg * dyg
            zc = min(az, float(b[2]))
            np.minimum(w, np.where(d2 <= Rb * Rb,
                                   zc + Rb - np.sqrt(np.maximum(Rb * Rb - d2,
                                                              0.0)),
                                   np.inf), out=w)
            return
        k = (float(b[2]) - az) / Lxy
        ux, uy = vx / Lxy, vy / Lxy
        nvx = int(math.ceil(vx / f))
        nvy = int(math.ceil(vy / f))
        i0 = max(0, min(ci, ci + nvx) - kR - 1)
        i1 = min(L.shape[1], max(ci, ci + nvx) + kR + 2)
        j0 = max(0, min(cj, cj + nvy) - kR - 1)
        j1 = min(L.shape[0], max(cj, cj + nvy) + kR + 2)
        if i0 >= i1 or j0 >= j1:
            return
        dxg, dyg = self._grid_xy(j0, i0, j1 - j0, i1 - i0, ax, ay)
        sp = dxg * ux + dyg * uy
        perp2 = (dxg * uy - dyg * ux) ** 2
        rr = np.maximum(Rb * Rb - perp2, 0.0)
        sig = np.clip(sp - k * np.sqrt(rr) / math.sqrt(1.0 + k * k),
                      0.0, Lxy)
        d2 = perp2 + (sig - sp) ** 2
        floorz = az + k * sig + Rb - np.sqrt(np.maximum(Rb * Rb - d2, 0.0))
        w = L[j0:j1, i0:i1]
        np.minimum(w, np.where(d2 <= Rb * Rb, floorz, np.inf), out=w)

    def stamp_flat_chord(self, a, b):
        """Mill the exact swept envelope of a FLAT-bottom cylinder feed move
        a->b (radius self.R) into the live stock: every covered cell drops to
        the lowest tip z that reaches it (last position of a descent, first
        of an ascent; flat bottom => no curvature term)."""
        ax, ay, az = float(a[0]), float(a[1]), float(a[2])
        vx, vy = float(b[0]) - ax, float(b[1]) - ay
        kR = self.kR
        L = self.L
        Rb, f = self.R, self.f
        Lxy = math.hypot(vx, vy)
        ci = int(math.floor((ax - self.x0) / f)) + self.pad
        cj = int(math.floor((ay - self.y0) / f)) + self.pad
        if Lxy <= 1e-9:
            w, j0, i0 = self._win(ax, ay)
            if w is None:
                return
            dxg, dyg = self._grid_xy(j0, i0, w.shape[0], w.shape[1], ax, ay)
            d2 = dxg * dxg + dyg * dyg
            zc = min(az, float(b[2]))
            np.minimum(w, np.where(d2 <= Rb * Rb, zc, np.inf), out=w)
            return
        k = (float(b[2]) - az) / Lxy
        ux, uy = vx / Lxy, vy / Lxy
        nvx = int(math.ceil(vx / f))
        nvy = int(math.ceil(vy / f))
        i0 = max(0, min(ci, ci + nvx) - kR - 1)
        i1 = min(L.shape[1], max(ci, ci + nvx) + kR + 2)
        j0 = max(0, min(cj, cj + nvy) - kR - 1)
        j1 = min(L.shape[0], max(cj, cj + nvy) + kR + 2)
        if i0 >= i1 or j0 >= j1:
            return
        dxg, dyg = self._grid_xy(j0, i0, j1 - j0, i1 - i0, ax, ay)
        sp = dxg * ux + dyg * uy
        perp2 = (dxg * uy - dyg * ux) ** 2
        sq = np.sqrt(np.maximum(Rb * Rb - perp2, 0.0))
        # lowest tip z over the covered interval: last covering point of a
        # descent, first of an ascent/flat move (clamped to the chord)
        sig = np.clip(sp + sq if k < 0.0 else sp - sq, 0.0, Lxy)
        floorz = az + k * sig
        # FE5 RESUME: coverage is the full capsule (segment + end caps),
        # not perp2 alone - a cell is covered iff its TRUE distance to the
        # SEGMENT is <= R (cells past a chord's ends must NOT inherit the
        # end-point z; same capsule test the ball stamp uses via d2)
        spc = np.clip(sp, 0.0, Lxy)
        d2 = perp2 + (spc - sp) ** 2
        w = L[j0:j1, i0:i1]
        np.minimum(w, np.where(d2 <= Rb * Rb + 1e-9, floorz, np.inf),
                   out=w)


def build_rough_stock(nc_path, dia, box, top_z, fine=FINE):
    """FE5 (b): the live stock at `fine` mm built from the ROUGH program's
    OWN emitted moves only: start from `top_z` over `box`
    (xmin, xmax, ymin, ymax), pad the grid by the tool radius, and mill
    every G1 move with a flat cylinder sweep (G0 never cuts). No min()
    against the part or any floor - the swept heightfield IS the stock.
    Cells outside the box are no-data (-inf)."""
    moves = parse_nc(nc_path)
    R = float(dia) / 2.0
    xmin, xmax, ymin, ymax = (float(v) for v in box)
    x0 = xmin - R
    y0 = ymin - R
    nx = int(math.ceil((xmax - xmin + 2.0 * R) / fine))
    ny = int(math.ceil((ymax - ymin + 2.0 * R) / fine))
    A = np.full((ny, nx), -np.inf)
    cx = x0 + (np.arange(nx) + 0.5) * fine
    cy = y0 + (np.arange(ny) + 0.5) * fine
    inside = ((cx >= xmin - 1e-9) & (cx <= xmax + 1e-9))[None, :] \
        & ((cy >= ymin - 1e-9) & (cy <= ymax + 1e-9))[:, None]
    A[inside] = float(top_z)
    live = LiveStock(A, x0, y0, fine, R, fine=fine)
    prev = None
    for mv in moves:
        cur = (mv["x"], mv["y"], mv["z"])
        if prev is not None and mv["g"] == 1:
            live.stamp_flat_chord(prev, cur)
        prev = cur
    return live


def _replay_stamp_batch(L, x0, y0, fine, R, cr, a0, kR, pad2, bmax,
                        sx, sy, sz):
    """RR-STOCK speed helper: stamp the tool disks of a batch of samples
    into L, padded by pad2 = pad + 2*kR + 2 so windows never clip (the
    extra margin is -inf and min keeps it). Bit-identical to the old
    per-sample loop: same floating-point expressions per element, and
    np.minimum into L is associative, commutative and idempotent, so
    only the SET of (window, value) pairs matters; samples dropped by
    `keep` would only have stamped -inf cells (or were clipped away)."""
    H, W = L.shape
    for c in range(0, sx.shape[0], bmax):
        bx, by, bz = sx[c:c + bmax], sy[c:c + bmax], sz[c:c + bmax]
        jj = np.floor((by - y0) / fine).astype(np.int64) + pad2
        ii = np.floor((bx - x0) / fine).astype(np.int64) + pad2
        keep = ((jj >= kR) & (jj < H - kR) & (ii >= kR) & (ii < W - kR))
        if not keep.all():
            jj, ii, bx, by, bz = (a[keep] for a in (jj, ii, bx, by, bz))
            if not jj.size:
                continue
        o = np.arange(-kR, kR + 1)
        gx = x0 + ((ii[:, None] + o - pad2) + 0.5) * fine - bx[:, None]
        gy = y0 + ((jj[:, None] + o - pad2) + 0.5) * fine - by[:, None]
        dd = np.hypot(gx[:, None, :], gy[:, :, None])
        m = dd <= R + 1e-9
        if cr:
            np.subtract(dd, a0, out=dd)
            np.maximum(dd, 0.0, out=dd)
            dd *= dd
            np.subtract(cr * cr, dd, out=dd)
            np.maximum(dd, 0.0, out=dd)
            np.sqrt(dd, out=dd)
            np.subtract(cr, dd, out=dd)
            np.add(dd, bz[:, None, None], out=dd)
            dd[...] = np.where(m, dd, np.inf)
        else:
            dd[...] = np.where(m, bz[:, None, None] + 0.0, np.inf)
        for b, (j, i) in enumerate(zip(jj.tolist(), ii.tolist())):
            w = L[j - kR:j + kR + 1, i - kR:i + kR + 1]
            np.minimum(w, dd[b], out=w)


def _replay_move_flat(L, x0, y0, fine, R, pad2, p, cur, d, n):
    """RR-STOCK speed path for a FLAT tool on one G1 move: z is linear
    along the move, so every cell's winning stamp (the minimum over the
    samples covering it) is taken from the LAST sample covering it
    (descending/flat z) or the FIRST one (ascending) - the covering
    samples of a cell form one contiguous run because the disk centre
    moves along a straight line. The winner index per cell is computed
    from the continuous capsule entry/exit time +-3 candidate samples,
    then the EXACT old predicate hypot(cell - s_i) <= R + 1e-9 is
    evaluated on those candidates (the float error of the capsule math
    is ~1e-3 of one sample step even at the worst n and grazing angle,
    so the true boundary index is always inside the candidate window);
    cells outside stay inf and stamp nothing."""
    T = R + 1e-9
    t = np.linspace(0.0, 1.0, n + 1)
    sx = p[0] + d[0] * t
    sy = p[1] + d[1] * t
    sz = p[2] + d[2] * t
    lxy2 = d[0] * d[0] + d[1] * d[1]
    H, W = L.shape
    i0 = max(0, int(math.floor((min(p[0], cur[0]) - T - 2 * fine - x0)
                               / fine)) + pad2)
    i1 = min(W, int(math.ceil((max(p[0], cur[0]) + T + 2 * fine - x0)
                              / fine)) + pad2 + 1)
    j0 = max(0, int(math.floor((min(p[1], cur[1]) - T - 2 * fine - y0)
                               / fine)) + pad2)
    j1 = min(H, int(math.ceil((max(p[1], cur[1]) + T + 2 * fine - y0)
                              / fine)) + pad2 + 1)
    if i0 >= i1 or j0 >= j1:
        return
    Xc = x0 + (np.arange(i0, i1) - pad2 + 0.5) * fine
    Yc = y0 + (np.arange(j0, j1) - pad2 + 0.5) * fine
    vx = (Xc - p[0])[None, :]
    vy = (Yc - p[1])[:, None]
    proj = vx * d[0] + vy * d[1]
    tau = proj / lxy2
    perp2 = np.maximum(vx * vx + vy * vy - tau * proj, 0.0)
    half = np.sqrt(np.maximum(T * T - perp2, 0.0)) / math.sqrt(lxy2)
    end = (tau + half if d[2] <= 0.0 else tau - half) * n
    c0 = np.rint(np.clip(end, 0.0, float(n))).astype(np.int64)
    win = np.zeros(c0.shape, np.int64)
    found = np.zeros(c0.shape, dtype=bool)
    for o in ((3, 2, 1, 0, -1, -2, -3) if d[2] > 0.0
              else (-3, -2, -1, 0, 1, 2, 3)):
        idx = np.clip(c0 + o, 0, n)
        P = np.hypot(Xc[None, :] - sx[idx], Yc[:, None] - sy[idx]) <= T
        found |= P
        np.copyto(win, idx, where=P)
    wL = L[j0:j1, i0:i1]
    np.minimum(wL, np.where(found, sz[win] + 0.0, np.inf), out=wL)


def _replay_worker(L, x0, y0, fine, R, cr, a0, kR, pad2, bmax, ends, cut,
                   lo, stride):
    """One RR-STOCK worker: replays move indices lo::stride into its own
    padded copy; workers fold later by np.minimum, exact and
    order-independent, so each sample is bit-identical to the old loop."""
    buf, nbuf = [], 0
    for mi in range(lo, ends.shape[0], stride):
        if not cut[mi]:
            continue
        p, cur = ends[mi, :3], ends[mi, 3:]
        d = cur - p
        n = 1 if abs(d[0]) <= 1e-9 and abs(d[1]) <= 1e-9 else max(
            2, int(math.ceil(float(np.linalg.norm(d)) / (fine / 4.0))))
        if cr == 0.0 and n >= 12 and d[0] * d[0] + d[1] * d[1] >= 2.5e-3:
            _replay_move_flat(L, x0, y0, fine, R, pad2, p, cur, d, n)
            continue
        t = np.linspace(0.0, 1.0, n + 1)
        buf.append((p[0] + d[0] * t, p[1] + d[1] * t,
                    np.full(n + 1, min(p[2], cur[2])) if n == 1
                    else p[2] + d[2] * t))
        nbuf += n + 1
        if nbuf >= bmax:
            _replay_stamp_batch(L, x0, y0, fine, R, cr, a0, kR, pad2, bmax,
                                *(np.concatenate(a) for a in zip(*buf)))
            buf, nbuf = [], 0
    if buf:
        _replay_stamp_batch(L, x0, y0, fine, R, cr, a0, kR, pad2, bmax,
                            *(np.concatenate(a) for a in zip(*buf)))


def replay_stock(moves, dia, corner, out_path, box=None, top_z=None,
                 init=None, fine=FINE):
    """RR-STOCK: replay an EMITTED move list (modal x/y/z, g 0|1, mm) with
    its tool into the engine's own `fine` mm stock, written as .npy +
    x0/y0/cell .json sidecar. Start from `init` (A, x0, y0, cell), resampled
    conservatively, or a full `box` (xmin xmax ymin ymax) raised to top_z;
    every G1 is sampled at <= fine/4 (the judge's resolution) and stamps the
    tool profile disk (dz = 0 inside R-cr, cr - sqrt(cr^2-(d-R+cr)^2) beyond;
    cr = dia/2 the ball, cr = 0 the flat); G0 never cuts - never lower than
    what the program removes. Returns (A, x0, y0, fine)."""
    import json, os, time
    t0 = time.time()
    R = float(dia) / 2.0
    cr = min(float(corner), R) if corner else 0.0
    if init is not None:
        A0, x0, y0, cell = init
        # same pitch: resample_fine would max-pool the touching neighbour
        F = A0 if abs(float(cell) - fine) < 1e-12 \
            else resample_fine(A0, x0, y0, cell, fine)
    else:
        xmn, xmx, ymn, ymx = (float(v) for v in box[:4])
        x0, y0 = xmn - R, ymn - R
        cx = x0 + (np.arange(int(math.ceil((xmx - xmn + 2 * R) / fine))) + .5) * fine
        cy = y0 + (np.arange(int(math.ceil((ymx - ymn + 2 * R) / fine))) + .5) * fine
        F = np.where(((cx >= xmn - 1e-9) & (cx <= xmx + 1e-9))[None, :]
                     & ((cy >= ymn - 1e-9) & (cy <= ymx + 1e-9))[:, None],
                     float(top_z), -np.inf)
    kR = int(math.ceil(R / fine))
    pad, a0 = kR + 1, R - cr
    pad2 = pad + 2 * kR + 2
    # batch samples so the 3D stamp arrays stay cache-sized
    bmax = max(4, min(64, 200000 // ((2 * kR + 1) ** 2)))
    # modal start/end of every G1 cut - the only serial pass over moves
    n_mv = len(moves)
    ends = np.empty((n_mv, 6))
    cut = np.zeros(n_mv, dtype=bool)
    pos = None
    for mi, mv in enumerate(moves):
        cur = tuple(p if mv.get(k) is None else mv[k]
                    for k, p in zip("xyz", pos or (0.0, 0.0, 0.0)))
        if pos is not None and mv["g"] == 1:
            cut[mi] = True
            ends[mi, :3] = pos
            ends[mi, 3:] = cur
        pos = cur
    # threads: min(4, $ENGINE_WORKERS), 1 when unset (coordinator); only
    # while the T padded copies stay under 512 MB
    T = min(4, max(1, int(os.environ.get("ENGINE_WORKERS", "1"))))
    pb = (F.shape[0] + 2 * pad2) * (F.shape[1] + 2 * pad2) * F.itemsize
    T = T if n_mv >= 2000 and T * pb < 512e6 else 1
    if T == 1:
        L = np.pad(F, pad2, constant_values=-np.inf)
        _replay_worker(L, x0, y0, fine, R, cr, a0, kR, pad2, bmax, ends,
                       cut, 0, 1)
    else:
        # independent per-worker padded copies; the np.minimum fold is
        # exact and order-independent
        import threading
        ls = [np.pad(F, pad2, constant_values=-np.inf) for _ in range(T)]
        th = [threading.Thread(target=_replay_worker,
                               args=(ls[k], x0, y0, fine, R, cr, a0, kR,
                                     pad2, bmax, ends, cut, k, T))
              for k in range(T)]
        for h in th:
            h.start()
        for h in th:
            h.join()
        L = ls[0]
        for k in range(1, T):
            np.minimum(L, ls[k], out=L)
    A = L[pad2:-pad2, pad2:-pad2]
    np.save(out_path, A)
    with open(os.path.splitext(out_path)[0] + ".json", "w") as fh:
        json.dump({"x0": x0, "y0": y0, "cell": fine}, fh)
    print("replay_stock: %d moves -> %s in %.1f s"
          % (len(moves), out_path, time.time() - t0), flush=True)
    return A, x0, y0, fine


def estimate_entries(moves, live):
    """FE5 (a): entries mirror zmap's ZB domain - every pass-start descent
    INCLUDING down-link drops (the feed move right after a G0 or at program
    start; a down link's vertical drop is itself scored at 90 deg), plus
    in-pass descents steeper than MAX_RAMP_DEG (angle from the chord's own
    XY length and dZ). In-pass descents at or below MAX_RAMP_DEG are NOT
    scored. Every feed move is stamped into the live stock (G0 never cuts);
    depth is read BEFORE the entry move cuts.
    Returns entries sorted in program order:
    {line, x, y, z, depth_mm, deep}."""
    entries = []
    prev = None
    pass_start = True  # the first feed move enters material from a G0/air
    for mv in moves:
        cur = (mv["x"], mv["y"], mv["z"])
        if prev is None:
            prev = cur
            continue
        if mv["g"] == 1:
            dz = prev[2] - cur[2]
            dxy = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            if dz > 1e-12:
                ang = math.degrees(math.atan2(dz, dxy))
                if pass_start or ang > MAX_RAMP_DEG:
                    d = live.disk_depth(cur[0], cur[1], cur[2])
                    entries.append({"line": mv["line"],
                                  "x": round(cur[0], 3),
                                  "y": round(cur[1], 3),
                                  "z": round(cur[2], 3),
                                  "depth_mm": d,
                                  "deep": math.isinf(d)})
            live.stamp_chord(prev, cur)
            # the pass is now under way: only a G0 (or program start) makes
            # the NEXT feed move a pass-start descent again; the vertical
            # half of a down link is itself the entry (90 deg > 15, scored)
            pass_start = False
        else:
            pass_start = True
        prev = cur
    return entries
