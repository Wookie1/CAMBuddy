#!/usr/bin/env python3
"""Independent toolpath checker: simulate a 2.5D toolpath against a part
heightfield and report gouges, leftover stock, rapid collisions and air time.

Plain Python 3 + numpy. No FreeCAD imports.
"""
import argparse
import json
import math
import os
import re
import sys

import numpy as np

WORD_RE = re.compile(r"([A-Za-z])\s*([-+]?[0-9]*\.?[0-9]+)")
GOUGE_TOL = 0.02  # mm below part surface before a cell counts as gouged
REMOVE_EPS = 1e-9  # mm^3 of removal below which a sample counts as air
RAPID_FEED = 15000.0  # mm/min assumed for G0 when estimating cycle time


# --------------------------------------------------------------------------
# G-code parsing
# --------------------------------------------------------------------------

def strip_comments(line):
    """Remove ( ... ) comments and ; to end of line."""
    out = []
    depth = 0
    for ch in line:
        if ch == ";":
            break
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def parse_gcode(text):
    """Parse G-code into a list of moves (absolute, mm where units known).

    Each move is a dict:
      line   : 1-based source line number
      motion : 'G0' | 'G1' | 'G2' | 'G3'
      x, y, z: target coordinates (may be None -> modal / unchanged)
      i, j, k: arc center offsets from start along X, Y, Z (arcs only)
      plane  : active motion plane at this move: 17=XY (I,J), 18=ZX (I,K),
               19=YZ (J,K) — set by G17/G18/G19
      comp   : cutter compensation state: 0 off, 1 = G41 (left), 2 = G42
               (right). A G40 line cancels, so the cancelling move itself
               carries comp=0 (as programmed).
      dreg   : D register number on this line (cutter comp), else None
      f      : feed in mm/min (modal; only set on lines carrying an F word)
    """
    moves = []
    units = 1.0
    modal = "G1"
    absolute = True
    feed = None
    g53 = False
    plane = 17  # 17=XY(I,J), 18=ZX(I,K), 19=YZ(J,K)
    comp = 0    # 0 off, 1 G41 left, 2 G42 right
    for lineno, raw in enumerate(text.splitlines(), 1):
        s = strip_comments(raw)
        words = WORD_RE.findall(s)
        if not words:
            continue
        params = {}
        gcodes = []
        dreg = None
        for letter, num in words:
            try:
                val = float(num)
            except ValueError:
                continue
            L = letter.upper()
            if L == "G":
                gcodes.append(val)
            elif L in ("X", "Y", "Z", "I", "J", "K"):
                params[L] = val
            elif L == "F":
                params[L] = val
            elif L == "D":
                dreg = int(round(val))
        for g in gcodes:
            if g == 20:
                units = 25.4
            elif g == 21:
                units = 1.0
            elif g in (17, 18, 19):
                plane = int(g)
            elif g == 41:
                comp = 1
            elif g == 42:
                comp = 2
            elif g == 40:
                comp = 0
            elif g == 53:
                g53 = True  # machine-coordinate rapid: outside the WCS
            elif g == 90:
                absolute = True
            elif g == 91:
                absolute = False
            elif g in (0.0, 1.0, 2.0, 3.0):
                modal = "G%d" % g
        if "F" in params:
            feed = params["F"] * units  # mm/min
        if g53:
            # G53 moves reference the machine origin, not the WCS the part
            # heightfield lives in (e.g. home retracts) -> ignore for sim.
            g53 = False
            continue
        has_xyz = any(k in params for k in ("X", "Y", "Z"))
        has_center = modal in ("G2", "G3") and any(k in params
                                                  for k in ("I", "J", "K"))
        if not has_xyz and not has_center:
            continue  # plane/unit/modal-only lines (e.g. bare G17) are not moves
        move = {"line": lineno, "motion": modal, "plane": plane, "comp": comp}
        for k in ("X", "Y", "Z"):
            move[k.lower()] = params[k] * units if k in params else None
        if modal in ("G2", "G3"):
            # I/J/K are center offsets from the start along X/Y/Z; which pair
            # is meaningful depends on the active plane (see PLANE_AXES).
            for k in ("I", "J", "K"):
                move[k.lower()] = params[k] * units if k in params else 0.0
        if comp and dreg is not None:
            move["dreg"] = dreg
        move["f"] = feed
        move["units"] = units  # lets parallel chunks stay unit-correct
        moves.append(move)
    return moves


# --------------------------------------------------------------------------
# Tool profiles
# --------------------------------------------------------------------------

def tool_dz(tool, dia, corner):
    """Return f(d) -> height of tool surface above the tip at radial dist d."""
    R = dia / 2.0
    if tool == "flat":
        def dz(d):
            return np.zeros_like(np.asarray(d, dtype=float))
    elif tool == "ball":
        def dz(d):
            d = np.asarray(d, dtype=float)
            return R - np.sqrt(np.maximum(R * R - d * d, 0.0))
    elif tool == "bull":
        a = R - corner

        def dz(d):
            d = np.asarray(d, dtype=float)
            t = np.maximum(d - a, 0.0)
            return np.where(d <= a, 0.0, corner - np.sqrt(np.maximum(corner * corner - t * t, 0.0)))
    else:
        raise ValueError("unknown tool type %r" % tool)
    return dz


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

