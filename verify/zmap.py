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
# Task ZA: an AXIAL PLUNGE is a descending feed move (G1) steeper than
# MAX_RAMP_DEG whose tool removes stock deeper than its floor under its
# end-point disk (deepest removed column, read before the move cuts).
# Flat/bull: floor AXIAL_FLOOR; ball (task ZB): floor BALL_AXIAL_FLOOR.
# Every tool type: failing gate at its own floor.
# MAX_RAMP_DEG = 15 = the engine's maximum ramp/helix angle: helixes and ramps
# at or below it are legitimate entries; anything steeper into stock - a true
# vertical (90 deg) or a disguised steep diagonal - is a plunge.
# AXIAL_FLOOR = 0.2 mm is a measurement noise floor (2 x the 0.1 mm judge
# cell), NOT a tolerated depth. Measured on out/core_front_roughRT_before.ngc
# (flat 12.686): 489 straight descents remove stock - 14 stepdown re-entries
# of 1.12-1.62 mm and 475 solid-stock plunges of 10.16-25.65 mm (worst at
# XY (-2.593,-52.230), line 63675). Both groups are axial removal under a
# flat bottom and both fail; no tolerated axial depth for flat/bull tools.
# Constants: never raise either later; fix the measurement instead.
MAX_RAMP_DEG = 15.0
AXIAL_FLOOR = 0.2  # mm: noise floor, constant, never raise it later
# Task ZB: BALL_AXIAL_FLOOR = 0.5 mm - a FIXED constant for ball tools, NOT
# tied to any per-program finish-leave parameter: James's 0.381 mm finish
# leave plus measurement noise. A ball axial plunge (same rule: descending
# feed steeper than MAX_RAMP_DEG, angle from arc length for helical arcs)
# that removes stock deeper than this under the ball FAILS exactly like a
# flat/bull plunge (CLI exit 1 + connector gate). Ball contact disk at the
# end point = the tool's full radius R around the end XY; removed depth is
# the deepest column stock - (z_end + dz(d)) over that disk against the
# spherical surface (see simulate). Never raise this floor later; fix the
# measurement or the toolpath instead.
BALL_AXIAL_FLOOR = 0.5  # mm: fixed ball floor, constant, never raise it
# Task ZE (report-only): axial depth classification of engaging horizontal
# feed moves. Axial depth = deepest column of stock removed above the tool
# tip under the footprint during the move (max over removed cells of
# stock_before - cut surface, read BEFORE the move cuts).
# SLOT_AXIAL_MM = 0.5: wide move with axial depth above this is a SLOT
# (axial cut); at or below it, a SKIM.
# SKIM_AXIAL_MM = 0.05: a move removing no more than this skims a floor
# already within a few hundredths of a mm.
# FULL_WIDTH_FRAC: radial width >= 0.9 x tool diameter = full-width slot.
# OVERLOAD_WIDTH_MM = 1.2 x the 2.032 mm optimal load (task text rounds to
# 2.44): the SE2 merge bar - SE2 must not increase overload count or total
# length vs main's helix-only rough on Core Front.
SLOT_AXIAL_MM = 0.5
SKIM_AXIAL_MM = 0.05
FULL_WIDTH_FRAC = 0.9
OVERLOAD_WIDTH_MM = 1.2 * 2.032  # = 2.4384 mm
# Task ZE2 (report-only): AREA-based radial engagement ae_eff = plan area of
# the cells a horizontal feed removes material from (cells counted once) over
# travel length. Consecutive horizontal feeds at the same Z along the same
# path (direction change <= AE2_DIR_MAX_DEG, no intervening rapid or vertical
# move) are combined into windows of at least AE2_WINDOW_MM travel, so the
# 0.1 mm judge grid adds no noise to short moves.
AE2_WINDOW_MM = 1.0
AE2_DIR_MAX_DEG = 45.0
# Task ZE2F (report-only): every ae2 window carries its feed. Cutting feed =
# the feed with the most horizontal ae2 travel in the program; a window at a
# feed below AE2_ENTRY_FEED_FRAC x that is an ENTRY-feed window. An entry-feed
# full-width window is ALLOWED only right after a helix descent and only with
# a <= that helix's measured pitch + AE2_PITCH_TOL (the same load per tooth as
# the helix turn itself); everything else full-width is a finding.
AE2_ENTRY_FEED_FRAC = 0.9
AE2_PITCH_TOL = 0.05
# Task ZE2F2: the helix pitch carries along the contiguous entry-feed run at
# the helix-bottom Z for at most one circumference of the helix path plus this
AE2_CARRY_EXTRA_MM = 1.0
# Task ZE2L (James 2026-10-27, "judge by load"): load of an ae2 window =
# ae_eff x a x feed / (design ae x design stepdown x cutting feed). A helix-bottom
# window (ZE2F2 carry) is allowed only when a <= pitch + AE2_PITCH_TOL AND load
# <= AE2_FLOOR_LOAD_MAX; overload_feeds_ae2_load drops allowed ones (the raw
# overload_feeds_ae2 stays as it was; the new key only with --load-rule). --design-ae /
# --design-stepdown set the design cut.
AE2_FLOOR_LOAD_MAX = 1.2
DESIGN_AE = 2.032
DESIGN_STEPDOWN = 19.05
LOAD_RULE = False   # --load-rule: emit overload_feeds_ae2_load (opt-in, keeps default JSON)
# Task ZE2D (report-only): full_width_depth of an ae2 window = the largest h for
# which (plan area of cells removed at least h deep) / travel >= 0.9 x dia.
# Separates a genuinely deep full-width slot from a wide shallow cut joined to
# a thin deep graze (where a = max removed height alone reads "deep slot").
# Removed heights are binned per move at FWD_BIN_MM (resolution of the result).
FWD_BIN_MM = 0.25
FWD_NBINS = 100
# Task ZE2B (report-only, ball only): engagement vs the pre-move stock zmap;
# descent = horizontal travel < ZE2B_DESCENT_FRAC of 3D travel (u undefined,
# never full-width: axial plunges stay ZB's job).
ZE2B_DESCENT_FRAC = 0.1
TOOLS_JSON = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools", "x7_tools.json")

# --strict (opt-in, task CP): the supported subset for judging a posted
# program. Anything outside these sets is reported unsupported, never skipped.
STRICT_ALLOWED_G = {0, 1, 2, 3, 4, 17, 20, 21, 40, 43, 49, 53,
                   54, 55, 56, 57, 58, 59, 80, 90, 94}
STRICT_ALLOWED_M = {3, 4, 5, 6, 8, 9, 30}
STRICT_OK_WORDS = {"G", "X", "Y", "Z", "F", "S", "T", "M", "N", "O"}


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


def _home_line(words):
    """True for the 'G91 G28 X0. Y0.' XY home line (order-free, no Z,
    zero XY, no other words): the only G91/G28 allowed under --strict."""
    gs, axes = set(), {}
    for L, num in words:
        try:
            v = float(num)
        except ValueError:
            return False
        if L == "G":
            gs.add(int(round(v)))
        elif L in ("X", "Y", "Z"):
            axes[L] = v
        else:
            return False
    return (gs >= {28, 91} and set(axes) == {"X", "Y"}
            and abs(axes["X"]) <= 1e-9 and abs(axes["Y"]) <= 1e-9)


