"""Stock heightfield for rest-aware roughing (Task G).

Tracks the top Z of the remaining stock on a uniform XY grid. Written
independently of verify/zmap.py (same grid idea, no import): the engine's
own model, used to

  * build per-level Adaptive2d stock regions (cells where the stock top is
    still above level Z + axial leave and >= ~1 mm above the part), so
    Adaptive2d skips cleared area instead of re-traversing the whole box;
  * answer link-clearance queries: is a straight link at cutting Z (or
    Z + lift) clear of stock, so the tool can stay down between paths?

Tool footprint: flat/bull disk — cells under the footprint are cut down to
tip Z + corner-profile height h(d) (h = 0 inside r - cr). The part
heightfield (resampled onto this grid) is only used for the "remaining
stock above the part" clip; gouge checking stays in verify/zmap.py.
"""
import json
import math

import numpy as np


def save_stock_npy(stock, path):
    """Write a StockField's final top surface to <path>.npy (+ .json sidecar
    with x0/y0/cell, the engine/zmap heightfield convention; cells outside
    the tracked stock box are NaN). Consumed by finish --stock-from."""
    stem = path[:-4] if path.endswith(".npy") else path
    A = np.where(np.isfinite(stock.top), stock.top, np.nan)
    np.save(stem + ".npy", A)
    with open(stem + ".json", "w") as fh:
        json.dump({"x0": stock.x0, "y0": stock.y0, "cell": stock.cell}, fh)