# In-plane axis order per motion plane: (a1, a2, normal) with (a1, a2, normal)
# right-handed, so G03 sweeps from a1 toward a2 about +normal (CCW viewed
# from the positive normal axis) and G02 sweeps the other way.
# G17 = XY (normal +Z), G18 = ZX (normal +Y), G19 = YZ (normal +X).
PLANE_AXES = {17: (0, 1, 2), 18: (2, 0, 1), 19: (1, 2, 0)}


def _arc_geom(start, end, ijk, plane, ccw):
    """Resolve an arc in its plane. start/end/ijk are (x, y, z) mm tuples.
    Returns (center3d, a1, a2, n, R, a0, sweep) or None if degenerate."""
    a1, a2, n = PLANE_AXES.get(plane, PLANE_AXES[17])
    center = (start[0] + ijk[0], start[1] + ijk[1], start[2] + ijk[2])
    u0, v0 = start[a1] - center[a1], start[a2] - center[a2]
    u1, v1 = end[a1] - center[a1], end[a2] - center[a2]
    R0 = math.hypot(u0, v0)
    R1 = math.hypot(u1, v1)
    if R0 <= 1e-12 and R1 <= 1e-12:
        return None
    R = 0.5 * (R0 + R1)
    if R <= 1e-12:
        return None
    a0 = math.atan2(v0, u0)
    a1a = math.atan2(v1, u1)
    sweep = a1a - a0
    if ccw:
        sweep = sweep % (2 * math.pi)
    else:
        sweep = (sweep + 2 * math.pi) % (2 * math.pi) - 2 * math.pi
    if abs(sweep) < 1e-12 and R > 1e-9:
        sweep = 2 * math.pi if ccw else -2 * math.pi  # full circle
    return (center, a1, a2, n, R, a0, sweep)


def _move_samples(mv, cur, cell):
    """Sample a resolved move (x0,y0,z0)->(x1,y1,z1) at <= cell/4 spacing.

    Arcs are interpolated in their active plane (G17 XY, G18 ZX, G19 YZ);
    travel along the plane normal (helical Z/Y/X) is linear.
    Returns (samples, length): list of (x, y, z) and total path length.
    """
    x0, y0, z0 = cur
    x1, y1, z1 = mv["x"], mv["y"], mv["z"]
    step = cell / 4.0
    if mv["motion"] in ("G2", "G3") and mv.get("arc"):
        center, a1, a2, n, R, a0, sweep = mv["arc"]
        if R <= 0 or abs(sweep) <= 0:
            return [(x1, y1, z1)], 0.0
        delta = (x1 - x0, y1 - y0, z1 - z0)
        length = math.hypot(abs(sweep) * R, delta[n])  # helical approx
        m = max(2, int(math.ceil(length / step)))
        samples = []
        for t in np.linspace(0.0, 1.0, m + 1):
            a = a0 + sweep * t
            p = list(center)
            p[a1] += R * math.cos(a)
            p[a2] += R * math.sin(a)
            p[n] = (x0, y0, z0)[n] + delta[n] * t
            samples.append((p[0], p[1], p[2]))
        return samples, length
    dx, dy, dzv = x1 - x0, y1 - y0, z1 - z0
    length = math.sqrt(dx * dx + dy * dy + dzv * dzv)
    if length <= 0:
        return [(x1, y1, z1)], 0.0
    n = max(2, int(math.ceil(length / step)))
    ts = np.linspace(0.0, 1.0, n + 1)
    samples = [(x0 + dx * t, y0 + dy * t, z0 + dzv * t) for t in ts]
    return samples, length


def _resolve_arcs(moves, x_init=0.0, y_init=0.0, z_init=0.0):
    """Fill modal x/y/z and attach arc geometry (plane-aware) to G2/G3 moves."""
    out = []
    cx, cy, cz = x_init, y_init, z_init
    for mv in moves:
        m = dict(mv)
        x = mv.get("x")
        y = mv.get("y")
        z = mv.get("z")
        x = cx if x is None else x
        y = cy if y is None else y
        z = cz if z is None else z
        m["x"], m["y"], m["z"] = x, y, z
        if mv["motion"] in ("G2", "G3"):
            g = _arc_geom((cx, cy, cz), (x, y, z),
                         (mv.get("i", 0.0), mv.get("j", 0.0),
                          mv.get("k", 0.0)),
                         mv.get("plane", 17), mv["motion"] == "G3")
            if g is not None:
                m["arc"] = g
        out.append(m)
        cx, cy, cz = x, y, z
    return out


def steep_window(part, cell, radius=2.0, dz_thresh=1.0):
    """Boolean mask: cells within `radius` mm of a steep wall of the part.

    A cell is steep if |dZ| > dz_thresh between it and any 4-neighbour.
    The steep seed set is dilated by ceil(radius/cell) cells (chebyshev,
    i.e. slightly over-dilated diagonally).
    """
    ny, nx = part.shape
    steep = np.zeros((ny, nx), dtype=bool)
    d = np.abs(np.diff(part, axis=0, prepend=part[:1, :]))
    steep |= d > dz_thresh
    d = np.abs(np.diff(part, axis=1, prepend=part[:, :1]))
    steep |= d > dz_thresh
    k = int(math.ceil(radius / cell))
    win = steep.copy()
    for _ in range(k):
        w = win.copy()
        w[1:, :] |= win[:-1, :]
        w[:-1, :] |= win[1:, :]
        w[:, 1:] |= win[:, :-1]
        w[:, :-1] |= win[:, 1:]
        win = w
    return win