def strict_check(text):
    """--strict (task CP): whitelist every word of a posted program.
    Allowed: G0-G3 and G2/G3 arcs in G17 (I/J centre and R forms), G17,
    G20/G21, G90, G94, G40, G49, G80 (cancel), G43 H, G53 Z-only retract
    lines, G54-G59, one 'G91 G28 X0 Y0' home line at the end, G04 P,
    F, S, T/M06, M03/M04/M05/M08/M09/M30, comments, N numbers, O, %.
    Anything else is an offender. Never skips a line silently: returns a
    list of {"code": <code>, "line": <1-based line>} in program order
    (empty list = the program is fully supported)."""
    findings = []
    units = 1.0
    pos_x = pos_y = None
    modal = None
    home_line = None

    def flag(code, lineno):
        findings.append({"code": code, "line": lineno})

    for lineno, raw in enumerate(text.splitlines(), 1):
        s = strip_comments(raw)
        if "#" in s:
            flag("#", lineno)
            continue
        words = [(L.upper(), num) for L, num in WORD_RE.findall(s)]
        if not words:
            rest = WORD_RE.sub("", s).replace("%", "").strip()
            if re.search(r"[A-Za-z0-9]", rest):
                junk = re.search(r"[A-Za-z][A-Za-z0-9.]*", rest)
                flag(junk.group(0) if junk else rest[:8], lineno)
            continue
        # a home line may only sit at the END: any axis word after it
        # means the program kept cutting past home -> not a home line
        if home_line is not None and any(
                L in ("X", "Y", "Z") for L, _ in words):
            flag("G28", home_line)
            home_line = None
        vals = {}
        gcodes = []
        for L, num in words:
            try:
                v = float(num)
            except ValueError:
                flag(L, lineno)
                continue
            if L == "G":
                gcodes.append(int(round(v)))
            vals.setdefault(L, []).append(v)
        gs = set(gcodes)
        home = _home_line(words)
        if home:
            if home_line is not None:
                flag("G28", lineno)
            else:
                home_line = lineno
        if 20 in gs:
            units = 25.4
        elif 21 in gs:
            units = 1.0
        axes = [L for L in vals if L in ("X", "Y", "Z")]
        new_modal = modal
        for g in (0, 1, 2, 3):
            if g in gs:
                new_modal = g
        arc_line = new_modal in (2, 3)
        for g in sorted(gs):
            if g in (28, 91):
                if not home:
                    flag("G%d" % g, lineno)
            elif g in STRICT_ALLOWED_G:
                if g == 53 and any(L != "Z" for L in axes):
                    flag("G53", lineno)  # only Z-only machine retracts
                elif g == 43 and "H" not in vals:
                    flag("G43", lineno)  # G43 must carry its H register
            else:
                flag("G%d" % g, lineno)
        for v in vals.get("M", []):
            m = int(round(v))
            if m not in STRICT_ALLOWED_M:
                flag("M%d" % m, lineno)
        for L in vals:
            if L in STRICT_OK_WORDS:
                continue
            if L == "H":
                if 43 not in gs:
                    flag("H", lineno)
            elif L == "P":
                if 4 not in gs:
                    flag("P", lineno)
            elif L in ("I", "J"):
                if not arc_line:
                    flag(L, lineno)
            elif L == "R":
                if not arc_line:
                    flag("R", lineno)
            else:
                flag(L, lineno)
        # R-form chord check (needs the pre-move position)
        if "R" in vals and arc_line:
            sx = pos_x if pos_x is not None else (
                vals["X"][-1] * units if "X" in vals else None)
            sy = pos_y if pos_y is not None else (
                vals["Y"][-1] * units if "Y" in vals else None)
            tx = vals["X"][-1] * units if "X" in vals else sx
            ty = vals["Y"][-1] * units if "Y" in vals else sy
            if None not in (sx, sy, tx, ty):
                d = math.hypot(tx - sx, ty - sy)
                for rv in vals["R"]:
                    r = abs(rv) * units
                    if d <= 1e-9 or r < d / 2.0 - 1e-9:
                        flag("R", lineno)
        if "X" in vals:
            pos_x = vals["X"][-1] * units
        if "Y" in vals:
            pos_y = vals["Y"][-1] * units
        modal = new_modal
    return findings


def parse_gcode(text, strict=False):
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
            elif L == "R":
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
        if strict and any(g == 4 for g in gcodes):
            continue  # dwell: never a simulated move (a bare G04 X is not X)
        if strict and _home_line([(L.upper(), n) for L, n in words]):
            continue  # end-of-program XY home line: not a simulated move
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
            # R form (G2/G3 ... R<n>): radius from the start point; negative
            # R = arc > 180 deg. Resolved to a centre where I/J are absent.
            if "R" in params:
                move["r"] = params["R"] * units
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


