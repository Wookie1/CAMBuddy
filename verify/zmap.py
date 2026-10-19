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
HOLDER_CLEAR = 1.0  # mm, S5: min clearance of the holder stack to material
TOOLS_JSON = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools", "x7_tools.json")


def resolve_holder(tool_number=None, holder=None, stickout=None, path=None):
    """S5: resolve a holder frustum stack + stick-out (independent of the
    engine: reads tools/x7_tools.json only). Explicit `holder` requires
    `stickout`; otherwise the tool table entry with "number" == tool_number
    supplies both ("holder" + "stickout_mm"). Segments are
    [z_lo, z_hi, r_lo, r_hi] mm above the holder nose (nose at tool tip +
    stick-out). Returns (segments, stickout_mm) or None when no holder
    geometry applies (no args, tool not in the table, or the entry has no
    holder/stick-out). Raises ValueError for an unknown holder name or a
    holder without any stick-out. Returns (segments, stickout_mm, name)."""
    if holder is None and tool_number is None:
        return None
    p = path or TOOLS_JSON
    try:
        with open(p) as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError):
        return None
    if holder is None:
        e = next((t for t in data.get("tools", [])
                  if t.get("number") == int(tool_number)), None)
        if e is None or not e.get("holder") or e.get("stickout_mm") is None:
            return None
        holder = e["holder"]
        if stickout is None:
            stickout = float(e["stickout_mm"])
        h = data.get("holders", {}).get(holder)
        if not isinstance(h, dict) or not h.get("segments"):
            return None  # table names a holder without geometry (e.g. the
                        # ER32 collet chuck): check off, not an error
    else:
        if stickout is None:
            raise ValueError("--holder %r given without --stickout" % holder)
        h = data.get("holders", {}).get(holder)
        if not isinstance(h, dict) or not h.get("segments"):
            raise ValueError("holder %r has no segments in %s" % (holder, p))
    return [[float(v) for v in s] for s in h["segments"]], float(stickout), \
        holder



def _holder_report(args, name, stickout):
    """Never skip silently: say which holder was checked, or that it is unknown."""
    if name is not None:
        src = None
        try:
            with open(args.tools_json) as fh:
                src = json.load(fh).get("holders", {}).get(name, {}).get("dimension_source")
        except (IOError, OSError, ValueError):
            pass
        return {"status": "checked", "name": name, "stickout_mm": stickout,
                "dimension_source": src or "drawing"}
    if args.tool_number is None and args.holder is None:
        return {"status": "not requested"}
    return {"status": "holder unknown",
            "reason": "no holder outline/stick-out for tool %s in %s"
                      % (args.tool_number, args.tools_json)}

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


def resolve_moves(moves, x_init=0.0, y_init=0.0, z_init=None):
    """Resolve modal coordinates and arc geometry for a move list.

    Returns dicts with explicit x/y/z (mm), arc tuples where applicable, and
    the move's feed. Do this once on the FULL list before chunking so chunk
    starts inherit the correct position and feed. Moves already carrying
    resolved=True (e.g. output of apply_cutter_comp) keep their arc geometry.

    ``z_init`` is the Z assumed by moves BEFORE the first explicit Z word. The
    default (None) means "Z unknown, above stock": a leading XY-only rapid
    (e.g. ``G00 X.. Y..`` then ``G43 Z3. H03``, as our posted op headers emit) must resolve
    to the first explicit Z of the program, NOT machine 0 -- defaulting to 0
    simulates a phantom dive up/down through the stock. With no Z word at all
    in the list, 0.0 is used.
    """
    if z_init is None:
        z_init = next((mv["z"] for mv in moves if mv.get("z") is not None),
                     0.0)
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
# Default zmap behaviour is "wear" compensation: the programmed path is
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
    posted NC where the activation move is an explicit lead to a safe
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


