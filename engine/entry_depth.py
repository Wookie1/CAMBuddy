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


def resample_fine(A, x0, y0, cell, fine=FINE):
    """Conservative resample to `fine` mm: each fine cell = max of the
    source cells overlapping it (nan = no data). Never lower than source."""
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

    def __init__(self, A, x0, y0, cell, R, fine=FINE):
        F = resample_fine(A, x0, y0, cell, fine)
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