def _r_center(start, end, r, ccw):
    """R-form arc (G2/G3 ... R<n>, G17): centre offset (i, j) from `start`
    for radius r (signed: negative r = arc > 180 deg). Returns None when
    |r| cannot span the start-end chord or the points coincide."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    d = math.hypot(dx, dy)
    if d <= 1e-9:
        return None  # R form cannot express a full circle
    h2 = r * r - (d / 2.0) ** 2
    if h2 < -1e-9:
        return None  # radius too small for this chord
    h = math.sqrt(max(h2, 0.0))
    ux, uy = dx / d, dy / d
    # CCW with r>0 (and CW with r<0): centre left of the travel chord
    sgn = 1.0 if (ccw == (r > 0)) else -1.0
    cx = 0.5 * (start[0] + end[0]) + sgn * h * (-uy)
    cy = 0.5 * (start[1] + end[1]) + sgn * h * ux
    return (cx - start[0], cy - start[1])


def _arc_ijk(mv, start, end):
    """Center offsets (i, j, k) for an arc move: I/J/K as programmed, or
    resolved from an R word (G17) when they are absent."""
    i = mv.get("i", 0.0) or 0.0
    j = mv.get("j", 0.0) or 0.0
    k = mv.get("k", 0.0) or 0.0
    r = mv.get("r")
    if r and abs(i) <= 1e-12 and abs(j) <= 1e-12:
        c = _r_center(start, end, r, mv["motion"] == "G3")
        if c is not None:
            return (c[0], c[1], 0.0)
    return (i, j, k)


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
                         _arc_ijk(mv, (cx, cy, cz), (x, y, z)),
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
                         _arc_ijk(mv, (cx, cy, cz), (x, y, z)),
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


def _engage_stats(vals):
    """Distribution of per-move max chord engagement (mm) over numpy:
    {n, p50, p95, p99, max}; n=0 -> percentiles/max are None."""
    if not vals:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}
    a = np.asarray(vals, dtype=float)
    return {"n": int(a.size),
            "p50": round(float(np.percentile(a, 50)), 4),
            "p95": round(float(np.percentile(a, 95)), 4),
            "p99": round(float(np.percentile(a, 99)), 4),
            "max": round(float(a.max()), 4)}


def _wide_class(recs):
    """Task ZE: one wide-move class (slot or skim) summary: count, total
    length, total time at the moves' feed, p50/p99 of radial width and of
    axial depth."""
    if not recs:
        return {"count": 0, "total_length_mm": 0.0, "total_time_s": 0.0,
                "width_p50": None, "width_p99": None,
                "depth_p50": None, "depth_p99": None}
    w = np.asarray([r["width_mm"] for r in recs], dtype=float)
    d = np.asarray([r["depth_mm"] for r in recs], dtype=float)
    return {"count": len(recs),
            "total_length_mm": round(sum(r["length_mm"] for r in recs), 1),
            "total_time_s": round(sum(r["time_s"] for r in recs), 1),
            "width_p50": round(float(np.percentile(w, 50)), 4),
            "width_p99": round(float(np.percentile(w, 99)), 4),
            "depth_p50": round(float(np.percentile(d, 50)), 4),
            "depth_p99": round(float(np.percentile(d, 99)), 4)}


def _ze_engagement_keys(hw, engage_max, dia):
    """Task ZE (report-only): new engagement keys derived from the raw
    per-move records of every engaging cutting move (each: line, x, y, z,
    kind, width_mm = max chord engagement, depth_mm = axial depth removed
    above the tip, length_mm, time_s at the move's feed). The existing
    engagement numbers are computed elsewhere and stay untouched.
    - wide_moves: horizontal moves over the engagement threshold split into
      "slot" (axial depth > SLOT_AXIAL_MM) and "skim" (<=); None when no
      threshold was given.
    - slot_horizontal: {n, p50, p95, p99, max} of radial width over
      horizontal moves with axial depth > SLOT_AXIAL_MM - the engagement
      statistic that matters for load.
    - skim_by_z: time per Z level spent skimming (horizontal feeds with
      axial depth <= SKIM_AXIAL_MM, i.e. floors already within a few
      hundredths).
    - full_width_slots: horizontal feeds with radial width >=
      FULL_WIDTH_FRAC x dia AND axial depth > SLOT_AXIAL_MM.
    - overload_feeds: horizontal feeds with radial width > OVERLOAD_WIDTH_MM
      AND axial depth > SLOT_AXIAL_MM (the SE2 merge bar)."""
    horiz = [r for r in hw if r["kind"] == "horizontal"]
    slots = [r for r in horiz if r["depth_mm"] > SLOT_AXIAL_MM]
    wide = ([r for r in horiz if r["width_mm"] > engage_max]
            if engage_max is not None else None)
    skim_by_z = {}
    for r in horiz:
        if r["depth_mm"] <= SKIM_AXIAL_MM:
            k = "%.3f" % r["z"]
            skim_by_z[k] = skim_by_z.get(k, 0.0) + r["time_s"]
    fws = sorted([r for r in horiz if r["width_mm"] >= FULL_WIDTH_FRAC * dia
                  and r["depth_mm"] > SLOT_AXIAL_MM],
                 key=lambda r: (-r["depth_mm"], -r["width_mm"]))
    ovl = sorted([r for r in horiz if r["width_mm"] > OVERLOAD_WIDTH_MM
                  and r["depth_mm"] > SLOT_AXIAL_MM],
                 key=lambda r: (-r["width_mm"], -r["depth_mm"]))
    return {
        "wide_moves": (None if wide is None else {
            "threshold_mm": engage_max,
            "slot": _wide_class([r for r in wide
                                if r["depth_mm"] > SLOT_AXIAL_MM]),
            "skim": _wide_class([r for r in wide
                                if r["depth_mm"] <= SLOT_AXIAL_MM]),
        }),
        "slot_horizontal": _engage_stats([r["width_mm"] for r in slots]),
        "skim_by_z": {k: round(v, 1) for k, v in
                      sorted(skim_by_z.items(), key=lambda kv: float(kv[0]))},
        "full_width_slots": {
            "count": len(fws),
            "total_length_mm": round(sum(r["length_mm"] for r in fws), 1),
            "total_time_s": round(sum(r["time_s"] for r in fws), 1),
            # top 20 by axial depth (line, XY, width, depth)
            "top": [{"line": r["line"], "x": r["x"], "y": r["y"],
                    "width_mm": r["width_mm"], "depth_mm": r["depth_mm"]}
                   for r in fws[:20]],
        },
        "overload_feeds": {
            "width_mm_above": round(OVERLOAD_WIDTH_MM, 4),
            "count": len(ovl),
            "total_length_mm": round(sum(r["length_mm"] for r in ovl), 1),
            "total_time_s": round(sum(r["time_s"] for r in ovl), 1),
            # worst 20 by radial width, then depth (line, XY, Z, width, depth)
            "worst": [{"line": r["line"], "x": r["x"], "y": r["y"],
                      "z": r["z"], "width_mm": r["width_mm"],
                      "depth_mm": r["depth_mm"]} for r in ovl[:20]],
        },
    }


def _ae2_windows(moves):
    """Task ZE2: combine consecutive horizontal feed moves into windows of at
    least AE2_WINDOW_MM travel. An entry is one horizontal feed move:
    {idx (global move index), line, x, y, z (rounded 3), dx, dy (unit chord
    direction), length_mm, area_mm2 (plan area of cells this move removes,
    each cell once), depth_mm (ZE axial depth a), width_mm (old max chord)}.
    A window ends at a non-horizontal move, a rapid or any vertical move (the
    next feed's idx is not the previous feed's idx + 1), a Z change, or a
    direction change > AE2_DIR_MAX_DEG. Windows are the MINIMAL runs of >= 1 mm
    travel: short feeds (< 1 mm) merge forward until the window reaches 1 mm;
    a move of >= 1 mm is its own window. Task ZG2: a trailing run below 1 mm
    merges into a kept neighbour (last kept before, else first kept after;
    none: ungated in .iso). ae_eff = area/length; a, width_mm as before."""
    windows, tails, iso = [], [], []
    cur = None

    def close(w):
        if w["length_mm"] >= AE2_WINDOW_MM:
            w["ae_eff"] = round(w["area_mm2"] / w["length_mm"], 4)
            windows.append(w)
        else:
            tails.append((w, len(windows)))

    for e in moves:
        link = (cur is not None and e["idx"] == cur["idx"] + 1
                and e["z"] == cur["z"] and e.get("feed") == cur.get("feed")
                and e["dx"] * cur["dx"] + e["dy"] * cur["dy"]
                >= math.cos(math.radians(AE2_DIR_MAX_DEG)))
        if not link:
            if cur is not None:
                close(cur)
            cur = {"idx": e["idx"], "line": e["line"], "end_line": e["line"],
                   "x": e["x"], "y": e["y"], "z": e["z"],
                   "dx": e["dx"], "dy": e["dy"],
                   "area_mm2": e["area_mm2"], "length_mm": e["length_mm"],
                   "a": e["depth_mm"], "width_mm": e["width_mm"],
                   "hist": (None if e.get("hist") is None
                            else e["hist"].copy()),
                   "n_moves": 1, "feed": e.get("feed"),
                   "helix_pitch": e.get("helix_pitch")}
        else:
            cur["idx"] = e["idx"]
            cur["end_line"] = e["line"]
            cur["x"], cur["y"] = e["x"], e["y"]
            cur["dx"], cur["dy"] = e["dx"], e["dy"]
            cur["area_mm2"] += e["area_mm2"]
            cur["length_mm"] += e["length_mm"]
            cur["a"] = max(cur["a"], e["depth_mm"])
            if e.get("hist") is not None:
                cur["hist"] = (e["hist"].copy() if cur["hist"] is None
                               else cur["hist"] + e["hist"])
            cur["width_mm"] = max(cur["width_mm"], e["width_mm"])
            cur["n_moves"] += 1
        if cur["length_mm"] >= AE2_WINDOW_MM:
            close(cur)
            cur = None
    if cur is not None:
        close(cur)
    for w, n in tails:
        tgt = windows[n - 1] if n else (windows[0] if windows else None)
        if tgt is None:
            iso.append(w)
        else:
            tgt["area_mm2"] += w["area_mm2"]
            tgt["length_mm"] += w["length_mm"]
            tgt["n_moves"] += w["n_moves"]
            tgt["a"] = max(tgt["a"], w["a"])
            if w["hist"] is not None:
                tgt["hist"] = (w["hist"] if tgt["hist"] is None
                               else tgt["hist"] + w["hist"])
            tgt["ae_eff"] = round(tgt["area_mm2"] / tgt["length_mm"], 4)
    wins = _Wins(windows)
    wins.iso = iso
    return wins


class _Wins(list):  # task ZG2: ae2 windows; .iso = unjudged sub-1 mm cuts
    pass


def _helix_radius(run):
    """Task ZE2F2: mean radius of a helix run about its centroid (0 if none)."""
    if len(run) < 4:
        return 0.0
    P = np.asarray(run, dtype=float)
    c = P[:, :2].mean(axis=0)
    return float(np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]).mean())


def _helix_pitch(run):
    """Task ZE2F: measured pitch (Z drop per full turn) of a descending feed
    run, or None when it is not a helix (fewer than 4 points, radius under
    0.05 mm - a straight plunge/ramp - or no XY travel)."""
    if len(run) < 4:
        return None
    P = np.asarray(run, dtype=float)
    c = P[:, :2].mean(axis=0)
    r = float(np.hypot(P[:, 0] - c[0], P[:, 1] - c[1]).mean())
    arc = float(np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1])).sum())
    dz = float(P[0, 2] - P[-1, 2])
    if r < 0.05 or arc <= 1e-9 or dz <= 0.0:
        return None
    return round(dz / (arc / (2.0 * math.pi * r)), 4)


def _ae2_engagement_keys(win_recs, dia, design_ae=None, design_stepdown=None,
                         load_rule=None):
    """Task ZE2 (report-only): engagement keys from the ae2 windows. Old keys
    stay untouched.
    - ae2: {n, p50, p95, p99, max} over ae_eff of every window.
    - full_width_slots_ae2: windows with ae_eff >= FULL_WIDTH_FRAC x dia AND
      a > SLOT_AXIAL_MM (a = ZE's axial depth of the window).
    - overload_feeds_ae2: windows with ae_eff > OVERLOAD_WIDTH_MM AND
      a > SLOT_AXIAL_MM (the SE2 merge bar, area form).
    Each with count, total length and worst 10 by ae_eff (line, x, y, z,
    ae_eff, a, old width)."""
    iso = getattr(win_recs, "iso", ())
    def brief(w):
        return {"line": w["line"], "x": w["x"], "y": w["y"], "z": w["z"],
                "ae_eff": w["ae_eff"], "a": round(w["a"], 4),
                "width_mm": w["width_mm"]}

    # task ZE2F: feed classes
    by_feed = {}
    for w in win_recs:
        if w.get("feed"):
            by_feed[w["feed"]] = by_feed.get(w["feed"], 0.0) + w["length_mm"]
    cut_feed = max(by_feed, key=by_feed.get) if by_feed else None

    def entry_feed(w):
        return (cut_feed is not None and w.get("feed") is not None
                and w["feed"] < AE2_ENTRY_FEED_FRAC * cut_feed)

    ref = ((design_ae or DESIGN_AE) * (design_stepdown or DESIGN_STEPDOWN)
           * (cut_feed or 1.0))
    for w in win_recs:   # task ZE2L: additive per-window key
        w["load"] = round(w["ae_eff"] * w["a"] * (w.get("feed") or cut_feed
                                                  or 0.0) / ref, 4)

    def allowed(w):
        hp = w.get("helix_pitch")
        return (hp is not None and w["a"] <= hp + AE2_PITCH_TOL
                and w["load"] <= AE2_FLOOR_LOAD_MAX)

    # task ZE2D: full_width_depth per window (then drop the histograms)
    for w in win_recs:
        h = w.pop("hist", None)
        fwd = 0.0
        if h is not None and w["length_mm"] > 0:
            cum = np.cumsum(h[::-1])[::-1]       # area removed >= each bin edge
            ok = np.nonzero(cum / w["length_mm"] >= FULL_WIDTH_FRAC * dia)[0]
            if ok.size:
                fwd = round(float(ok.max()) * FWD_BIN_MM, 3)
        w["full_width_depth"] = fwd
    fws = sorted([w for w in win_recs
                  if w["ae_eff"] >= FULL_WIDTH_FRAC * dia
                  and w["a"] > SLOT_AXIAL_MM],
                 key=lambda w: (-w["ae_eff"], -w["a"]))
    ovl = sorted([w for w in win_recs
                  if w["ae_eff"] > OVERLOAD_WIDTH_MM and w["a"] > SLOT_AXIAL_MM],
                 key=lambda w: (-w["ae_eff"], -w["a"]))
    fw_cut = [w for w in fws if not entry_feed(w)]
    fw_ent = [w for w in fws if entry_feed(w)]
    fw_ent_bad = [w for w in fw_ent if not allowed(w)]

    def fw_class(ws):
        return {"count": len(ws),
                "total_length_mm": round(sum(w["length_mm"] for w in ws), 1),
                "worst": [dict(brief(w), feed=w.get("feed"),
                               helix_pitch=w.get("helix_pitch"))
                          for w in ws[:10]]}
    def bands(ws):
        out = {}
        for lo, hi, name in ((0.0, 0.5, "<0.5"), (0.5, 2.0, "0.5-2"),
                             (2.0, 5.0, "2-5"), (5.0, 1e9, ">5")):
            sel = [w for w in ws if lo <= w["full_width_depth"] < hi]
            out[name] = {"count": len(sel), "total_length_mm":
                         round(sum(w["length_mm"] for w in sel), 1)}
        return out
    return {
        "full_width_depth_bands_ae2": {
            "cutting_feed": bands([w for w in fws if not entry_feed(w)]),
            "entry_feed": bands([w for w in fws if entry_feed(w)])},
        "ae2_cutting_feed": cut_feed,
        "full_width_slots_ae2_cutting_feed": fw_class(fw_cut),
        "full_width_slots_ae2_entry_feed": dict(
            fw_class(fw_ent), allowed_helix_bottom=len(fw_ent) - len(fw_ent_bad),
            not_allowed=fw_class(fw_ent_bad)),
        # the roughing target (report-only): 0 full-width at cutting feed and
        # no entry-feed full-width beyond the bounded helix-bottom exception
        "roughing_target_ae2": {
            "fw_cutting_feed": len(fw_cut),
            "fw_entry_not_allowed": len(fw_ent_bad),
            "met": not fw_cut and not fw_ent_bad},
        "ae2": _engage_stats([w["ae_eff"] for w in win_recs]),
        **({"ae2_isolated_sub1mm": {
            "count": len(iso), "worst_ae_eff_mm": round(min(max(
                [w["area_mm2"] / w["length_mm"] for w in iso
                 if w["length_mm"] > 0] or [0.0]), dia), 4)}} if iso else {}),
        "full_width_slots_ae2": {
            "count": len(fws),
            "total_length_mm": round(sum(w["length_mm"] for w in fws), 1),
            # worst 10 by ae_eff (line, XY, Z, ae_eff, a, old width)
            "worst": [brief(w) for w in fws[:10]],
        },
        "overload_feeds_ae2": {
            "ae_eff_above_mm": round(OVERLOAD_WIDTH_MM, 4),
            "count": len(ovl),
            "total_length_mm": round(sum(w["length_mm"] for w in ovl), 1),
            "worst": [brief(w) for w in ovl[:10]],
        },
        # task ZE2L: the same windows minus allowed helix-bottom floor turns
        **({"overload_feeds_ae2_load": {
            "ae_eff_above_mm": round(OVERLOAD_WIDTH_MM, 4),
            "load_max": AE2_FLOOR_LOAD_MAX, "raw_count": len(ovl),
            "floor_circles_allowed": sum(1 for w in ovl if allowed(w)),
            "count": sum(1 for w in ovl if not allowed(w)),
            "total_length_mm": round(sum(w["length_mm"] for w in ovl
                                         if not allowed(w)), 1),
            "worst": [dict(brief(w), load=w["load"])
                      for w in ovl if not allowed(w)][:10],
        }} if (LOAD_RULE if load_rule is None else load_rule) else {}),
    }


def _ze2b_chord(a, dia):
    """Task ZE2B: the ball's chord at axial depth a: c(a) = 2*sqrt(a*(dia-a))."""
    return 2.0 * math.sqrt(max(a, 0.0) * max(dia - a, 0.0))


def _ze2b_windows(moves, dia):
    """Task ZE2B: merge consecutive ball cutting-feed moves (no rapid between,
    direction change <= AE2_DIR_MAX_DEG on u, ANY Z change) into ZE2's minimal
    windows of >= AE2_WINDOW_MM 3D travel (short tail dropped). vol = mm^3
    removed (live-stock telescope), a = max stock_top - tip over engaged cells
    (clipped [0,R]), ext/dext = extent perp to u / bbox diagonal."""
    windows = []
    cur = None

    def close(w):
        if w["length_3d"] >= AE2_WINDOW_MM:
            w["ae_eq"] = round(w["vol"] / w["length_3d"] / w["a"], 4) if w["a"] > 0.0 else 0.0
            w["w_plan"] = round(min(w["dext"] if w["descent"] else w["ext"], dia), 4)
            w["c_a"] = round(_ze2b_chord(w["a"], dia), 4)
            w["theta"] = round(math.degrees(math.acos(1.0 - w["a"] / (dia / 2.0))), 3)
            windows.append(w)

    for e in moves:
        if not (cur is not None and e["idx"] == cur["idx"] + 1
                and e["dx"] * cur["dx"] + e["dy"] * cur["dy"]
                >= math.cos(math.radians(AE2_DIR_MAX_DEG))):
            if cur is not None:
                close(cur)
            cur = dict(e, n_moves=1, end_line=e["line"])
        else:
            cur.update(idx=e["idx"], end_line=e["line"], x=e["x"], y=e["y"])
            cur["length_3d"] += e["length_3d"]
            cur["horiz"] += e["horiz"]
            cur["vol"] += e["vol"]
            cur["a"] = max(cur["a"], e["a"])
            cur["ext"] = max(cur["ext"], e["ext"])
            cur["dext"] = max(cur["dext"], e["dext"])
            cur["n_moves"] += 1
        cur["descent"] = cur["horiz"] < ZE2B_DESCENT_FRAC * cur["length_3d"]
        if cur["length_3d"] >= AE2_WINDOW_MM:
            close(cur)
            cur = None
    if cur is not None:
        close(cur)
    return windows


def _ze2b_keys(wins, dia, engage_max):
    """Task ZE2B (report-only): engagement.ze2b for ball programs, with ZE2F's
    cutting/entry-feed split; full_width = not descent AND a >= 0.05 AND
    w_plan >= FULL_WIDTH_FRAC x c(a); overload = ae_eq > engage_max."""
    def brief(w):
        return {"line": w["line"], "x": w["x"], "y": w["y"], "z": w["z"],
                "a": round(w["a"], 4), "theta": w["theta"],
                "w_plan": w["w_plan"], "c_a": w["c_a"], "ae_eq": w["ae_eq"],
                "length_3d": round(w["length_3d"], 3), "feed": w["feed"],
                "descent": w["descent"]}

    fw = sorted([w for w in wins if not w["descent"] and w["a"] >= 0.05
                 and w["w_plan"] >= FULL_WIDTH_FRAC * w["c_a"]],
                key=lambda w: -(w["w_plan"] / max(w["c_a"], 1e-9)))
    ov = sorted([w for w in wins if engage_max is not None
                 and w["ae_eq"] > engage_max], key=lambda w: -w["ae_eq"])
    by_feed = {}
    for w in wins:
        if w.get("feed"):
            by_feed[w["feed"]] = by_feed.get(w["feed"], 0.0) + w["length_3d"]
    cut_feed = max(by_feed, key=by_feed.get) if by_feed else None
    fw_cut = [w for w in fw if cut_feed is None or (w.get("feed") is not None
                and w["feed"] >= AE2_ENTRY_FEED_FRAC * cut_feed)]

    def cls(ws):
        return {"count": len(ws),
                "length_mm": round(sum(w["length_3d"] for w in ws), 1)}
    return {
        "n_windows": len(wins),
        "full_width": dict(cls(fw), worst=[brief(w) for w in fw[:10]]),
        "overload": dict(cls(ov), worst=[brief(w) for w in ov[:10]]),
        "ae_eq": _engage_stats([w["ae_eq"] for w in wins]),
        "w_plan_over_chord": _engage_stats([w["w_plan"] / w["c_a"]
                                            for w in wins if w["c_a"] > 0.0]),
        "a": _engage_stats([w["a"] for w in wins]),
        "descent": cls([w for w in wins if w["descent"]]),
        "ae2b_cutting_feed": cut_feed,
        "full_width_cutting_feed": cls(fw_cut),
        "full_width_entry_feed": cls([w for w in fw if w not in fw_cut]),
    }


def _axial_report(raw, tool="flat"):
    """Task ZA/ZB: summarize axial plunges (descents steeper than
    MAX_RAMP_DEG) that removed more than the tool's floor under its bottom
    (flat/bull: AXIAL_FLOOR; ball: BALL_AXIAL_FLOOR):
    {count, max_depth_mm, first_line, worst_xy, floor_mm} - floor_mm is per
    tool type."""
    floor = BALL_AXIAL_FLOOR if tool == "ball" else AXIAL_FLOOR
    ax = [e for e in raw if e["depth_mm"] > floor]
    if not ax:
        return {"count": 0, "max_depth_mm": 0.0, "first_line": None,
                "worst_xy": None, "floor_mm": floor}
    worst = max(ax, key=lambda e: e["depth_mm"])
    return {"count": len(ax), "max_depth_mm": worst["depth_mm"],
            "first_line": min(e["line"] for e in ax),
            "worst_xy": [worst["x"], worst["y"]], "floor_mm": floor}


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
             stickout=None, engage_max=None, ramp_angle=3.0,
             engage_report=False, idx_offset=0):
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
    engage_report: opt-in (task CP): measure and report engagement stats even
                when engage_max is None (no threshold, so nothing is flagged);
                the engagement block is present in the report with
                threshold_mm=None, count=0. Default False = off (unchanged).
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
    # part grid bounds in mm: cells outside them are never evaluated, so a
    # move whose footprint (XY +- tool radius) leaves the grid is unjudged
    gxmin, gxmax = x0, x0 + nx * cell
    gymin, gymax = y0, y0 + ny * cell
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
    # task SP2: for a ball, the exact dz(d) op chain is replayed in-place on
    # one scratch buffer per sample (same ops, same order, same dtype) so the
    # per-sample closure allocates nothing.
    ball_surf = tool == "ball"
    # task ZA/ZB: bottom disk radius for the axial plunge check -- the flat
    # part of the tool's bottom: R for flat, R - corner for bull; a ball has
    # no flat bottom: its contact disk at the end point is the tool's FULL
    # radius R around the end XY, and the removed depth there is measured
    # against the spherical surface z1 + dz(d) (deepest removed column)
    bottom_r = R - corner if tool == "bull" else R
    engage_track = engage_max is not None or engage_report
    k = int(math.ceil(R / cell)) + 1  # +1 so the padded engagement mask fits
    surf_buf = np.empty((2 * k + 1, 2 * k + 1)) if ball_surf else None
    zb_on = engage_track and tool == "ball"  # task ZE2B (ball only)
    zb_moves = []
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
    engage_spikes = []  # list of dicts: {line, x, y, engagement_mm, kind}
    engage_max_seen = 0.0
    engage_count = 0
    engage_horiz = []   # per-move max chord mm: horizontal cuts (|dz|<=1e-6)
    engage_entry = []   # per-move max chord mm: descending entries into stock
    # task ZE: per engaging cutting move raw records {line, x, y, z, kind,
    # width_mm (max chord), depth_mm (axial depth removed above the tip),
    # length_mm, time_s at the move's feed} - report-only, merged raw in
    # parallel so serial/jobs results agree exactly
    hw_records = []
    # task ZE2: per horizontal feed move raw records {idx (global move index),
    # line, x, y, z, dx, dy (unit chord direction), length_mm, area_mm2 (plan
    # area of cells this move removes material from, cells counted once),
    # depth_mm (a), width_mm (old max chord)} - merged raw in parallel so
    # serial/jobs results agree exactly; windows built from the full list
    ae2_moves = []
    desc_run = []  # task ZE2F: points of the descending feed run just made
    hp_carry = None  # task ZE2F2: (pitch, z, feed) carried along the entry-feed run at the helix bottom
    # plunge tracking
    plunge_flags = []  # list of dicts: {line, x, y, z, angle_deg, depth_mm}
    plunge_count = 0
    # axial plunge tracking (task ZA/ZB): every descending feed move steeper
    # than MAX_RAMP_DEG that removed >0 stock under the tool's bottom disk
    # (flat/bull: flat bottom, ball: full disk vs sphere), with its deepest
    # removed column (raw; the report filters by the tool's floor)
    axial_raw = []  # list of dicts: {line, x, y, depth_mm}
    # footprint-outside-grid tracking (cells outside the grid are unjudged)
    outside_grid = 0
    first_outside_line = None
    bsb_raw = []  # task ZG1: {line, x, y, depth} below the stock bottom

    for mi, mv in enumerate(resolved):
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
        # footprint check: any move (rapid or cutting) whose tool footprint
        # (XY +- R) leaves the part grid counts -- cells outside the grid
        # are never simulated, so such a move is only partially judged.
        # Air moves outside the STOCK box are NOT exempt unless they stay
        # inside the grid.
        fxmin = min(s[0] for s in samples) - R
        fxmax = max(s[0] for s in samples) + R
        fymin = min(s[1] for s in samples) - R
        fymax = max(s[1] for s in samples) + R
        if (fxmin < gxmin - 1e-9 or fxmax > gxmax + 1e-9 or
                fymin < gymin - 1e-9 or fymax > gymax + 1e-9):
            outside_grid += 1
            if first_outside_line is None:
                first_outside_line = mv["line"]
        cutting = mv["motion"] in ("G1", "G2", "G3")
        if cutting and min(z1, cur[2]) < szmin - 1e-9:  # task ZG1
            bz, bxy = ((z1, [x1, y1]) if z1 <= cur[2] else (cur[2], cur[:2]))
            bsb_raw.append({"line": mv["line"], "x": bxy[0], "y": bxy[1],
                            "depth": szmin - bz})
        move_collided = False
        move_over_flute = False
        move_shank = False
        move_holder = False
        move_max_engage = 0.0
        # task ZE: deepest column removed above the tool surface under the
        # footprint during this move (max over removed cells of
        # stock_before - cut surface)
        move_max_depth = 0.0
        move_hist = None  # task ZE2D: histogram of removed cell heights
        # task ZE2: plan area of the cells this move removes material from
        # (cells counted once: stock update makes later samples cut 0 there)
        move_area = 0.0
        # task ZE2B: engagement vs the stock BEFORE this move stamps it (copy)
        zb_vol = zb_a = zb_ext = zb_dext = 0.0
        zb_pre = None
        if cutting and zb_on:
            bx = np.asarray(samples)
            zb_ilo = max(0, int(math.floor((bx[:, 0].min() - x0) / cell)) - k)
            zb_ihi = min(nx, int(math.floor((bx[:, 0].max() - x0) / cell)) + k + 1)
            zb_jlo = max(0, int(math.floor((bx[:, 1].min() - y0) / cell)) - k)
            zb_jhi = min(ny, int(math.floor((bx[:, 1].max() - y0) / cell)) + k + 1)
            if zb_ilo < zb_ihi and zb_jlo < zb_jhi:
                zb_pre = stock[zb_jlo:zb_jhi, zb_ilo:zb_ihi].copy()
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
        # task ZA: axial plunge -- a straight downward feed move (G1,
        # |dXY| <= 1e-6, dz < 0). Deepest stock column removed under the
        # tool's flat bottom disk (radius bottom_r), read BEFORE this move
        # cuts: depth = max(stock - (z1 + dz(d))) over cells in the disk.
        axial_depth = 0.0
        # horizontal path length: the chord for G1, the arc length R*|sweep|
        # for a G17 helical G2/G3 (a full-circle helix has a zero chord and
        # would otherwise read as 90 deg)
        horiz = math.hypot(x1 - cur[0], y1 - cur[1])
        if mv["motion"] in ("G2", "G3") and mv.get("arc") \
                and mv["arc"][3] == 2:
            horiz = mv["arc"][4] * abs(mv["arc"][6])
        if (cutting and mv["motion"] in ("G1", "G2", "G3") and z1 < cur[2]
                and math.degrees(math.atan2(cur[2] - z1, horiz))
                > MAX_RAMP_DEG):
            ia = int(math.floor((x1 - x0) / cell))
            ja = int(math.floor((y1 - y0) / cell))
            ilo, ihi = max(0, ia - k), min(nx, ia + k + 1)
            jlo, jhi = max(0, ja - k), min(ny, ja + k + 1)
            if ilo < ihi and jlo < jhi:
                dxa = xs[ilo:ihi] - x1
                dya = ys[jlo:jhi] - y1
                da = np.hypot(dxa, dya[:, None])
                win_a = stock[jlo:jhi, ilo:ihi]
                keep = (da <= bottom_r + 1e-9) & np.isfinite(win_a)
                if keep.any():
                    axial_depth = float(np.max(win_a[keep] - (z1 + dz(da))[keep]))
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
                    dd = np.hypot(xs[slo:shi] - sx, (ys[tlo:thi] - sy)[:, None])
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
                        dd = np.hypot(xs[slo:shi] - sx, (ys[tlo:thi] - sy)[:, None])
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
            d = np.hypot(gx[None, :], gy[:, None])
            msk = d <= R + 1e-9
            if window is not None:
                msk &= window[jlo:jhi, ilo:ihi]
            if not msk.any():
                continue
            if ball_surf:
                # exact dz(d) chain into scratch, then sz + dz (same ops)
                t = surf_buf[:gy.size, :gx.size]
                np.multiply(d, d, out=t)
                np.subtract(R * R, t, out=t)
                np.maximum(t, 0.0, out=t)
                np.sqrt(t, out=t)
                np.subtract(R, t, out=t)
                np.add(sz, t, out=t)
                newv = np.where(msk, t, np.inf)
            else:
                newv = np.where(msk, sz + dz(d), np.inf)
            cut = win - newv
            # task SP2: outside msk newv is +inf so cut is -inf and the clip
            # to >= 0 yields the same 0.0 the masked where wrote there
            removed = float(np.sum(np.clip(cut, 0.0, None)))
            if cutting and engage_track:
                # task ZE2: cells this sample actually removes (finite positive
                # cut height); each cell is counted at most once per move since
                # the stock update drops it to the cut surface below
                nrem = int(np.count_nonzero(cut > REMOVE_EPS))
                move_area += nrem * cell * cell
                if nrem:
                    hb = np.minimum((cut[cut > REMOVE_EPS] / FWD_BIN_MM)
                                    .astype(np.int64), FWD_NBINS - 1)
                    hh = np.bincount(hb, minlength=FWD_NBINS).astype(np.uint32)
                    move_hist = hh if move_hist is None else move_hist + hh
            if cutting and zb_on:
                # task ZE2B: vol = live cut (telescopes, each cell once); a/ext
                # vs the pre-move snapshot where r = stock - z_b > 0.01
                cb = msk & np.isfinite(cut) & (cut > REMOVE_EPS)
                if cb.any():
                    zb_vol += float(cut[cb].sum()) * cell * cell
                if zb_pre is not None:
                    sub = zb_pre[jlo - zb_jlo:jhi - zb_jlo, ilo - zb_ilo:ihi - zb_ilo]
                    eb = msk & np.isfinite(sub) & (sub - newv > 0.01)
                    if eb.any():
                        zb_a = max(zb_a, float(np.max(sub[eb] - sz)))
                        pu = (dx_t * gx[None, :] + dy_t * gy[:, None])[eb]
                        pv = (-dy_t * gx[None, :] + dx_t * gy[:, None])[eb]
                        zb_ext = max(zb_ext, float(pv.max() - pv.min()))
                        zb_dext = max(zb_dext, math.hypot(float(pu.max() - pu.min()),
                                                        float(pv.max() - pv.min())))
            if cutting and engage_track:
                # task ZE: axial depth at this sample = deepest column of
                # stock removed above the tool surface under the footprint
                # (cut = stock_before - cut surface; -inf outside the disk
                # and over non-finite stock, so a finite max is a column this
                # move actually cuts)
                dmax = float(np.max(cut))
                if np.isfinite(dmax) and dmax > move_max_depth:
                    move_max_depth = dmax
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
                # task SP2: msk_e.any() is implied -- with an empty msk_e the
                # masked max is -inf and the comparison is False either way
                engaged = (float(np.max(np.where(msk_e, win, -np.inf)))
                           > sz + 1e-6)
                # radial engagement: chord width of engaged arc perpendicular to
                # travel (dx_t, dy_t); equivalent radial width = 2*R*sin(theta/2)
                if engaged and engage_track:
                    perp_x, perp_y = -dy_t, dx_t
                    proj = (gx[None, :] * perp_x + gy[:, None] * perp_y)
                    # Measure the chord over the cells THIS move actually cuts:
                    # stock above the tip inside the padded footprint, before
                    # the stock update. Using msk_e alone (or a -inf-filled
                    # window) reads ~2R even for a light side cut.
                    cells = msk_e & (win > sz + 1e-6)
                    if cells.any():
                        cproj = proj[cells]
                        ew = float(cproj.max()) - float(cproj.min())
                    else:
                        ew = np.nan
                    # Finite guard BEFORE the clamp: clamping first would turn
                    # inf into 2R and the guard could never fire.
                    if not np.isfinite(ew):
                        ew = 0.0
                    # Clamp to [0, dia]: the padded mask (R + 0.75*cell) can
                    # make ew slightly exceed the tool diameter.
                    ew = min(max(ew, 0.0), 2.0 * R)
                    if ew > move_max_engage:
                        move_max_engage = ew
                if removed > REMOVE_EPS:
                    stock[jlo:jhi, ilo:ihi] = np.minimum(win, newv)
                if not engaged:
                    air_length += seg_len
            else:  # rapid
                # task SP2: outside msk cut is -inf, never > REMOVE_EPS
                if np.any(cut > REMOVE_EPS):
                    move_collided = True
        if cutting:
            cut_length += length
            if axial_depth > 0.0:
                axial_raw.append({"line": mv["line"], "x": round(x1, 4),
                                  "y": round(y1, 4),
                                  "depth_mm": round(axial_depth, 4)})
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
        # engagement: track the widest measured chord over all cutting moves;
        # flag only those exceeding the threshold. Engaging cuts are bucketed
        # by vertical motion: horizontal (|dz| <= 1e-6, the steady cuts) vs
        # entry (descending: helix/ramp/plunge into stock).
        if cutting and engage_track:
            if move_max_engage > engage_max_seen:
                engage_max_seen = move_max_engage
            dz_mv = z1 - cur[2]
            if move_max_engage > 0.0:
                if abs(dz_mv) <= 1e-6:
                    engage_horiz.append(move_max_engage)
                elif dz_mv < 0.0:
                    engage_entry.append(move_max_engage)
            # task ZE: record radial width AND axial depth for EVERY engaging
            # cutting move (report keys filter to horizontal; raw list merges
            # unchanged under --jobs)
            if move_max_engage > 0.0 or move_max_depth > 0.0:
                feed_ze = mv.get("f")
                hw_records.append({
                    "line": mv["line"],
                    "x": round(x1, 4), "y": round(y1, 4), "z": round(z1, 3),
                    "kind": ("horizontal" if abs(dz_mv) <= 1e-6 else
                           ("entry" if dz_mv < 0.0 else "rising")),
                    "width_mm": round(move_max_engage, 4),
                    "depth_mm": round(max(move_max_depth, 0.0), 4),
                    "length_mm": length,
                    "time_s": (length / (feed_ze if feed_ze and feed_ze > 0
                                        else rapid_feed) * 60.0),
                })
            # task ZE2: EVERY horizontal feed move (even one removing nothing)
            # enters the ae2 window sequence; travel through air at the same Z
            # and direction is real feed length with zero removed area
            if abs(dz_mv) <= 1e-6 and length > 0.0:
                # ZE2F2: the pitch of the helix just made applies to the whole
                # contiguous run at its bottom Z and feed (e.g. a floor circle),
                # not only to the first move after it
                # (bounded: at most one circumference of the helix path,
                # 2*pi*r + AE2_CARRY_EXTRA_MM; beyond that a window is judged
                # as a normal window)
                hp = _helix_pitch(desc_run)
                if hp is not None:
                    hp_carry = [hp, round(z1, 3), mv.get("f"),
                                2.0 * math.pi * _helix_radius(desc_run)
                                + AE2_CARRY_EXTRA_MM, length]
                elif (hp_carry is not None and hp_carry[1] == round(z1, 3)
                      and hp_carry[2] == mv.get("f")
                      and hp_carry[4] + length <= hp_carry[3]):
                    hp = hp_carry[0]
                    hp_carry[4] += length
                else:
                    hp_carry = None
                ae2_moves.append({
                    "feed": mv.get("f"),
                    "helix_pitch": hp,
                    "idx": mi + idx_offset,
                    "line": mv["line"],
                    "x": round(x1, 4), "y": round(y1, 4),
                    "z": round(z1, 3),
                    "dx": dx_t, "dy": dy_t,
                    "length_mm": length,
                    "area_mm2": move_area,
                    "hist": (None if move_hist is None
                             else move_hist.astype(np.float32) * np.float32(cell * cell)),
                    "depth_mm": round(max(move_max_depth, 0.0), 4),
                    "width_mm": round(move_max_engage, 4),
                })
            if zb_on and length > 0.0:
                zb_moves.append({
                    "idx": mi + idx_offset, "line": mv["line"],
                    "x": round(x1, 4), "y": round(y1, 4), "z": round(z1, 3),
                    "dx": dx_t, "dy": dy_t, "length_3d": length,
                    "horiz": horiz,
                    "vol": zb_vol, "a": min(max(zb_a, 0.0), R),
                    "ext": zb_ext, "dext": zb_dext, "feed": mv.get("f"),
                })
            if engage_max is not None and move_max_engage > engage_max:
                engage_count += 1
                engage_spikes.append({
                    "line": mv["line"],
                    "x": round(x1, 4), "y": round(y1, 4),
                    "engagement_mm": round(move_max_engage, 4),
                    "kind": "entry" if dz_mv < -1e-6 else "horizontal"})
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
        # task ZE2F: keep the current descending feed run (a helix entry);
        # any other move ends it (the horizontal move after it reads it first)
        if cutting and z1 < cur[2] - 1e-6:
            if math.hypot(x1 - cur[0], y1 - cur[1]) <= 1e-6:
                desc_run = [(x1, y1, z1)]  # vertical feed-down: helix starts here
            else:
                if not desc_run:
                    desc_run.append((cur[0], cur[1], cur[2]))
                desc_run.append((x1, y1, z1))
        else:
            desc_run = []
        if hp_carry is not None and not (
                cutting and abs(z1 - cur[2]) <= 1e-6
                and round(z1, 3) == hp_carry[1] and mv.get("f") == hp_carry[2]):
            hp_carry = None
        cur = [x1, y1, z1]

    ae2_windows = _ae2_windows(ae2_moves) if engage_track else []
    zb_windows = _ze2b_windows(zb_moves, dia) if zb_on else []
    result = {
        "stock": stock,
        "rapid_collisions": {"count": rapid_collisions,
                            "first_line": first_rapid_line},
        "outside_grid": {"count": outside_grid,
                         "first_line": first_outside_line},
        "below_stock_bottom": _bsb_report(bsb_raw),
        "_bsb_raw": bsb_raw,
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
            # distribution over engaging cuts, per-move max chord mm
            "horizontal": _engage_stats(engage_horiz),
            "entry": _engage_stats(engage_entry),
            # top 10 worst spots (line, XY, value)
            "spikes": sorted(engage_spikes, key=lambda s: s["engagement_mm"],
                             reverse=True)[:10],
            # task ZE (new keys only): axial depth per engaging move
            **_ze_engagement_keys(hw_records, engage_max, dia),
            # task ZE2 (new keys only): AREA-based engagement windows
            **_ae2_engagement_keys(ae2_windows, dia),
        } if engage_track else None,
        # raw per-move width+depth records for exact parallel merging
        "_hw_raw": hw_records,
        # task ZE2: raw per-feed area records + built ae2 windows
        "_ae2_move_raw": ae2_moves,
        "_ae2_raw": ae2_windows,
        "_zb_move_raw": zb_moves,
        "_zb_raw": zb_windows,
        # raw per-bucket values for exact parallel merging (not reported)
        "_engage_raw": {"horizontal": engage_horiz, "entry": engage_entry},
        # task ZA/ZB: failing gate for EVERY tool type at its own floor
        # (flat/bull: AXIAL_FLOOR, ball: BALL_AXIAL_FLOOR) - CLI exit code +
        # connector _check_zmap_gates; floor_mm in the report is per tool
        "axial_plunges": _axial_report(axial_raw, tool),
        "_axial_raw": axial_raw,
        "plunge": {
            "ramp_angle_deg": ramp_angle,
            "count": plunge_count,
            # top 10 deepest spots (line, XY, value)
            "flags": sorted(plunge_flags, key=lambda f: f["depth_mm"],
                           reverse=True)[:10],
        },
    }
    if tool == "ball" and engage_track:
        result["engagement"]["semantics"] = "flat-only, see ze2b"
        result["engagement"]["ze2b"] = _ze2b_keys(zb_windows, dia, engage_max)
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
                    ramp_angle=g["ramp_angle"], engage_report=g["engage_report"],
                    idx_offset=g["spans"][idx].start)