def _box_max_np(A, k):
    """Max filter over a (2k+1) square window per axis (non-finite = -inf);
    conservative superset of a disc-radius footprint max (numpy only)."""
    m = np.where(np.isfinite(A), A, -np.inf).astype(float)
    for _ in range(k):
        m[1:, :] = np.maximum(m[1:, :], m[:-1, :])
        m[:-1, :] = np.maximum(m[:-1, :], m[1:, :])
        m[:, 1:] = np.maximum(m[:, 1:], m[:, :-1])
        m[:, :-1] = np.maximum(m[:, 1:], m[:, :-1])
    return m


def simulate(moves, part, cell, x0, y0, stock_box, tool="flat", dia=6.0,
             corner=0.0, stock_init=None, window=None, rapid_feed=RAPID_FEED,
             start=None, flute=None, shank_dia=None, holder=None,
             stickout=None, engage_max=None, ramp_angle=3.0):
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
    start     : optional (x, y, z) machine position before the first move;
                used by chunked parallel sims so a chunk's first move starts
                from the previous chunk's end instead of its own target.
    flute     : optional flute length mm; when set, count cutting moves whose
                tip goes more than this below the material surface under the
                move's start/end XY before the move (plunges/ramps/traverses
                into material deeper than the flutes: reach/evacuation
                problem). Reported as plunge_over_flute: count + first line.
    shank_dia : optional shank diameter mm (default = tool dia; only used
                when flute is set). The shank occupies z > tip + flute within
                radius shank_dia/2 of the centre; a cutting sample is a HIT if
                max(current stock, part) over cells within that radius exceeds
                tip + flute + 0.01 mm (the shank above the flutes rubs a
                wall). Reported as over_flute: count of cutting moves with a
                hit, max excess mm, worst xy, first line.
    engage_max: optional threshold mm for radial engagement spikes. When set,
                flag cutting moves whose max radial engagement (chord width of
                the tool's engaged arc, measured perpendicular to travel)
                exceeds this value. Default None = off.
    ramp_angle: ramp/helix angle threshold in degrees (default 3.0). A plunge
                (vertical feed into stock) is NOT flagged if it is a helix or
                ramp at or below this angle.
    holder    : optional S5 holder frustum stack [[z_lo, z_hi, r_lo, r_hi],
                ...] mm above the holder nose (see resolve_holder). When given
                with stickout, every CUTTING sample checks the conservative
                holder envelope: a cylinder of radius max(segment radii) +
                HOLDER_CLEAR (1.0 mm) around the sample centre, from the nose
                at tip + stickout upward (the stack is contiguous from
                z_lo = 0, so material reaching above the nose inside the
                envelope can come within 1.0 mm of some frustum surface). HIT
                if max(current stock, part) inside that envelope stands above
                the nose. Reported as holder_hits: count of cutting moves with
                a hit, max intrusion mm above the nose, worst xy, first line.
    stickout  : holder nose distance above the tool tip mm (with holder).
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
    # shank/over-flute check (only with flute): radius S/2, its own window
    shank_on = flute is not None
    Rs = (shank_dia if shank_dia else dia) / 2.0
    ks = int(math.ceil(Rs / cell)) + 1 if shank_on else k
    # S5 holder check: conservative envelope cylinder (max segment radius +
    # HOLDER_CLEAR) from the nose at tip + stick-out upward; Bstat is a
    # static upper bound of max(stock, part) per neighbourhood (cutting only
    # lowers the stock), so samples whose bound stays at/below the nose skip
    # the window entirely.
    holder_on = holder is not None and stickout is not None
    if holder_on:
        Rh = max(max(s[2], s[3]) for s in holder) + HOLDER_CLEAR
        kH = int(math.ceil(Rh / cell))
        Bstat = _box_max_np(
            np.maximum(np.where(np.isfinite(stock), stock, -np.inf), part),
            kH)

    if window is not None:
        # samples only matter within tool reach of the window; dilate once so
        # the per-sample skip is a single mask lookup (kd covers the shank
        # radius too when the over-flute check is on)
        kd = max(k, ks)
        near = window.copy()
        for _ in range(kd):
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
    if start is not None:
        cur = [start[0], start[1], start[2]]
    elif resolved:
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
    over_flute = 0
    first_over_flute_line = None
    shank_hits = 0
    first_shank_line = None
    shank_depth = 0.0
    shank_worst_xy = None
    holder_hits = 0
    first_holder_line = None
    holder_intrusion = 0.0
    holder_worst_xy = None
    zbands = {}
    comp_moves = 0
    comp_first_line = None
    comp_last_line = None
    d_registers = set()
    # engagement tracking
    engage_spikes = []  # list of dicts: {line, x, y, engagement_mm}
    engage_max_seen = 0.0
    engage_count = 0
    # plunge tracking
    plunge_flags = []  # list of dicts: {line, x, y, z, angle_deg, depth_mm}
    plunge_count = 0

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
        move_over_flute = False
        move_shank = False
        move_holder = False
        move_max_engage = 0.0
        # travel direction for engagement (perpendicular chord width)
        dx_t = x1 - cur[0]
        dy_t = y1 - cur[1]
        tlen = math.hypot(dx_t, dy_t)
        if tlen > 1e-9:
            dx_t, dy_t = dx_t / tlen, dy_t / tlen
        else:
            dx_t, dy_t = 1.0, 0.0  # pure plunge: arbitrary perp direction
        # save stock height at start position BEFORE this move cuts
        stock_at_start = None
        pi_s = int(math.floor((cur[0] - x0) / cell))
        pj_s = int(math.floor((cur[1] - y0) / cell))
        if 0 <= pi_s < nx and 0 <= pj_s < ny:
            stock_at_start = float(stock[pj_s, pi_s])
        if cutting and flute is not None:
            # material surface under the move's start/end XY as it stands
            # BEFORE this move cuts (the footprint leads the centre by R, so
            # mid-move readings would hide true plunge/ramp engagement)
            zmin_m = min(cur[2], z1)
            for (px, py) in ((cur[0], cur[1]), (x1, y1)):
                pi = int(math.floor((px - x0) / cell))
                pj = int(math.floor((py - y0) / cell))
                if 0 <= pi < nx and 0 <= pj < ny:
                    s0 = float(stock[pj, pi])
                    if np.isfinite(s0) and s0 - zmin_m > flute + 1e-9:
                        move_over_flute = True
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
            if cutting and shank_on:
                # shank above the flutes: z > tip + F within radius S/2 of the
                # centre. HIT if stock/part there rises above the flute top
                slo, shi = max(0, i0 - ks), min(nx, i0 + ks + 1)
                tlo, thi = max(0, j0 - ks), min(ny, j0 + ks + 1)
                if slo < shi and tlo < thi:
                    dsg = np.meshgrid(xs[slo:shi] - sx, ys[tlo:thi] - sy)
                    dd = np.hypot(dsg[0], dsg[1])
                    dsh = dd <= Rs + 0.75 * cell
                    vsh = np.where(dsh, np.maximum(stock[tlo:thi, slo:shi],
                                                   part[tlo:thi, slo:shi]),
                                  -np.inf)
                    vtop = float(vsh.max())
                    if vtop > sz + flute + 0.01:
                        move_shank = True
                        excess = vtop - (sz + flute)
                        if excess > shank_depth:
                            shank_depth = excess
                            # among cells at the max height, report the one
                            # whose PART is that high (the wall itself, not
                            # just uncut stock) and closest to the centre
                            psl = part[tlo:thi, slo:shi]
                            cand = dd + np.where(psl >= vtop - 1e-9,
                                               0.0, 1e6)
                            cand = np.where(vsh >= vtop - 1e-9, cand, np.inf)
                            tj, ti = np.unravel_index(int(np.argmin(cand)),
                                                     cand.shape)
                            shank_worst_xy = [float(xs[slo + ti]),
                                            float(ys[tlo + tj])]
            if cutting and holder_on:
                # S5: material within the holder envelope (radius max_r + 1 mm)
                # standing above the nose at tip + stick-out -> the holder stack
                # cannot keep its 1.0 mm clearance
                nose = sz + stickout
                ioc = min(max(i0, 0), nx - 1)
                joc = min(max(j0, 0), ny - 1)
                if float(Bstat[joc, ioc]) > nose:
                    slo, shi = max(0, i0 - kH), min(nx, i0 + kH + 1)
                    tlo, thi = max(0, j0 - kH), min(ny, j0 + kH + 1)
                    if slo < shi and tlo < thi:
                        dsg = np.meshgrid(xs[slo:shi] - sx, ys[tlo:thi] - sy)
                        dd = np.hypot(dsg[0], dsg[1])
                        dH = dd <= Rh
                        mat = np.maximum(
                            np.where(np.isfinite(stock[tlo:thi, slo:shi]),
                                   stock[tlo:thi, slo:shi], -np.inf),
                            part[tlo:thi, slo:shi])
                        vH = np.where(dH, mat, -np.inf)
                        vtop = float(vH.max())
                        if vtop > nose:
                            move_holder = True
                            intr = vtop - nose
                            if intr > holder_intrusion:
                                holder_intrusion = intr
                                # among cells at the max height, report the one
                                # whose PART is that high and closest to centre
                                psl = part[tlo:thi, slo:shi]
                                cand = dd + np.where(psl >= vtop - 1e-9,
                                                   0.0, 1e6)
                                cand = np.where(vH >= vtop - 1e-9, cand, np.inf)
                                tj, ti = np.unravel_index(int(np.argmin(cand)),
                                                        cand.shape)
                                holder_worst_xy = [float(xs[slo + ti]),
                                                float(ys[tlo + tj])]
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
                # Must use msk_e-filtered max so that engaged=True implies
                # msk_e has True cells (prevents inf/NaN in engagement width).
                msk_e = d <= R + 0.75 * cell
                if window is not None:
                    msk_e &= window[jlo:jhi, ilo:ihi]
                engaged = (msk_e.any() and
                         float(np.max(np.where(msk_e, win, -np.inf))) > sz + 1e-6)
                # radial engagement: chord width of engaged arc perpendicular to
                # travel (dx_t, dy_t); equivalent radial width = 2*R*sin(theta/2)
                if engaged and engage_max is not None:
                    perp_x, perp_y = -dy_t, dx_t
                    proj = (gx[None, :] * perp_x + gy[:, None] * perp_y)
                    eproj = np.where(msk_e, proj, -np.inf)
                    ew = float(eproj.max()) - float(eproj.min())
                    # Clamp to [0, dia]: the padded mask (R + 0.75*cell) can
                    # make ew slightly exceed the tool diameter; guard against
                    # inf/NaN from degenerate masks (helix, pure plunge, arcs).
                    ew = min(max(ew, 0.0), 2.0 * R)
                    if not np.isfinite(ew):
                        ew = 0.0
                    if ew > move_max_engage:
                        move_max_engage = ew
                if removed > REMOVE_EPS:
                    stock[jlo:jhi, ilo:ihi] = np.minimum(win, newv)
                if not engaged:
                    air_length += seg_len
            else:  # rapid
                if np.any(np.where(msk, cut > REMOVE_EPS, False)):
                    move_collided = True
        if cutting:
            cut_length += length
            lo = int(math.floor(0.5 * (cur[2] + z1) / 5.0)) * 5
            lbl = "%d-%d" % (lo, lo + 5)
            zbands[lbl] = zbands.get(lbl, 0.0) + length
            if flute is not None and move_over_flute:
                over_flute += 1
                if first_over_flute_line is None:
                    first_over_flute_line = mv["line"]
            if shank_on and move_shank:
                shank_hits += 1
                if first_shank_line is None:
                    first_shank_line = mv["line"]
            if holder_on and move_holder:
                holder_hits += 1
                if first_holder_line is None:
                    first_holder_line = mv["line"]
            feed = mv.get("f")
            cycle_s += length / (feed if feed and feed > 0 else rapid_feed) * 60.0
        else:  # rapid
            rapid_length += length
            cycle_s += length / rapid_feed * 60.0
            if move_collided:
                rapid_collisions += 1
                if first_rapid_line is None:
                    first_rapid_line = mv["line"]
        # engagement spike: flag moves exceeding threshold
        if cutting and engage_max is not None and move_max_engage > engage_max:
            engage_count += 1
            engage_spikes.append({
                "line": mv["line"],
                "x": round(x1, 4), "y": round(y1, 4),
                "engagement_mm": round(move_max_engage, 4)})
            if move_max_engage > engage_max_seen:
                engage_max_seen = move_max_engage
        # plunge detection: feed move descending into stock
        if cutting and z1 < cur[2] - 1e-9:
            dx_m = x1 - cur[0]
            dy_m = y1 - cur[1]
            dz_m = cur[2] - z1
            xy_len = math.hypot(dx_m, dy_m)
            # check if entering stock: stock at start XY > move's min Z
            # (using pre-move stock height saved before the sample loop)
            zmin_m = min(cur[2], z1)
            enters = False
            depth_m = 0.0
            if stock_at_start is not None and np.isfinite(stock_at_start):
                if stock_at_start > zmin_m:
                    enters = True
                    depth_m = stock_at_start - zmin_m
            if enters:
                # compute ramp angle
                angle_deg = 90.0
                if xy_len > 1e-9:
                    angle_deg = math.degrees(math.atan2(dz_m, xy_len))
                # flag unless helix/ramp at or under ramp_angle
                if xy_len < 1e-9 or angle_deg > ramp_angle:
                    plunge_count += 1
                    plunge_flags.append({
                        "line": mv["line"],
                        "x": round(cur[0], 4), "y": round(cur[1], 4),
                        "z": round(z1, 4),
                        "angle_deg": round(angle_deg, 2),
                        "depth_mm": round(depth_m, 4)})
        cur = [x1, y1, z1]

    result = {
        "stock": stock,
        "rapid_collisions": {"count": rapid_collisions,
                            "first_line": first_rapid_line},
        "plunge_over_flute": ({"count": over_flute, "flute_mm": flute,
                               "first_line": first_over_flute_line}
                              if flute is not None else None),
        "over_flute": ({"count": shank_hits, "max_depth": shank_depth,
                        "worst_xy": shank_worst_xy,
                        "first_line": first_shank_line}
                       if flute is not None else None),
        "holder_hits": ({"count": holder_hits,
                         "max_intrusion": holder_intrusion,
                         "worst_xy": holder_worst_xy,
                         "first_line": first_holder_line}
                        if holder_on else None),
        "air_fraction": (air_length / cut_length) if cut_length > 0 else 0.0,
        "cutting_length_mm": cut_length,
        "cutting_length_by_zband": {k: round(v, 1)
                                    for k, v in sorted(zbands.items())},
        "rapid_length_mm": rapid_length,
        "cycle_time_s": cycle_s,
        "cutter_comp": {"active_moves": comp_moves,
                       "first_line": comp_first_line,
                       "last_line": comp_last_line,
                       "d_registers": sorted(d_registers)},
        "engagement": {
            "threshold_mm": engage_max,
            "count": engage_count,
            "max_mm": round(engage_max_seen, 4),
            # top 10 worst spots (line, XY, value)
            "spikes": sorted(engage_spikes, key=lambda s: s["engagement_mm"],
                             reverse=True)[:10],
        } if engage_max is not None else None,
        "plunge": {
            "ramp_angle_deg": ramp_angle,
            "count": plunge_count,
            # top 10 deepest spots (line, XY, value)
            "flags": sorted(plunge_flags, key=lambda f: f["depth_mm"],
                           reverse=True)[:10],
        },
    }
    result.update(analyze(stock, part, cell, x0, y0,
                          restrict=window if window is not None else in_box))
    return result


# --------------------------------------------------------------------------
# Parallel chunking
# --------------------------------------------------------------------------
# Stock updates are a running per-cell minimum, so splitting the (globally
# modal-resolved) move list and combining chunk stocks with an element-wise
# min is EXACT for the final heightfield and gouge/leftover stats.
# Rapid collisions need the stock state as it was EARLIER in the program, so
# a naive chunked count is wrong (a rapid descending into material already cut
# by an earlier chunk looks like a collision against fresh stock). Fixed with
# two passes: pass 1 computes each chunk's own removal field; each chunk then
# re-runs with stock_init = min(base, removals of all earlier chunks), which
# reproduces the sequential stock state at its start (earlier chunks all cut
# before later ones). With chunk start positions also carried across, the
# chunked result (stock, gouges, rapids, cycle time) is identical to serial;
# air_fraction is reconstructed exactly from the per-chunk values.

_CHUNK = {}


def _chunk_worker(idx):
    g = _CHUNK
    return simulate(g["moves"][g["spans"][idx]], g["part"], g["cell"],
                    g["x0"], g["y0"],
                    g["stock_box"], tool=g["tool"], dia=g["dia"],
                    corner=g["corner"],
                    stock_init=g["stock_init_per"][idx],
                    window=g["window"], rapid_feed=g["rapid_feed"],
                    start=g["start_per"][idx], flute=g["flute"],
                    shank_dia=g["shank_dia"], holder=g["holder"],
                    stickout=g["stickout"], engage_max=g["engage_max"],
                    ramp_angle=g["ramp_angle"])


def simulate_parallel(moves, part, cell, x0, y0, stock_box, jobs, tool="flat",
                      dia=6.0, corner=0.0, stock_init=None, window=None,
                      rapid_feed=RAPID_FEED, flute=None, shank_dia=None,
                      holder=None, stickout=None, engage_max=None,
                      ramp_angle=3.0):
    import multiprocessing as mp
    # leading moves without a Z word: Z unknown = above stock, not machine 0;
    # use the first explicit Z (as serial simulate does), else the stock top
    z_init = next((m["z"] for m in moves if m.get("z") is not None),
                 float(stock_box[5]))
    moves = resolve_moves(moves, z_init=z_init)
    spans, n = [], len(moves)
    per = int(math.ceil(n / float(jobs)))
    for c in range(0, n, per):
        spans.append(slice(c, min(n, c + per)))
    _CHUNK.update(moves=moves, spans=spans, part=part, cell=cell, x0=x0,
                  y0=y0,
                  stock_box=stock_box, tool=tool, dia=dia, corner=corner,
                  window=window, rapid_feed=rapid_feed, flute=flute,
                  shank_dia=shank_dia, holder=holder, stickout=stickout,
                  engage_max=engage_max, ramp_angle=ramp_angle)
    # true machine position at each chunk start = end of the previous chunk's
    # last move (chunks must not simulate their first move from its own target)
    start_per = []
    for sp in spans:
        if sp.start == 0:
            start_per.append(None)
        else:
            p = moves[sp.start - 1]
            start_per.append((p["x"], p["y"], p["z"]))
    _CHUNK["start_per"] = start_per
    ctx = mp.get_context("fork")
    # pass 1: every chunk simulates from the base stock to get its own removals
    _CHUNK["stock_init_per"] = [stock_init] * len(spans)
    with ctx.Pool(len(spans)) as pool:
        pass1 = pool.map(_chunk_worker, range(len(spans)))
    # prefix stock for chunk c = base stock cut by ALL chunks before c, so
    # rapid-collision checks see the same material state as in a serial run
    # (pass-1 chunk stocks already have stock_init applied to them)
    prefixes, acc = [], stock_init
    for r in pass1:
        prefixes.append(acc)
        acc = r["stock"] if acc is None else np.minimum(acc, r["stock"])
    # pass 2: re-run chunks with their true starting stock (exact rapids)
    _CHUNK["stock_init_per"] = prefixes
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
            "note": "exact under --jobs (two-pass prefix stock + chunk starts)",
        },
        "plunge_over_flute": (
            {"count": sum(r["plunge_over_flute"]["count"] for r in results),
             "flute_mm": flute,
             "first_line": min((r["plunge_over_flute"]["first_line"]
                               for r in results
                               if r["plunge_over_flute"]["first_line"]),
                              default=None)}
            if flute is not None else None),
        "over_flute": (
            {"count": sum(r["over_flute"]["count"] for r in results),
             "max_depth": max(r["over_flute"]["max_depth"]
                             for r in results),
             "worst_xy": max(results,
                            key=lambda r: r["over_flute"]["max_depth"])[
                                "over_flute"]["worst_xy"],
             "first_line": min((r["over_flute"]["first_line"]
                               for r in results
                               if r["over_flute"]["first_line"]),
                              default=None)}
            if flute is not None else None),
        "holder_hits": (
            {"count": sum(r["holder_hits"]["count"] for r in results),
             "max_intrusion": max(r["holder_hits"]["max_intrusion"]
                                 for r in results),
             "worst_xy": max(results,
                            key=lambda r: r["holder_hits"]["max_intrusion"])[
                                "holder_hits"]["worst_xy"],
             "first_line": min((r["holder_hits"]["first_line"]
                               for r in results
                               if r["holder_hits"]["first_line"]),
                              default=None)}
            if holder is not None else None),
        "air_fraction": 0.0,
        "cutting_length_mm": sum(r["cutting_length_mm"] for r in results),
        "rapid_length_mm": sum(r["rapid_length_mm"] for r in results),
        "cycle_time_s": sum(r["cycle_time_s"] for r in results),
        "engagement": (
            {"threshold_mm": engage_max,
             "count": sum(r["engagement"]["count"] for r in results),
             "max_mm": round(max(r["engagement"]["max_mm"]
                                for r in results), 4),
             "spikes": sorted([s for r in results
                              for s in r["engagement"]["spikes"]],
                             key=lambda s: s["engagement_mm"],
                             reverse=True)[:10],
            } if engage_max is not None else None),
        "plunge": {
            "ramp_angle_deg": ramp_angle,
            "count": sum(r["plunge"]["count"] for r in results),
            "flags": sorted([f for r in results
                            for f in r["plunge"]["flags"]],
                           key=lambda f: f["depth_mm"], reverse=True)[:10],
        },
    }
    zbands = {}
    for r in results:
        for k, v in r["cutting_length_by_zband"].items():
            zbands[k] = zbands.get(k, 0.0) + v
    combined["cutting_length_by_zband"] = {k: round(v, 1)
                                           for k, v in sorted(zbands.items())}
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
    tess = meta.get("tess_tol")
    if tess is None or float(tess) > 0.02:
        print("warning: part sidecar tess_tol missing or > 0.02 mm "
              "(vertical walls carry chord error); regenerate the heightfield "
              "with TESS_TOL=0.01", file=sys.stderr)
    return part, float(meta["cell"]), float(meta["x0"]), float(meta["y0"])