class StockField:
    """top[j, i] = highest remaining stock Z at cell centre; -inf outside
    the stock box. Row j grows with +Y, column i with +X."""

    def __init__(self, stock_box, cell=0.5, pad_cells=None, reach=8.0):
        sxmin, sxmax, symin, symax, szmin, szmax = stock_box
        self.cell = float(cell)
        pad = pad_cells if pad_cells else int(math.ceil(reach / cell))
        self.pad = pad
        nx = int(math.ceil((sxmax - sxmin) / cell)) + 2 * pad
        ny = int(math.ceil((symax - symin) / cell)) + 2 * pad
        self.x0 = sxmin - pad * cell
        self.y0 = symin - pad * cell
        self.nx, self.ny = nx, ny
        xs = self.x0 + (np.arange(nx) + 0.5) * cell
        ys = self.y0 + (np.arange(ny) + 0.5) * cell
        inb = ((xs >= sxmin) & (xs <= sxmax))[None, :] & \
              ((ys >= symin) & (ys <= symax))[:, None]
        self.inb = inb
        self.top = np.where(inb, float(szmax), -np.inf)
        self.part = None

    # ------------------------------------------------------------------ grid
    def _ci(self, x):
        return int(math.floor((x - self.x0) / self.cell))

    def _cj(self, y):
        return int(math.floor((y - self.y0) / self.cell))

    def top_at(self, x, y):
        i, j = self._ci(x), self._cj(y)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return float(self.top[j, i])
        return -np.inf

    def set_part_grid(self, part):
        """part: array on THIS grid (same x0/y0/cell/shape), NaN where no
        part material; stock above the part is what roughing must remove."""
        p = np.where(np.isfinite(part), part, -np.inf)
        self.part = p

    def set_part_from_other_grid(self, part, x0p, y0p, cellp, fill=-1e9):
        """Nearest-neighbour resample of `part` (row j = +Y like ours) onto
        this grid; NaN -> fill."""
        xs = self.x0 + (np.arange(self.nx) + 0.5) * self.cell
        ys = self.y0 + (np.arange(self.ny) + 0.5) * self.cell
        ii = np.clip(((xs - x0p) / cellp).astype(np.int64), 0,
                     part.shape[1] - 1)
        jj = np.clip(((ys - y0p) / cellp).astype(np.int64), 0,
                     part.shape[0] - 1)
        p = part[np.ix_(jj, ii)]
        p = np.where(np.isfinite(p), p, fill)
        self.set_part_grid(p)

    # ---------------------------------------------------------------- miling
    def _disk_radius_cells(self, tool_r):
        """Disk radius in cells (rounded up) for footprint stamping."""
        return int(math.ceil(tool_r / self.cell))

    def mill_segment(self, xa, ya, xb, yb, zc, tool_r, corner_r=0.0):
        """Cut the swept disk down: every cell under the footprint along the
        segment gets top = min(top, zc + h(d)). `zc` is the tip Z (use the
        higher end of a sloped move: conservative)."""
        k = self._disk_radius_cells(tool_r)
        c = self.cell
        i0 = self._ci(min(xa, xb)) - k
        i1 = self._ci(max(xa, xb)) + k + 1
        j0 = self._cj(min(ya, yb)) - k
        j1 = self._cj(max(ya, yb)) + k + 1
        i0, j0 = max(i0, 0), max(j0, 0)
        i1, j1 = min(i1, self.nx), min(j1, self.ny)
        if i0 >= i1 or j0 >= j1:
            return
        xs = self.x0 + (np.arange(i0, i1) + 0.5) * c
        ys = self.y0 + (np.arange(j0, j1) + 0.5) * c
        X, Y = np.meshgrid(xs, ys)
        abx, aby = xb - xa, yb - ya
        L2 = abx * abx + aby * aby
        if L2 < 1e-12:
            t = np.zeros_like(X)
        else:
            t = np.clip(((X - xa) * abx + (Y - ya) * aby) / L2, 0.0, 1.0)
        dx = X - (xa + t * abx)
        dy = Y - (ya + t * aby)
        d = np.sqrt(dx * dx + dy * dy)
        near = d <= tool_r
        if not near.any():
            return
        # exact kernel height where the disk fully covers the sub-array,
        # distance-based height at the strip ends
        hh = corner_r - np.sqrt(np.maximum(
            corner_r ** 2 - np.maximum(d - (tool_r - corner_r), 0.0) ** 2,
            0.0)) if corner_r > 1e-9 else np.zeros_like(d)
        newtop = zc + hh
        sub = self.top[j0:j1, i0:i1]
        np.putmask(sub, near & (sub > newtop), newtop)

    def mill_path(self, pts, z, tool_r, corner_r=0.0):
        """Mill a polyline at constant tip Z (list of (x, y))."""
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            if xa == xb and ya == yb:
                continue
            self.mill_segment(xa, ya, xb, yb, z, tool_r, corner_r)

    def mill_sloped(self, xa, ya, xb, yb, za, zb, tool_r, corner_r=0.0):
        """Mill a sloped move (helix/ramp/plunge) conservatively: each
        segment at its higher end Z."""
        self.mill_segment(xa, ya, xb, yb, max(za, zb), tool_r, corner_r)

    # -------------------------------------------------------------- regions
    def region_mask(self, z, axial_leave=0.381, min_rest=1.0, leave_margin=None):
        """Cells that still need machining at level Z: stock top above
        Z + axial leave, the part surface at/below Z (cells whose part is
        higher are island territory - not reachable with the tip at Z), and
        (when a part grid is set) at least min_rest mm of stock left above
        the part. When leave_margin is given, cells within that distance of
        the island footprint (part > Z) are excluded too: they form the
        radial-leave fin band that no legal cutter centre can reach at this
        level (centres must stay >= tool_r + leave from the islands, and the
        rim already cuts that band when passes run next to the walls)."""
        m = (self.top > z + axial_leave) & self.inb
        if self.part is not None:
            pz = (self.part > z) & self.inb
            m &= ~pz
            if min_rest is not None:
                m &= (self.top - self.part) > min_rest
            if leave_margin is not None and pz.any():
                m &= ~self.dilate(pz, leave_margin)
        return m

    def region_area(self, mask):
        return float(mask.sum()) * self.cell * self.cell

    def dilate(self, mask, radius):
        """Boolean dilation by a disk of `radius` (shift-OR trick). Offsets
        are clipped to the grid so a radius larger than the grid extent
        (possible when inch inputs expand the stock box) never crashes."""
        k = int(math.ceil(radius / self.cell))
        offs = [(dj, di) for dj in range(-k, k + 1)
                for di in range(-k, k + 1)
                if (dj * dj + di * di) * self.cell * self.cell <= radius * radius]
        out = np.zeros_like(mask, dtype=bool)
        m = mask.astype(np.uint8)
        for dj, di in offs:
            j0 = max(0, dj, dj - self.ny)
            j1 = min(self.ny, self.ny + dj)
            i0 = max(0, di, di - self.nx)
            i1 = min(self.nx, self.nx + di)
            if j0 >= j1 or i0 >= i1:
                continue  # this shifted copy lies entirely outside the grid
            out[j0:j1, i0:i1] |= m[j0 - dj:j1 - dj, i0 - di:i1 - di].astype(bool)
        return out

    def max_filter(self, radius):
        """Max of `top` over a disk of `radius` (shift-max trick)."""
        k = int(math.ceil(radius / self.cell))
        offs = [(dj, di) for dj in range(-k, k + 1)
                for di in range(-k, k + 1)
                if (dj * dj + di * di) * self.cell * self.cell <= radius * radius]
        out = np.full_like(self.top, -np.inf)
        for dj, di in offs:
            j0, j1 = max(0, dj), min(self.ny, self.ny + dj)
            i0, i1 = max(0, di), min(self.nx, self.nx + di)
            np.maximum(out[j0:j1, i0:i1],
                       self.top[j0 - dj:j1 - dj, i0 - di:i1 - di],
                       out=out[j0:j1, i0:i1])
        return out

    # ------------------------------------------------------- link clearance
    def set_tool(self, tool_r, corner_r=0.0):
        self._tool_r = tool_r

    def refresh_tool(self):
        pass

    def link_clear(self, pts, h, eps=0.05):
        """True if the tool can traverse the polyline (list of (x, y)) with
        its tip at Z = h without touching stock: every cell whose centre is
        within tool radius of the true link line must have stock height
        <= h + eps (same cell-centre footprint convention as mill_segment)."""
        top = self.top
        c = self.cell
        r = self._tool_r
        k = int(math.ceil(r / c)) + 1
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            i0 = max(self._ci(min(xa, xb)) - k, 0)
            i1 = min(self._ci(max(xa, xb)) + k + 1, self.nx)
            j0 = max(self._cj(min(ya, yb)) - k, 0)
            j1 = min(self._cj(max(ya, yb)) + k + 1, self.ny)
            if i0 >= i1 or j0 >= j1:
                return False  # link leaves the tracked grid
            xs = self.x0 + (np.arange(i0, i1) + 0.5) * c
            ys = self.y0 + (np.arange(j0, j1) + 0.5) * c
            X, Y = np.meshgrid(xs, ys)
            abx, aby = xb - xa, yb - ya
            L2 = abx * abx + aby * aby
            if L2 < 1e-12:
                t = np.zeros_like(X)
            else:
                t = np.clip(((X - xa) * abx + (Y - ya) * aby) / L2, 0.0, 1.0)
            dx = X - (xa + t * abx)
            dy = Y - (ya + t * aby)
            near = (dx * dx + dy * dy) <= r * r
            if (top[j0:j1, i0:i1][near] > h + eps).any():
                return False
        return True

    def rise_clear(self, x, y, z_from, z_to, eps=0.05):
        """True if the tool can move vertically from z_from to z_to (> ) at
        (x, y): the cell it occupies must be at/below its current tip."""
        if z_to <= z_from:
            return True
        return self.top_at(x, y) <= z_from + eps

    def link_top_max(self, pts, r):
        """Highest tracked material Z - max(stock top, part surface) - at
        cell centres within r of the polyline (list of (x, y)). -inf when no
        material is under the path. Used by roughing to verify rapids/lifts
        against the LIVE stock model (Task R5)."""
        top = self.top
        if self.part is not None:
            top = np.maximum(top, self.part)
        c = self.cell
        k = int(math.ceil(r / c)) + 1
        mx = -np.inf
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            i0 = max(self._ci(min(xa, xb)) - k, 0)
            i1 = min(self._ci(max(xa, xb)) + k + 1, self.nx)
            j0 = max(self._cj(min(ya, yb)) - k, 0)
            j1 = min(self._cj(max(ya, yb)) + k + 1, self.ny)
            if i0 >= i1 or j0 >= j1:
                continue  # segment outside the tracked grid: nothing to see
            xs = self.x0 + (np.arange(i0, i1) + 0.5) * c
            ys = self.y0 + (np.arange(j0, j1) + 0.5) * c
            X, Y = np.meshgrid(xs, ys)
            abx, aby = xb - xa, yb - ya
            L2 = abx * abx + aby * aby
            if L2 < 1e-12:
                t = np.zeros_like(X)
            else:
                t = np.clip(((X - xa) * abx + (Y - ya) * aby) / L2, 0.0, 1.0)
            dx = X - (xa + t * abx)
            dy = Y - (ya + t * aby)
            near = (dx * dx + dy * dy) <= r * r
            if near.any():
                mx = max(mx, float(top[j0:j1, i0:i1][near].max()))
        return mx

    # ------------------------------------------------------------- contours
    def contours(self, mask, min_perimeter=4.0, simplify_eps=0.25):
        """Marching squares on the cell-centre grid -> closed loops in world
        coords. Returns (outers, holes): outers CCW (positive signed area),
        holes CW, both simplified and rounded."""
        m = mask.astype(np.int8)
        v00 = m[:-1, :-1]
        v01 = m[:-1, 1:]
        v11 = m[1:, 1:]
        v10 = m[1:, :-1]
        case = (v00 | (v01 << 1) | (v11 << 2) | (v10 << 3)).ravel()
        rr, cc = np.divmod(np.arange(case.size), mask.shape[1] - 1)
        # edge midpoints in half-index space: T=(2r,2c+1) R=(2r+1,2c+2)
        # B=(2r+2,2c+1) L=(2r+1,2c); segment table per marching-squares case
        T = lambda r, c: (2 * r, 2 * c + 1)
        R = lambda r, c: (2 * r + 1, 2 * c + 2)
        B = lambda r, c: (2 * r + 2, 2 * c + 1)
        L = lambda r, c: (2 * r + 1, 2 * c)
        # crossing edges: top v00!=v01, right v01!=v11, bottom v11!=v10,
        # left v00!=v10
        table = {1: [(T, L)], 2: [(T, R)], 3: [(L, R)], 4: [(B, R)],
                 5: [(T, L), (R, B)], 6: [(T, B)], 7: [(L, B)], 8: [(L, B)],
                 9: [(T, B)], 10: [(T, R), (L, B)], 11: [(R, B)],
                 12: [(L, R)], 13: [(T, R)], 14: [(T, L)]}
        adj = {}

        def add(p, q):
            adj.setdefault(p, []).append(q)
            adj.setdefault(q, []).append(p)

        for cs, pairs in table.items():
            sel = np.nonzero(case == cs)[0]
            for s in sel:
                r, c = int(rr[s]), int(cc[s])
                for (f1, f2) in pairs:
                    add(f1(r, c), f2(r, c))

        loops = []
        for p in list(adj):
            while adj.get(p):
                q = adj[p].pop()
                if adj.get(q):
                    adj[q].remove(p)
                loop = [p, q]
                while q != p:
                    nxt = adj[q].pop() if adj.get(q) else None
                    if nxt is None:
                        break
                    if adj.get(nxt):
                        adj[nxt].remove(q)
                    loop.append(nxt)
                    q = nxt
                if len(loop) >= 4 and loop[0] == loop[-1]:
                    loops.append(loop[:-1])

        c2 = self.cell * 0.5
        raw = []
        for loop in loops:
            pts = [(self.x0 + (hc + 1) * c2, self.y0 + (hr + 1) * c2)
                   for (hr, hc) in loop]
            pts = _rdp(pts, simplify_eps)
            if len(pts) < 3:
                continue
            per = sum(math.dist(pts[i], pts[(i + 1) % len(pts)])
                     for i in range(len(pts)))
            if per < min_perimeter:
                continue
            raw.append(pts)

        def pip(x, y, poly):
            inside = False
            n = len(poly)
            for i in range(n):
                x1, y1 = poly[i]
                x2, y2 = poly[(i + 1) % n]
                if (y1 > y) != (y2 > y):
                    xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                    if xint > x:
                        inside = not inside
            return inside

        outers, holes = [], []
        for i, pts in enumerate(raw):
            depth = sum(1 for j, other in enumerate(raw)
                        if j != i and pip(pts[0][0], pts[0][1], other))
            area2 = sum(pts[k][0] * pts[(k + 1) % len(pts)][1] -
                        pts[(k + 1) % len(pts)][0] * pts[k][1]
                        for k in range(len(pts)))
            if depth % 2 == 0:  # outer boundary -> CCW
                lp = pts if area2 > 0 else pts[::-1]
                outers.append(lp)
            else:  # hole -> CW
                lp = pts if area2 < 0 else pts[::-1]
                holes.append(lp)
        return ([round_xy(l) for l in outers], [round_xy(l) for l in holes])


def round_xy(loop):
    return [[round(x, 4), round(y, 4)] for (x, y) in loop]


def _rdp(pts, eps):
    """Ramer-Douglas-Peucker simplification of a closed polyline (list of
    (x, y)); keeps the loop closed-safe (first point re-appears at end)."""
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        worst, widx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L2 == 0.0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > worst:
                worst, widx = d, i
        if worst > eps:
            keep[widx] = True
            stack.append((a, widx))
            stack.append((widx, b))
    return [p for p, k in zip(pts, keep) if k]