def simulate_parallel(moves, part, cell, x0, y0, stock_box, jobs, tool="flat",
                      dia=6.0, corner=0.0, stock_init=None, window=None,
                      rapid_feed=RAPID_FEED, flute=None, shank_dia=None,
                      holder=None, stickout=None, engage_max=None,
                      ramp_angle=3.0, engage_report=False):
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
                  engage_max=engage_max, ramp_angle=ramp_angle,
                  engage_report=engage_report)
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
        "outside_grid": {
            "count": sum(r["outside_grid"]["count"] for r in results),
            "first_line": min((r["outside_grid"]["first_line"]
                              for r in results
                              if r["outside_grid"]["first_line"]),
                             default=None),
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
             "horizontal": _engage_stats(
                 [v for r in results for v in r["_engage_raw"]["horizontal"]]),
             "entry": _engage_stats(
                 [v for r in results for v in r["_engage_raw"]["entry"]]),
             "spikes": sorted([s for r in results
                              for s in r["engagement"]["spikes"]],
                             key=lambda s: s["engagement_mm"],
                             reverse=True)[:10],
            } if engage_max is not None or engage_report else None),
        "plunge": {
            "ramp_angle_deg": ramp_angle,
            "count": sum(r["plunge"]["count"] for r in results),
            "flags": sorted([f for r in results
                            for f in r["plunge"]["flags"]],
                           key=lambda f: f["depth_mm"], reverse=True)[:10],
        },
        "axial_plunges": _axial_report(
            [e for r in results for e in r["_axial_raw"]], tool),
        "_axial_raw": [e for r in results for e in r["_axial_raw"]],
        "below_stock_bottom": _bsb_report(
            [e for r in results for e in r["_bsb_raw"]]),
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
    # task ZE: merge raw width+depth records per move (each move lives in
    # exactly one chunk), then derive the new keys with the same builder as
    # serial -> jobs result identical to serial
    hw_all = [r for res in results for r in res["_hw_raw"]]
    combined["_hw_raw"] = hw_all
    # task ZE2: merge raw per-feed area records (each move lives in exactly
    # one chunk, global idx preserved), rebuild windows and keys with the same
    # builders as serial -> jobs result identical to serial
    ae2_all = [e for res in results for e in res["_ae2_move_raw"]]
    ae2_windows = _ae2_windows(ae2_all)
    combined["_ae2_move_raw"] = ae2_all
    combined["_ae2_raw"] = ae2_windows
    zb_all = [e for res in results for e in res["_zb_move_raw"]]
    combined["_zb_move_raw"] = zb_all
    combined["_zb_raw"] = _ze2b_windows(zb_all, dia) if zb_all else []
    if tool == "ball" and combined["engagement"] is not None:
        combined["engagement"]["semantics"] = "flat-only, see ze2b"
        combined["engagement"]["ze2b"] = _ze2b_keys(combined["_zb_raw"], dia,
                                                    engage_max)
    if combined["engagement"] is not None:
        combined["engagement"].update(
            _ze_engagement_keys(hw_all, engage_max, dia))
        combined["engagement"].update(
            _ae2_engagement_keys(ae2_windows, dia))
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