def _sanitize(obj):
    """Replace inf/NaN with None so json.dumps never fails."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


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
                   help="parallel worker processes (results identical to "
                        "serial: prefix stock + chunk start states)")
    p.add_argument("--flute", type=float, default=None,
                  help="flute length mm: when set, report cutting moves whose "
                       "tip is more than this deep below the local stock "
                       "surface at that XY (plunge_over_flute: count + first "
                       "line) and run the shank rub check (over_flute). "
                       "Default off.")
    p.add_argument("--shank-dia", dest="shank_dia", type=float, default=None,
                  help="shank diameter mm for the over-flute shank rub check "
                       "(default: tool dia); used with --flute")
    p.add_argument("--optimal-load", dest="optimal_load", type=float, default=None,
                  help="optimal radial engagement load mm: when given and "
                       "--engage-max is not set, the engagement threshold is "
                       "1.5 x this value. Default off.")
    p.add_argument("--engage-max", dest="engage_max", type=float, default=None,
                  help="radial engagement threshold mm: flag cutting moves whose "
                       "max engagement exceeds this (chord width of engaged arc "
                       "perpendicular to travel). Default: 1.5 x --optimal-load "
                       "when that is given, else off.")
    p.add_argument("--ramp-angle", dest="ramp_angle", type=float, default=3.0,
                  help="ramp/helix angle threshold deg for plunge detection "
                       "(default 3.0). Descending feed moves into stock are "
                       "flagged unless they are helix/ramp at or below this.")
    p.add_argument("--tool-number", dest="tool_number", type=int, default=None,
                   help="S5: X7 tool number; resolves the holder frustum "
                        "stack + stick-out from tools/x7_tools.json (entry "
                        "needs holder + stickout_mm) for the holder-hit check")
    p.add_argument("--holder", default=None,
                   help="S5: holder name in the tools json \"holders\" map "
                        "(requires --stickout); overrides --tool-number")
    p.add_argument("--stickout", type=float, default=None,
                   help="S5: holder nose distance above tool tip mm "
                        "(with --holder, or overriding the table entry)")
    p.add_argument("--tools-json", dest="tools_json", default=TOOLS_JSON,
                   help="tool table JSON for --tool-number/--holder "
                        "(default: tools/x7_tools.json)")
    args = p.parse_args(argv)

    # Derive engage_max from optimal_load when not explicitly given
    engage_max = args.engage_max
    if engage_max is None and args.optimal_load is not None:
        engage_max = 1.5 * args.optimal_load

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
    hg = resolve_holder(args.tool_number, args.holder, args.stickout,
                       args.tools_json)
    holder_segs, holder_stick, holder_name = \
        hg if hg else (None, None, None)
    if args.jobs > 1:
        res = simulate_parallel(moves, part, cell, x0, y0, stock_box,
                               args.jobs, tool=args.tool, dia=args.dia,
                               corner=args.corner, stock_init=stock_init,
                               window=window, rapid_feed=args.rapid_feed,
                               flute=args.flute, shank_dia=args.shank_dia,
                               holder=holder_segs, stickout=holder_stick,
                               engage_max=engage_max,
                               ramp_angle=args.ramp_angle)
    else:
        res = simulate(moves, part, cell, x0, y0, stock_box,
                       tool=args.tool, dia=args.dia, corner=args.corner,
                       stock_init=stock_init, window=window,
                       rapid_feed=args.rapid_feed, flute=args.flute,
                       shank_dia=args.shank_dia,
                       holder=holder_segs, stickout=holder_stick,
                       engage_max=engage_max, ramp_angle=args.ramp_angle)

    report = {
        "gcode": os.path.abspath(args.gcode),
        "part": os.path.abspath(args.part),
        "tool": {"type": args.tool, "dia": args.dia, "corner": args.corner},
        "stock_box": [float(v) for v in stock_box],
        "stock_in": os.path.abspath(args.stock_in) if args.stock_in else None,
        "holder": _holder_report(args, holder_name, holder_stick),
        "cell": cell,
        "window": ("steep walls |dZ|>1mm dilated 2mm" if args.window else None),
        "gouges": res["gouges"],
        "leftover": res["leftover"],
        "within_0p5mm_fraction": res["within_0p5mm_fraction"],
        "rapid_collisions": res["rapid_collisions"],
        "plunge_over_flute": res["plunge_over_flute"],
        "over_flute": res["over_flute"],
        "holder_hits": res["holder_hits"],
        "cutter_comp": res["cutter_comp"],
        "comp_radius_mm": args.comp_radius,
        "air_fraction": res["air_fraction"],
        "cutting_length_mm": round(res["cutting_length_mm"], 1),
        "cutting_length_by_zband_mm": res["cutting_length_by_zband"],
        "rapid_length_mm": round(res["rapid_length_mm"], 1),
        "cycle_time_s": round(res["cycle_time_s"], 1),
        "cycle_time_note": ("feed moves at their F words; rapids assumed at "
                           "%.0f mm/min" % args.rapid_feed),
        "engagement": res["engagement"],
        "plunge": res["plunge"],
        "warnings": {
            "engagement": res["engagement"],
            "plunge": res["plunge"],
        },
    }
    report = _sanitize(report)
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