def resolve_moves(moves, x_init=0.0, y_init=0.0, z_init=0.0):
    """Resolve modal coordinates and arc geometry for a move list.

    Returns dicts with explicit x/y/z (mm), arc tuples where applicable, and
    the move's feed. Do this once on the FULL list before chunking so chunk
    starts inherit the correct position and feed. Moves already carrying
    resolved=True (e.g. output of apply_cutter_comp) keep their arc geometry.
    """
    out = []
    cx, cy, cz = x_init, y_init, z_init
    feed = None
    for mv in moves:
        m = dict(mv)
        m["x"] = x = mv["x"] if mv.get("x") is not None else cx
        m["y"] = y = mv["y"] if mv.get("y") is not None else cy
        m["z"] = z = mv["z"] if mv.get("z") is not None else cz
        if mv.get("f") is not None:
            feed = mv["f"]
        m["f"] = feed
        m["resolved"] = True
        if mv["motion"] in ("G2", "G3") and not mv.get("arc"):
            g = _arc_geom((cx, cy, cz), (x, y, z),
                         (mv.get("i", 0.0), mv.get("j", 0.0),
                          mv.get("k", 0.0)),
                         mv.get("plane", 17), mv["motion"] == "G3")
            if g is not None:
                m["arc"] = g
        out.append(m)
        cx, cy, cz = x, y, z
    return out


# --------------------------------------------------------------------------
# Cutter radius compensation (G41/G42) — optional pre-offset
# --------------------------------------------------------------------------
# Default zmap behaviour is Fusion "wear" compensation: the programmed path is
# simulated as the tool centre and comp-active moves are only counted/reported,
# because the D register value is not in the file. --comp-radius>0 instead
# pre-offsets each G41/G42 section by the given radius (registry-style
# compensation): lines offset perpendicular to travel, XY arcs offset
# concentrically, consecutive elements joined at their curve intersection
# (miter) where one exists, otherwise linked with a straight feed move. The
# activation move is offset; the G40-cancel move runs as programmed. This
# approximates but does not reproduce exact ISO lead-in/out arcs.

def _offset_line(p, q, sgn, r):
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = math.hypot(dx, dy)
    if L <= 1e-12:
        return None
    return ((p[0] + sgn * r * (-dy / L), p[1] + sgn * r * (dx / L)),
            (q[0] + sgn * r * (-dy / L), q[1] + sgn * r * (dx / L)))