def _bsb_report(raw):  # task ZG1: below_stock_bottom block from raw records
    w = max(raw, key=lambda e: e["depth"], default=None)
    return {"count": len(raw), "max_depth": w["depth"] if w else 0.0,
            "worst_xy": [w["x"], w["y"]] if w else None,
            "first_line": min((e["line"] for e in raw), default=None)}


def analyze(stock, part, cell, x0, y0, restrict=None):
    ny, nx = part.shape
    valid = np.isfinite(stock)
    hit = getattr(part, "hit", None)
    bottom = float(np.min(part))
    footprint = part > bottom + 1e-9
    mask = valid & footprint
    if restrict is not None:
        mask &= restrict
    depth = part - stock
    gouge_mask = (valid & hit if hit is not None else valid) \
        & (stock < part - GOUGE_TOL)
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
        "part_mask": "present" if hit is not None else "missing",
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

class PartField(np.ndarray): hit = None  # ndarray + .hit bool mask (task ZG1)


def load_part(path):
    part = np.load(path)
    sidecar = re.sub(r"\.npy$", "", path) + ".json"
    with open(sidecar) as f:
        meta = json.load(f)
    tess = meta.get("tess_tol")
    if tess is None or float(tess) > 0.02:
        raise ValueError(
            "part sidecar %s tess_tol is missing or > 0.02 mm (got %r): "
            "vertical walls carry unbounded chord error and the judgement "
            "would be silently optimistic. Regenerate the heightfield with "
            "TESS_TOL=0.01." % (sidecar, tess))
    part = part.view(PartField)
    if os.path.exists(hp := re.sub(r"\.npy$", "", path) + ".hit.npy"):
        part.hit = np.load(hp)
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
    global DESIGN_AE, DESIGN_STEPDOWN, LOAD_RULE   # task ZE2L: read by _ae2_engagement_keys
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
                   help="speed option: only cells within 2 mm of steep walls "
                        "are simulated and judged; gouges and every other "
                        "check outside the window are NOT judged; never use "
                        "for a gate or a verdict")
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
                       "--engage-max is not set (roughing), the engagement "
                       "threshold is 1.2 x this value. Finishing passes an "
                       "explicit --engage-max (1.5 x stepover) instead. "
                       "Default off.")
    p.add_argument("--engage-max", dest="engage_max", type=float, default=None,
                  help="radial engagement threshold mm: flag cutting moves whose "
                       "max engagement exceeds this (chord width of engaged arc "
                       "perpendicular to travel). Roughing: 1.2 x optimal load; "
                       "finishing passes an explicit value (1.5 x stepover). "
                       "Default: 1.2 x --optimal-load when that is given, "
                       "else off.")
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
    p.add_argument("--strict", action="store_true",
                   help="task CP: judge a posted program against the "
                        "supported subset (G17 I/J and R arcs, no cutter "
                        "comp, no canned cycles, no other planes, one home "
                        "line at the end). Anything else exits non-zero with "
                        "'unsupported: <code> at line N' and the full list in "
                        "the check json \"unsupported\". Default off: "
                        "behaviour is exactly as before")
    p.add_argument("--engage-report", dest="engage_report",
                   action="store_true",
                   help="report engagement stats (max/percentiles) without a "
                        "threshold: nothing is flagged (report-only). "
                        "Default off")
    p.add_argument("--load-rule", dest="load_rule", action="store_true",
                   help="task ZE2L: also report overload_feeds_ae2_load "
                        "(helix-bottom floor turns allowed by load <= 1.2 and "
                        "a <= pitch + 0.05); off keeps the JSON unchanged")
    p.add_argument("--design-ae", dest="design_ae", type=float,
                   default=DESIGN_AE,
                   help="task ZE2L: design radial engagement mm for the "
                        "window load ratio (default 2.032)")
    p.add_argument("--design-stepdown", dest="design_stepdown", type=float,
                   default=DESIGN_STEPDOWN,
                   help="task ZE2L: design stepdown mm for the window load "
                        "ratio (default 19.05)")
    p.add_argument("--ae2-dump", dest="ae2_dump", default=None,
                   help="task ZE2 (report-only extra): write the raw ae2 "
                        "window records (res[_ae2_raw]) to this JSON path in "
                        "addition to the report; changes nothing else")
    p.add_argument("--ae2b-dump", dest="ae2b_dump", default=None,
                   help="task ZE2B (report-only extra, ball): write the raw "
                        "ze2b window records to this JSON path")
    args = p.parse_args(argv)

    gtext = None
    if args.strict:
        # task CP: judge every line before anything else; unsupported codes
        # fail the run with the first offender and the full list in json
        with open(args.gcode) as f:
            gtext = f.read()
        findings = strict_check(gtext)
        if findings:
            report = _sanitize({"gcode": os.path.abspath(args.gcode),
                                "strict": True, "unsupported": findings})
            text = json.dumps(report, indent=2)
            if args.out_json:
                with open(args.out_json, "w") as f:
                    f.write(text + "\n")
            else:
                print(text)
            first = findings[0]
            print("unsupported: %s at line %d"
                  % (first["code"], first["line"]), file=sys.stderr)
            return 1

    # Derive engage_max from optimal_load when not explicitly given
    # (roughing: warn above 1.2 x optimal load; finishing passes an explicit
    # --engage-max of 1.5 x stepover)
    DESIGN_AE, DESIGN_STEPDOWN = args.design_ae, args.design_stepdown
    LOAD_RULE = args.load_rule
    engage_max = args.engage_max
    if engage_max is None and args.optimal_load is not None:
        engage_max = 1.2 * args.optimal_load

    if args.stock is None and not args.stock_in:
        p.error("--stock is required unless --stock-in provides the stock state")

    if args.tool == "ball" and abs(args.corner - args.dia / 2) > 1e-9:
        args.corner = args.dia / 2
    if args.tool == "bull" and not (0 < args.corner < args.dia / 2):
        p.error("--corner must satisfy 0 < corner < dia/2 for a bull nose")

    if gtext is None:
        with open(args.gcode) as f:
            gtext = f.read()
    moves = parse_gcode(gtext, strict=args.strict)
    if args.comp_radius > 0:
        moves = apply_cutter_comp(resolve_moves(moves), args.comp_radius)
    try:
        part, cell, x0, y0 = load_part(args.part)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    window = steep_window(part, cell) if args.window else None

    stock_init = None
    if args.stock_in:
        stock_init = np.load(args.stock_in)
    # task ZG1b: the true stock bottom travels through chains via the stock
    # sidecar's "stock_box" key (never nanmin of the remaining grid)
    side_box = None
    if args.stock_in and os.path.exists(si := os.path.splitext(args.stock_in)[0] + ".json"):
        with open(si) as fh:
            side_box = json.load(fh).get("stock_box")
        side_box = tuple(map(float, side_box)) if side_box else None
    if args.stock is not None:
        if side_box and any(abs(a - b) > 1e-6 for a, b in zip(args.stock, side_box)):
            print("error: --stock box %s and --stock-in sidecar stock_box %s disagree"
                  " by more than 1e-6 mm" % (list(args.stock), list(side_box)), file=sys.stderr)
            return 1
        stock_box = tuple(args.stock)
    else:
        # Derive the box from the saved state's finite cells.
        jj, ii = np.where(np.isfinite(stock_init))
        if jj.size == 0:
            p.error("--stock-in file has no finite cells")
        stock_box = (x0 + ii.min() * cell, x0 + (ii.max() + 1) * cell,
                    y0 + jj.min() * cell, y0 + (jj.max() + 1) * cell,
                    # unknown bottom = -inf: the gate can never fire on a guess
                    float(side_box[4]) if side_box else float("-inf"),
                    float(np.nanmax(stock_init)))
    # --stock-out records this ORIGINAL box; --stock wins over the sidecar
    orig_box = tuple(args.stock) if args.stock is not None else side_box
    # a judge must never silently judge less than the whole stock: the part
    # grid has to cover the stock box (within half a cell per side), or the
    # moves out there are unjudged. No option to skip this.
    gxmin, gxmax = x0, x0 + part.shape[1] * cell
    gymin, gymax = y0, y0 + part.shape[0] * cell
    half = cell / 2.0
    if (stock_box[0] < gxmin - half or stock_box[1] > gxmax + half or
            stock_box[2] < gymin - half or stock_box[3] > gymax + half):
        print("error: stock box [X %.3f..%.3f, Y %.3f..%.3f] extends beyond "
              "the part grid [X %.3f..%.3f, Y %.3f..%.3f] (cell %.3f mm) by "
              "more than half a cell -- moves over the uncovered stock would "
              "be silently unjudged. Regenerate the part heightfield with "
              "enough PAD to cover stock + tool radius." % (
                  stock_box[0], stock_box[1], stock_box[2], stock_box[3],
                  gxmin, gxmax, gymin, gymax, cell), file=sys.stderr)
        return 1
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
                               ramp_angle=args.ramp_angle,
                               engage_report=args.engage_report)
    else:
        res = simulate(moves, part, cell, x0, y0, stock_box,
                       tool=args.tool, dia=args.dia, corner=args.corner,
                       stock_init=stock_init, window=window,
                       rapid_feed=args.rapid_feed, flute=args.flute,
                       shank_dia=args.shank_dia,
                       holder=holder_segs, stickout=holder_stick,
                       engage_max=engage_max, ramp_angle=args.ramp_angle,
                       engage_report=args.engage_report)

    report = {
        "gcode": os.path.abspath(args.gcode),
        "part": os.path.abspath(args.part),
        "tool": {"type": args.tool, "dia": args.dia, "corner": args.corner},
        "stock_box": [float(v) for v in stock_box],
        "part_grid": [gxmin, gxmax, gymin, gymax],
        "stock_in": os.path.abspath(args.stock_in) if args.stock_in else None,
        "holder": _holder_report(args, holder_name, holder_stick),
        "cell": cell,
        "window": ("speed option: only cells within 2 mm of steep walls are "
                   "simulated and judged; gouges and every other check outside "
                   "the window are NOT judged; never use for a gate or a "
                   "verdict" if args.window else None),
        "gouges": res["gouges"],
        "part_mask": res["part_mask"],
        "below_stock_bottom": res["below_stock_bottom"] if orig_box else {
            "status": "unknown", "count": 0, "max_depth": 0.0, "worst_xy": None,
            "first_line": None, "reason": "stock bottom check NOT done: no "
            "--stock and no stock_box in the --stock-in sidecar", "next_step":
            "pass --stock or regenerate the stock file with this version"},
        "outside_grid": res["outside_grid"],
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
        "axial_plunges": res["axial_plunges"],
        "warnings": {
            "engagement": res["engagement"],
            "plunge": res["plunge"],
        },
    }
    if args.strict:
        report["strict"] = True
        report["unsupported"] = []
    report = _sanitize(report)
    text = json.dumps(report, indent=2)
    if args.out_json:
        with open(args.out_json, "w") as f:
            f.write(text + "\n")
    else:
        print(text)
    if args.ae2_dump:
        # task ZE2 report-only extra: raw ae2 windows (line/end_line span,
        # ae_eff, a, old width, length) for post-hoc per-line analysis
        with open(args.ae2_dump, "w") as f:
            json.dump(_sanitize(res["_ae2_raw"]), f, indent=1)
    if args.ae2b_dump:
        with open(args.ae2b_dump, "w") as f:
            json.dump(_sanitize(res.get("_zb_raw", [])), f, indent=1)
    if args.stock_out:
        np.save(args.stock_out, res["stock"])
        if orig_box is not None:  # the ORIGINAL box; merge existing sidecar keys
            sc = os.path.splitext(args.stock_out)[0] + ".json"
            meta = {}
            if os.path.exists(sc):
                with open(sc) as f:
                    meta = json.load(f)
            meta["stock_box"] = [float(v) for v in orig_box]
            with open(sc, "w") as f:
                json.dump(meta, f)
    if args.png:
        ok = write_png(res["stock"], part, cell, x0, y0, args.png)
        if not ok:
            print("PNG skipped (matplotlib unavailable)", file=sys.stderr)
    if res["outside_grid"]["count"] > 0:
        print("error: %d move(s) have a tool footprint (XY +- %.3f mm) "
              "outside the part grid [X %.3f..%.3f, Y %.3f..%.3f] (first "
              "line %s): cells outside the grid are unjudged, so the whole "
              "toolpath was never judged. Fix the heightfield (PAD) or the "
              "toolpath." % (
                  res["outside_grid"]["count"], args.dia / 2.0,
                  gxmin, gxmax, gymin, gymax,
                  res["outside_grid"]["first_line"]), file=sys.stderr)
        return 1
    if (bs := res["below_stock_bottom"])["count"] > 0:
        print("error: %d cutting move(s) drive the tip below the stock "
              "bottom Z %.3f (max %.3f mm below at XY %s, first line %s)"
              % (bs["count"], stock_box[4], bs["max_depth"],
                 bs["worst_xy"], bs["first_line"]), file=sys.stderr)
        return 1
    ap = res["axial_plunges"]
    if ap["count"] > 0:
        # task ZA/ZB: axial plunges FAIL for EVERY tool type at its own
        # floor (flat/bull: AXIAL_FLOOR, ball: BALL_AXIAL_FLOOR)
        wx = ap["worst_xy"] or [float("nan"), float("nan")]
        print("error: %d axial plunge(s): descending feed steeper than %.0f "
              "deg driving the %s tool deeper than its %.3f mm floor into "
              "stock under its bottom (max %.3f mm at XY %.3f, %.3f, first "
              "line %s)" % (
                  ap["count"], MAX_RAMP_DEG, args.tool, ap["floor_mm"],
                  ap["max_depth_mm"], wx[0], wx[1],
                  ap["first_line"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