def _line_line_int(p1, p2, p3, p4):
    """Intersection of lines p1-p2 and p3-p4, or None (parallel/shallow)."""
    d1 = (p2[0] - p1[0], p2[1] - p1[1])
    d2 = (p4[0] - p3[0], p4[1] - p3[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    n1 = math.hypot(*d1)
    n2 = math.hypot(*d2)
    if n1 <= 1e-12 or n2 <= 1e-12 or abs(den) < 0.1 * n1 * n2:
        return None  # parallel or shallow angle: link instead of long miter
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def _line_circle_int(p1, p2, c, R):
    """Intersections of the infinite line p1-p2 with circle (c, R)."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    L = math.hypot(dx, dy)
    if L <= 1e-12:
        return []
    ux, uy = dx / L, dy / L
    fx, fy = c[0] - p1[0], c[1] - p1[1]
    tca = fx * ux + fy * uy
    d2 = fx * fx + fy * fy - tca * tca
    r2 = R * R
    if d2 > r2:
        return []
    tht = math.sqrt(max(r2 - d2, 0.0))
    return [(p1[0] + (tca - tht) * ux, p1[1] + (tca - tht) * uy),
            (p1[0] + (tca + tht) * ux, p1[1] + (tca + tht) * uy)]


def _on_arc(c, R, a0, sweep, p):
    """True if point p lies (angularly) within the arc's sweep."""
    a = math.atan2(p[1] - c[1], p[0] - c[0])
    rel = (a - a0) if sweep >= 0 else (a0 - a)
    rel = rel % (2 * math.pi)
    return rel <= abs(sweep) + 1e-9


def _elem_point(e, at_end):
    if e["kind"] == "line":
        return e["q"] if at_end else e["p"]
    a = e["a0"] + (e["sweep"] if at_end else 0.0)
    return (e["c"][0] + e["R"] * math.cos(a), e["c"][1] + e["R"] * math.sin(a))


def _join_point(e1, e2, nominal):
    """Miter intersection of two offset elements near `nominal`, or None.
    Arc-arc joins fall back to linking (rare for compensated contours)."""
    cands = []
    if e1["kind"] == "line" and e2["kind"] == "line":
        p = _line_line_int(e1["p"], e1["q"], e2["p"], e2["q"])
        if p:
            cands.append(p)
    elif e1["kind"] == "line" or e2["kind"] == "line":
        if e1["kind"] == "line":
            line, arc = (e1["p"], e1["q"]), e2
        else:
            line, arc = (e2["p"], e2["q"]), e1
        for p in _line_circle_int(line[0], line[1], arc["c"], arc["R"]):
            if _on_arc(arc["c"], arc["R"], arc["a0"], arc["sweep"], p):
                cands.append(p)
    if not cands:
        return None
    return min(cands, key=lambda p: math.hypot(p[0] - nominal[0],
                                              p[1] - nominal[1]))


def _set_elem_end(e, p):
    if e["kind"] == "line":
        e["q"] = p
    else:
        a = math.atan2(p[1] - e["c"][1], p[0] - e["c"][0])
        sweep = a - e["a0"]
        if e["sweep"] >= 0:
            sweep = sweep % (2 * math.pi)
        else:
            sweep = (sweep + 2 * math.pi) % (2 * math.pi) - 2 * math.pi
        e["sweep"] = sweep


def _set_elem_start(e, p):
    if e["kind"] == "line":
        e["p"] = p
    else:
        a = math.atan2(p[1] - e["c"][1], p[0] - e["c"][0])
        sweep = (e["a0"] + e["sweep"]) - a
        if e["sweep"] >= 0:
            sweep = sweep % (2 * math.pi)
        else:
            sweep = (sweep + 2 * math.pi) % (2 * math.pi) - 2 * math.pi
        e["a0"] = a
        e["sweep"] = sweep


def _emit_elem(e, src):
    m = {"line": src["line"], "motion": src["motion"], "plane": 17,
         "comp": src.get("comp", 0), "f": src.get("f"),
         "units": src.get("units", 1.0), "resolved": True,
         "z": e["z1"], "comp_offset": True}
    if e["kind"] == "line":
        m["motion"] = "G1"
        m["x"], m["y"] = e["q"]
    else:
        p_end = _elem_point(e, True)
        m["x"], m["y"] = p_end
        m["arc"] = ((e["c"][0], e["c"][1], e["z0"]), 0, 1, 2, e["R"],
                    e["a0"], e["sweep"])
    return m


def apply_cutter_comp(moves, radius):
    """Pre-offset G41/G42-compensated sections of a RESOLVED move list by
    `radius` mm (registry-style compensation). The activation block (the G1
    carrying G41/G42) and the G40-cancel block run as programmed — matching
    Fusion-posted NC where the activation move is an explicit lead to a safe
    point; elements between them are offset perpendicular (lines) or
    concentrically (XY arcs), joined at curve intersections (miter) where one
    exists, otherwise linked with straight feed moves. Approximates but does
    not reproduce exact ISO lead-in/out arcs."""
    if radius <= 0:
        return moves

    def nominal_start(k):
        prev = moves[k - 1] if k > 0 else None
        return (prev["x"], prev["y"]) if prev is not None \
            else (moves[k]["x"], moves[k]["y"])

    def link_move(src, p_from, p_to, z):
        return {"line": src["line"], "motion": "G1", "plane": 17,
                "comp": src.get("comp", 0), "f": src.get("f"),
                "units": src.get("units", 1.0), "resolved": True,
                "comp_offset": True,
                "x": p_to[0], "y": p_to[1], "z": z}

    out = []
    i, n = 0, len(moves)
    while i < n:
        mv = moves[i]
        if not mv.get("comp") or mv["motion"] == "G0":
            out.append(mv)
            i += 1
            continue
        sgn = 1.0 if mv.get("comp") == 1 else -1.0
        j = i
        while j < n and moves[j].get("comp") and moves[j]["motion"] != "G0":
            j += 1
        # build offset elements; the activation move (first of section) stays
        # as programmed — compensation applies from the following element on
        chain = []
        prev_z = moves[i - 1]["z"] if i > 0 else mv.get("z", 0.0)
        for k in range(i, j):
            m = moves[k]
            z0, z1 = prev_z, m.get("z", prev_z)
            prev_z = z1
            if k == i:
                chain.append({"kind": "raw", "src": m})
            elif m["motion"] in ("G2", "G3") and m.get("arc") \
                    and m.get("plane", 17) == 17:
                _c, a1, a2, _nn, R, a0, sweep = m["arc"]
                Rp = R - radius if sweep * sgn > 0 else R + radius
                if Rp > 1e-9:
                    chain.append({"kind": "arc", "c": (_c[0], _c[1]),
                                "R": Rp, "a0": a0, "sweep": sweep,
                                "z0": z0, "z1": z1, "src": m})
                else:  # radius collapse: keep this element uncompensated
                    chain.append({"kind": "raw", "src": m})
            elif m["motion"] == "G1":
                off = _offset_line(nominal_start(k), (m["x"], m["y"]),
                                  sgn, radius)
                if off is None:
                    chain.append({"kind": "raw", "src": m})
                else:
                    chain.append({"kind": "line", "p": off[0], "q": off[1],
                                "z0": z0, "z1": z1, "src": m})
            else:
                chain.append({"kind": "raw", "src": m})
        # emit, inserting entry/exit links and miter joins
        prev_pt = None   # (x, y) after last emitted move
        prev_comp = False
        for k, e in enumerate(chain):
            if e["kind"] == "raw":
                src = e["src"]
                if prev_pt is not None and prev_comp:
                    d = math.hypot(src["x"] - prev_pt[0], src["y"] - prev_pt[1])
                    if d > 1e-9:
                        out.append(link_move(src, prev_pt, (src["x"], src["y"]),
                                           e["z0"]))
                out.append(dict(src, resolved=True))
                prev_pt = (src["x"], src["y"])
                prev_comp = False
                continue
            if prev_pt is not None and not prev_comp:
                sp = _elem_point(e, False)
                if math.hypot(sp[0] - prev_pt[0], sp[1] - prev_pt[1]) > 1e-9:
                    out.append(link_move(e["src"], prev_pt, sp, e["z0"]))
            joined = False
            if k + 1 < len(chain) and chain[k + 1]["kind"] != "raw":
                jp = _join_point(e, chain[k + 1], _elem_point(e, True))
                if jp is not None:
                    _set_elem_end(e, jp)
                    _set_elem_start(chain[k + 1], jp)
                    joined = True
            out.append(_emit_elem(e, e["src"]))
            prev_pt = _elem_point(e, True)
            prev_comp = True
            if not joined and k + 1 < len(chain) \
                    and chain[k + 1]["kind"] != "raw":
                nxt = _elem_point(chain[k + 1], False)
                if math.hypot(nxt[0] - prev_pt[0], nxt[1] - prev_pt[1]) > 1e-9:
                    out.append(link_move(e["src"], prev_pt, nxt,
                                       chain[k + 1]["z0"]))
                    prev_pt = nxt
        i = j
    return out


def simulate(moves, part, cell, x0, y0, stock_box, tool="flat", dia=6.0,
             corner=0.0, stock_init=None, window=None, rapid_feed=RAPID_FEED):
    """Run the toolpath over a stock heightfield.

    part      : (ny, nx) array of part top-Z heights
    cell,x0,y0: grid geometry (cell center of [j, i] is x0+(i+.5)*cell, ...)
    stock_box : (xmin, xmax, ymin, ymax, zmin, zmax)
    stock_init: optional (ny, nx) array; starting stock heights (e.g. the
                'stock' output of a previous op via --stock-out) so multiple
                toolpaths can be chained. Cells outside stock_box are still
                set to -inf. Default: start from the stock box top.
    window    : optional (ny, nx) bool mask; when given, only cells inside the
                window are cut/collided/evaluated (focused sims near steep
                walls); everything outside is treated as -inf.
    rapid_feed: assumed G0 feed (mm/min) for the cycle-time estimate.
    Returns dict with 'stock' array and report fields.
    """
    sxmin, sxmax, symin, symax, szmin, szmax = stock_box
    ny, nx = part.shape
    if stock_init is not None:
        stock = np.array(stock_init, dtype=float)
        if stock.shape != (ny, nx):
            raise ValueError("stock_init shape %r does not match part grid %r"
                             % (stock.shape, (ny, nx)))
    else:
        stock = np.full((ny, nx), float(szmax))
    ii = np.arange(nx)
    jj = np.arange(ny)
    xs = x0 + (ii + 0.5) * cell
    ys = y0 + (jj + 0.5) * cell
    in_box = ((xs >= sxmin) & (xs <= sxmax))[None, :] & \
             ((ys >= symin) & (ys <= symax))[:, None]
    stock[~in_box] = -np.inf
    if window is not None:
        if window.shape != (ny, nx):
            raise ValueError("window shape %r does not match part grid %r"
                            % (window.shape, (ny, nx)))
        stock[~window] = -np.inf
    R = dia / 2.0
    dz = tool_dz(tool, dia, corner)
    k = int(math.ceil(R / cell)) + 1  # +1 so the padded engagement mask fits

    if window is not None:
        # samples only matter within tool reach of the window; dilate once so
        # the per-sample skip is a single mask lookup
        near = window.copy()
        for _ in range(k):
            w = near.copy()
            w[1:, :] |= near[:-1, :]
            w[:-1, :] |= near[1:, :]
            w[:, 1:] |= near[:, :-1]
            w[:, :-1] |= near[:, 1:]
            near = w
    else:
        near = None

    if moves and "z" in moves[0] and moves[0].get("resolved"):
        resolved = moves
    else:
        fz_init = next((m["z"] for m in moves if m.get("z") is not None),
                      float(szmax))
        resolved = _resolve_arcs(moves, *next(((m["x"], m["y"]) for m in moves
                                              if m.get("x") is not None
                                              or m.get("y") is not None),
                                             (0.0, 0.0)), fz_init)
    if resolved:
        first_xy = next(((m["x"], m["y"]) for m in resolved
                         if m["x"] is not None and m["y"] is not None),
                        (0.0, 0.0))
        fz = next((m["z"] for m in resolved if m.get("z") is not None),
                  float(szmax))
        cur = [first_xy[0], first_xy[1], fz]
    else:
        cur = [0.0, 0.0, float(szmax)]
    rapid_collisions = 0
    first_rapid_line = None
    cut_length = 0.0
    rapid_length = 0.0
    air_length = 0.0
    cycle_s = 0.0
    comp_moves = 0
    comp_first_line = None
    comp_last_line = None
    d_registers = set()

    for mv in resolved:
        if mv.get("comp"):
            comp_moves += 1
            if comp_first_line is None:
                comp_first_line = mv["line"]
            comp_last_line = mv["line"]
            if mv.get("dreg") is not None:
                d_registers.add(mv["dreg"])
        x1 = mv["x"] if mv["x"] is not None else cur[0]
        y1 = mv["y"] if mv["y"] is not None else cur[1]
        z1 = mv["z"] if mv["z"] is not None else cur[2]
        if mv["motion"] in ("G2", "G3") and (mv["x"] is None or mv["y"] is None):
            continue  # arc without a resolvable endpoint
        m = dict(mv)
        m["x"], m["y"], m["z"] = x1, y1, z1
        samples, length = _move_samples(m, cur, cell)
        cutting = mv["motion"] in ("G1", "G2", "G3")
        move_collided = False
        seg_len = length / max(1, len(samples))
        for (sx, sy, sz) in samples:
            if near is not None:
                ix = int(math.floor((sx - x0) / cell))
                jy = int(math.floor((sy - y0) / cell))
                if ix < 0 or jy < 0 or ix >= nx or jy >= ny \
                        or not near[jy, ix]:
                    if cutting:  # cannot touch any window cell -> air
                        air_length += seg_len
                    continue
            i0 = int(math.floor((sx - x0) / cell))
            j0 = int(math.floor((sy - y0) / cell))
            ilo, ihi = max(0, i0 - k), min(nx, i0 + k + 1)
            jlo, jhi = max(0, j0 - k), min(ny, j0 + k + 1)
            if ilo >= ihi or jlo >= jhi:
                continue
            gx = xs[ilo:ihi] - sx
            gy = ys[jlo:jhi] - sy
            win = stock[jlo:jhi, ilo:ihi]
            # no cell in reach is above the tool tip -> nothing to cut here
            if float(win.max()) <= sz + 1e-6:
                if cutting:
                    air_length += seg_len
                continue
            dxg, dyg = np.meshgrid(gx, gy)
            d = np.hypot(dxg, dyg)
            msk = d <= R + 1e-9
            if window is not None:
                msk &= window[jlo:jhi, ilo:ihi]
            if not msk.any():
                continue
            newv = np.where(msk, sz + dz(d), np.inf)
            cut = win - newv
            removed = float(np.sum(np.clip(np.where(msk, cut, 0.0), 0.0, None)))
            if cutting:
                # engaged = any stock cell at/over the footprint edge above the
                # tip. The radius is padded by half a cell diagonal so that
                # slivers of cells clipped by the disk edge still count (the
                # cell-center mask alone would report false air while cutting).
                msk_e = d <= R + 0.75 * cell
                if window is not None:
                    msk_e &= window[jlo:jhi, ilo:ihi]
                engaged = (msk_e.any() and
                         float(np.max(np.where(msk_e, win, -np.inf))) > sz + 1e-6)
            if removed > REMOVE_EPS:
                stock[jlo:jhi, ilo:ihi] = np.minimum(win, newv)
            if cutting and not engaged:
                air_length += seg_len
            else:  # rapid
                if np.any(np.where(msk, cut > REMOVE_EPS, False)):
                    move_collided = True
        if cutting:
            cut_length += length
            feed = mv.get("f")
            cycle_s += length / (feed if feed and feed > 0 else rapid_feed) * 60.0
        else:  # rapid
            rapid_length += length
            cycle_s += length / rapid_feed * 60.0
            if move_collided:
                rapid_collisions += 1
                if first_rapid_line is None:
                    first_rapid_line = mv["line"]
        cur = [x1, y1, z1]

    result = {
        "stock": stock,
        "rapid_collisions": {"count": rapid_collisions,
                            "first_line": first_rapid_line},
        "air_fraction": (air_length / cut_length) if cut_length > 0 else 0.0,
        "cutting_length_mm": cut_length,
        "rapid_length_mm": rapid_length,
        "cycle_time_s": cycle_s,
        "cutter_comp": {"active_moves": comp_moves,
                       "first_line": comp_first_line,
                       "last_line": comp_last_line,
                       "d_registers": sorted(d_registers)},
    }
    result.update(analyze(stock, part, cell, x0, y0,
                          restrict=window if window is not None else in_box))
    return result


# --------------------------------------------------------------------------
# Parallel chunking
# --------------------------------------------------------------------------
# Stock updates are a running per-cell minimum, so splitting the (globally
# modal-resolved) move list and combining chunk stocks with an element-wise
# min is EXACT for the final heightfield and gouge/leftover stats. Only
# rapid-collision counts and air_fraction are approximate (a chunk cannot see
# stock removed by earlier chunks); the chunked report flags this.

_CHUNK = {}


def _chunk_worker(idx):
    g = _CHUNK
    return simulate(g["moves"][g["spans"][idx]], g["part"], g["cell"],
                    g["x0"], g["y0"],
                    g["stock_box"], tool=g["tool"], dia=g["dia"],
                    corner=g["corner"], stock_init=g["stock_init"],
                    window=g["window"], rapid_feed=g["rapid_feed"])


def simulate_parallel(moves, part, cell, x0, y0, stock_box, jobs, tool="flat",
                      dia=6.0, corner=0.0, stock_init=None, window=None,
                      rapid_feed=RAPID_FEED):
    import multiprocessing as mp
    moves = resolve_moves(moves)
    spans, n = [], len(moves)
    per = int(math.ceil(n / float(jobs)))
    for c in range(0, n, per):
        spans.append(slice(c, min(n, c + per)))
    _CHUNK.update(moves=moves, spans=spans, part=part, cell=cell, x0=x0,
                  y0=y0,
                  stock_box=stock_box, tool=tool, dia=dia, corner=corner,
                  stock_init=stock_init, window=window, rapid_feed=rapid_feed)
    ctx = mp.get_context("fork")
    with ctx.Pool(len(spans)) as pool:
        results = pool.map(_chunk_worker, range(len(spans)))
    combined = {
        "stock": np.min(np.stack([r["stock"] for r in results]), axis=0),
        "rapid_collisions": {
            "count": sum(r["rapid_collisions"]["count"] for r in results),
            "first_line": min((r["rapid_collisions"]["first_line"]
                              for r in results
                              if r["rapid_collisions"]["first_line"]),
                             default=None),
            "note": "counted per chunk; approximate under --jobs",
        },
        "air_fraction": 0.0,
        "cutting_length_mm": sum(r["cutting_length_mm"] for r in results),
        "rapid_length_mm": sum(r["rapid_length_mm"] for r in results),
        "cycle_time_s": sum(r["cycle_time_s"] for r in results),
    }
    cut = sum(r["cutting_length_mm"] for r in results)
    # recompute air from chunk air fractions (air = fraction * chunk cut len)
    air = sum(r["air_fraction"] * r["cutting_length_mm"] for r in results)
    combined["air_fraction"] = (air / cut) if cut > 0 else 0.0
    combined["cutter_comp"] = {
        "active_moves": sum(r["cutter_comp"]["active_moves"] for r in results),
        "first_line": min((r["cutter_comp"]["first_line"] for r in results
                          if r["cutter_comp"]["first_line"]), default=None),
        "last_line": max((r["cutter_comp"]["last_line"] for r in results
                         if r["cutter_comp"]["last_line"]), default=None),
        "d_registers": sorted({d for r in results
                              for d in r["cutter_comp"]["d_registers"]}),
    }
    combined.update(analyze(combined["stock"], part, cell, x0, y0,
                            restrict=window))
    return combined


# --------------------------------------------------------------------------
# Analysis / report
# --------------------------------------------------------------------------

def analyze(stock, part, cell, x0, y0, restrict=None):
    ny, nx = part.shape
    valid = np.isfinite(stock)
    bottom = float(np.min(part))
    footprint = part > bottom + 1e-9
    mask = valid & footprint
    if restrict is not None:
        mask &= restrict
    depth = part - stock
    gouge_mask = mask & (stock < part - GOUGE_TOL)
    if gouge_mask.any():
        flat = np.argmax(np.where(gouge_mask, depth, -np.inf))
        gj, gi = np.unravel_index(flat, part.shape)
        worst = [float(x0 + (gi + 0.5) * cell), float(y0 + (gj + 0.5) * cell)]
        max_depth = float(depth[gouge_mask].max())
    else:
        worst = None
        max_depth = 0.0
    if mask.any():
        leftover = (stock - part)[mask]
        lv = {
            "max": float(leftover.max()),
            "mean": float(leftover.mean()),
            "p95": float(np.percentile(leftover, 95)),
        }
        within = float(np.mean(np.abs(leftover) <= 0.5))
    else:
        lv = {"max": 0.0, "mean": 0.0, "p95": 0.0}
        within = 0.0
    return {
        "gouges": {"count": int(gouge_mask.sum()), "max_depth": max_depth,
                   "worst_xy": worst},
        "leftover": lv,
        "within_0p5mm_fraction": within,
    }


def write_png(stock, part, cell, x0, y0, path):
    """Heatmap of leftover stock. Returns True if written, False if skipped."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    with np.errstate(invalid="ignore"):
        data = np.where(np.isfinite(stock), stock - part, np.nan)
    fig, ax = plt.subplots(figsize=(8, 8))
    im = ax.imshow(data, origin="lower", cmap="viridis",
                   extent=[x0, x0 + data.shape[1] * cell,
                         y0, y0 + data.shape[0] * cell])
    fig.colorbar(im, ax=ax, label="leftover stock (mm)")
    ax.set_title("leftover stock")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_part(path):
    part = np.load(path)
    sidecar = re.sub(r"\.npy$", "", path) + ".json"
    with open(sidecar) as f:
        meta = json.load(f)
    return part, float(meta["cell"]), float(meta["x0"]), float(meta["y0"])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("gcode", help="input G-code file")
    p.add_argument("--part", required=True, help="part heightfield .npy "
                   "(with .json sidecar)")
    p.add_argument("--tool", choices=("flat", "ball", "bull"), default="flat")
    p.add_argument("--dia", type=float, default=6.0, help="tool diameter mm")
    p.add_argument("--corner", type=float, default=0.0,
                   help="bull-nose corner radius mm")
    p.add_argument("--stock", type=float, nargs=6, metavar=("XMIN", "XMAX",
                   "YMIN", "YMAX", "ZMIN", "ZMAX"), default=None,
                   help="stock bounding box mm (required unless --stock-in)")
    p.add_argument("--stock-in", dest="stock_in", default=None,
                  help="continue from a stock heightfield .npy saved by a "
                       "previous run's --stock-out (same grid as --part)")
    p.add_argument("--stock-out", dest="stock_out", default=None,
                  help="save the final stock heightfield to this .npy so a "
                       "later toolpath can continue via --stock-in")
    p.add_argument("--out-json", default=None, help="write report JSON here")
    p.add_argument("--png", default=None, help="optional leftover heatmap PNG")
    p.add_argument("--window", action="store_true",
                   help="only simulate/evaluate cells within 2 mm of steep "
                        "walls (|dZ| > 1 mm between part heightfield "
                        "neighbours); faster at fine cell sizes")
    p.add_argument("--rapid-feed", dest="rapid_feed", type=float,
                   default=RAPID_FEED,
                   help="assumed G0 feed mm/min for the cycle-time estimate")
    p.add_argument("--comp-radius", dest="comp_radius", type=float, default=0.0,
                  help="apply registry-style cutter radius compensation to "
                       "G41/G42 sections (pre-offset the path by this mm). "
                       "Default 0 = wear model: simulate as programmed and "
                       "only count/report comp-active moves")
    p.add_argument("--jobs", type=int, default=1,
                   help="parallel worker processes (exact for stock/stats; "
                        "rapid-collision counts become approximate)")
    args = p.parse_args(argv)

    if args.stock is None and not args.stock_in:
        p.error("--stock is required unless --stock-in provides the stock state")

    if args.tool == "ball" and abs(args.corner - args.dia / 2) > 1e-9:
        args.corner = args.dia / 2
    if args.tool == "bull" and not (0 < args.corner < args.dia / 2):
        p.error("--corner must satisfy 0 < corner < dia/2 for a bull nose")

    with open(args.gcode) as f:
        moves = parse_gcode(f.read())
    if args.comp_radius > 0:
        moves = apply_cutter_comp(resolve_moves(moves), args.comp_radius)
    part, cell, x0, y0 = load_part(args.part)
    window = steep_window(part, cell) if args.window else None

    stock_init = None
    if args.stock_in:
        stock_init = np.load(args.stock_in)
    if args.stock is not None:
        stock_box = tuple(args.stock)
    else:
        # Derive the box from the saved state's finite cells.
        jj, ii = np.where(np.isfinite(stock_init))
        if jj.size == 0:
            p.error("--stock-in file has no finite cells")
        stock_box = (x0 + ii.min() * cell, x0 + (ii.max() + 1) * cell,
                    y0 + jj.min() * cell, y0 + (jj.max() + 1) * cell,
                    float(np.nanmin(stock_init)),
                    float(np.nanmax(stock_init)))
    if args.jobs > 1:
        res = simulate_parallel(moves, part, cell, x0, y0, stock_box,
                               args.jobs, tool=args.tool, dia=args.dia,
                               corner=args.corner, stock_init=stock_init,
                               window=window, rapid_feed=args.rapid_feed)
    else:
        res = simulate(moves, part, cell, x0, y0, stock_box,
                       tool=args.tool, dia=args.dia, corner=args.corner,
                       stock_init=stock_init, window=window,
                       rapid_feed=args.rapid_feed)

    report = {
        "gcode": os.path.abspath(args.gcode),
        "part": os.path.abspath(args.part),
        "tool": {"type": args.tool, "dia": args.dia, "corner": args.corner},
        "stock_box": [float(v) for v in stock_box],
        "stock_in": os.path.abspath(args.stock_in) if args.stock_in else None,
        "cell": cell,
        "window": ("steep walls |dZ|>1mm dilated 2mm" if args.window else None),
        "gouges": res["gouges"],
        "leftover": res["leftover"],
        "within_0p5mm_fraction": res["within_0p5mm_fraction"],
        "rapid_collisions": res["rapid_collisions"],
        "cutter_comp": res["cutter_comp"],
        "comp_radius_mm": args.comp_radius,
        "air_fraction": res["air_fraction"],
        "cutting_length_mm": round(res["cutting_length_mm"], 1),
        "rapid_length_mm": round(res["rapid_length_mm"], 1),
        "cycle_time_s": round(res["cycle_time_s"], 1),
        "cycle_time_note": ("feed moves at their F words; rapids assumed at "
                           "%.0f mm/min" % args.rapid_feed),
    }
    text = json.dumps(report, indent=2)
    if args.out_json:
        with open(args.out_json, "w") as f:
            f.write(text + "\n")
    else:
        print(text)
    if args.stock_out:
        np.save(args.stock_out, res["stock"])
    if args.png:
        ok = write_png(res["stock"], part, cell, x0, y0, args.png)
        if not ok:
            print("PNG skipped (matplotlib unavailable)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
