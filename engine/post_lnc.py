"""Neutral / engine move list -> James's SyilCNC LNCv2 G-code (post_lnc).

The engine's neutral moves (mm, ``G0``/``G1`` with explicit X/Y/Z/F words as
written by :func:`engine.gcode.moves_to_gcode`) are re-posted into the format
documented in ``docs/lnc5800_post_spec.md`` for James's LNC 5800 (Syil X7).
Rule ids below cite that spec (P1..P13 program structure, N1..N7 words and
numbers).

* Header (P1-P6): ``%`` / ``O<n>`` / tool comment
  ``(T<n> D=<dia> CR=<cr> - ZMIN=<min z> - <type>)`` /
  ``G90 G94 G17 G49 G40 G80`` (P4) / ``G20`` (or ``G21``, P5) /
  ``G53 G00 Z0.`` (P6).
* Per op (P7-P12): ``(OP NAME)`` / ``T<n> M06`` / tool description comment /
  ``S<rpm> M03`` + warm-up dwell (P8: ``G04 P<ms>`` by default, confirmed on James's X7;
  ``dwell_p_ms=False`` emits ``G04 X<s>.``) / work offset ``G54`` (P9) /
  ``M08`` (P10) / first XY rapid at the current Z / ``G43 Z<clear> H<n>``
  (P11) / motion. Cutter radius comp is off, paths are tool centre (P12); a
  header comment states this. Arcs (``G02``/``G03`` with I/J in G17, N5) are
  emitted only if the input path actually contains arcs.
* Number format (N1-N4): every axis/arc-centre/feed value carries a decimal
  point; maximum fraction digits with trailing zeros trimmed and the point
  forced (inch coords 4 dp, mm 3 dp; feeds inch up to 1 dp, mm integer).
  Integer-only addresses (O/N/T/H/D/M/S/G) never carry a point (N2); ``-0.``
  collapses to ``0.`` (N3).
* Modal suppression (N6): the motion word (``G00``/``G01``) is emitted only
  when the motion mode changes, an axis word only when that axis value changes
  at output precision, and ``F`` only when the feed changes.
* Footer (P13): a clearance rapid, blank line, then ``M09 / M05 / G53 G00 Z0.
  / G49 / G28 G91 X0. Y0. / G90 / M30 / %`` (M05 is the explicit spindle
  stop).

Line endings: CRLF per N7 (``crlf=False`` switches to LF for diffing/tests).
"""
import json
import os

# Motion G-codes that are "group 1" modal moves in this post.
_MOTION = {0: "G00", 1: "G01", 2: "G02", 3: "G03"}

# Human tool-type suffix used in the header tool comment.
_TYPE = {
    "bull": "BULLNOSE END MILL",
    "flat": "FLAT END MILL",
    "endmill": "END MILL",
    "ball": "BALL NOSE END MILL",
}

# X7 tool table: spec (type + diameter + corner radius, mm) -> machine numbers.
TOOL_TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              os.pardir, "tools", "x7_tools.json")


def load_tool_table(path=None):
    """Load the X7 tool table (list of entries); [] if the file is absent."""
    p = path or TOOL_TABLE_PATH
    try:
        with open(p) as fh:
            return json.load(fh).get("tools", [])
    except (IOError, OSError, ValueError):
        return []


def lookup_tool(kind, dia_mm, corner_mm, table=None):
    """Find the table entry matching type + diameter + corner radius within
    0.001 mm. Returns the entry dict or None."""
    tol = 0.001
    for e in (table if table is not None else load_tool_table()):
        if e.get("type") != kind:
            continue
        if abs(float(e.get("diameter_mm", -1.0)) - dia_mm) > tol:
            continue
        if abs(float(e.get("corner_radius_mm", 0.0)) - corner_mm) > tol:
            continue
        return e
    return None


# ---------------------------------------------------------------------------
# Number formatting (spec N1-N4: max fraction digits, trailing zeros trimmed,
# decimal point forced on float addresses)
# ---------------------------------------------------------------------------

def fmt_num(value, decimals):
    """Format one number per spec N1/N3.

    ``decimals`` is the maximum number of fractional digits; trailing zeros are
    trimmed but a decimal point is always kept (``3.`` for integers). ``-0.0``
    and values that round to zero collapse to a positive ``0.`` (N3).
    """
    if decimals <= 0:
        # integer feed field (N4): the forced trailing dot still applies
        n = int(round(value))
        if n == 0:
            n = 0  # collapse -0
        return "%d." % n
    s = ("%%.%df" % decimals) % value
    if float(s) == 0.0:               # kill "-0.0000"
        s = ("%%.%df" % decimals) % 0.0
    return s.rstrip("0")             # trailing zeros trimmed; '.' remains


def _coord_decimals(metric):
    return 3 if metric else 4


def _feed_decimals(metric):
    return 0 if metric else 1


# ---------------------------------------------------------------------------
# Input parsing (neutral / engine output)
# ---------------------------------------------------------------------------

def _strip_comment(line):
    out, depth = [], 0
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


def parse_neutral(text):
    """Parse a neutral/engine G-code listing into a move list + metadata.

    Returns ``{"moves": [...], "units_in": 1.0|25.4, "spindle": int|None,
    "tool": {"kind", "dia", "cr", "number"} or None}``. Coordinates are returned
    in the *input* units together with ``units_in`` (mm-per-input-unit) so the
    caller can rescale to the requested output units. Modal X/Y/Z carry forward
    so a suppressed-word input still resolves to absolute targets.
    """
    units_in = 1.0
    modal_g = None
    absolute = True
    feed = None
    spindle = None
    tool = None
    pos = {"x": 0.0, "y": 0.0, "z": 0.0}
    moves = []

    import re
    word_re = re.compile(r"([A-Za-z])\s*([-+]?[0-9]*\.?[0-9]+)")

    for raw in text.splitlines():
        # capture tool comment before stripping: (T<n> <kind> D=<d> CR=<c>)
        if tool is None:
            m = re.match(r"\s*\(\s*T(\d+)\s+(\w+)\s+D=([0-9.]+)\s+CR=([0-9.]+)",
                        raw)
            if m:
                tool = {"number": int(m.group(1)), "kind": m.group(2).lower(),
                       "dia": float(m.group(3)), "cr": float(m.group(4))}
        s = _strip_comment(raw)
        words = word_re.findall(s)
        if not words:
            continue
        gcodes, params = [], {}
        for letter, num in words:
            try:
                val = float(num)
            except ValueError:
                continue
            L = letter.upper()
            if L == "G":
                gcodes.append(val)
            elif L in ("X", "Y", "Z"):
                params[L] = val
            elif L == "F":
                params["F"] = val
            elif L == "S":
                spindle = int(round(val))

        g0 = None
        for g in gcodes:
            gi = int(round(g))
            if g == 20:
                units_in = 25.4
            elif g == 21:
                units_in = 1.0
            elif g in (90.0,):
                absolute = True
            elif g in (91.0,):
                absolute = False
            elif gi in (0, 1, 2, 3):
                g0 = gi
            elif g == 53:
                g0 = None  # machine-coordinate home rapid: not part of the path

        if "F" in params:
            feed = params["F"]

        # home / non-path moves (G53 rapids) are skipped
        if "G53" in s.upper():
            continue

        if g0 is None:
            # a line with only S/M/G43 etc. carries no path motion
            if not any(k in params for k in ("X", "Y", "Z")):
                continue
            g0 = modal_g if modal_g is not None else 1

        # resolve absolute targets (input units)
        tgt = {}
        for k in ("X", "Y", "Z"):
            if k in params:
                tgt[k.lower()] = params[k] if absolute else pos[k.lower()] + params[k]
            else:
                tgt[k.lower()] = pos[k.lower()]
        pos = {"x": tgt["x"], "y": tgt["y"], "z": tgt["z"]}
        move = {"g": g0, "x": tgt["x"], "y": tgt["y"], "z": tgt["z"]}
        if feed is not None and g0 == 1:
            move["f"] = feed
        moves.append(move)
        modal_g = g0

    return {"moves": moves, "units_in": units_in, "spindle": spindle,
            "tool": tool}


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def post_moves(moves, metric=False, units_in=1.0, start=None):
    """Return the motion lines (no header/footer) for ``moves``.

    ``units_in`` is mm-per-input-unit (1.0 if the input is already mm). Output
    units are inch (default) or mm (``metric=True``); the scale converts input
    units to output units for both coordinates and feeds.

    ``start`` is the (x, y, z) position already established by the op header
    (first XY rapid + ``G43`` tool-length), in output units; it lets the first
    cutting move suppress axes that have not changed (modal rule N6).
    """
    out_to_mm = 1.0 if metric else 25.4
    scale = units_in / out_to_mm          # input units -> output units
    dec = _coord_decimals(metric)
    fdec = _feed_decimals(metric)

    def coord(v):
        return round(v * scale, dec)

    lines = []
    if start is not None:
        cur = {"x": round(start[0], dec) if start[0] is not None else None,
               "y": round(start[1], dec) if start[1] is not None else None,
               "z": round(start[2], dec) if start[2] is not None else None}
    else:
        cur = {"x": None, "y": None, "z": None}   # rounded output position
    mode = None                                # last emitted motion mode word
    cur_feed = None

    for mv in moves:
        g = mv.get("g", 1)
        newmode = _MOTION.get(g, "G01")
        tgt = {"x": coord(mv["x"]) if mv.get("x") is not None else cur["x"],
               "y": coord(mv["y"]) if mv.get("y") is not None else cur["y"],
               "z": coord(mv["z"]) if mv.get("z") is not None else cur["z"]}

        words = []
        if newmode != mode:
            words.append(newmode)
        for k in ("x", "y", "z"):
            if tgt[k] != cur[k]:
                words.append("%s%s" % (k.upper(), fmt_num(tgt[k], dec)))

        feed = mv.get("f")
        if newmode == "G01" and feed:
            outf = round(feed * scale, fdec)
            if outf != cur_feed:
                words.append("F%s" % fmt_num(outf, fdec))

        if not words:
            continue                          # no-op move (nothing changed)
        lines.append(" ".join(words))
        cur = tgt
        mode = newmode
        if newmode == "G01" and feed:
            cur_feed = round(feed * scale, fdec)

    return lines


def post(moves, *, metric=False, units_in=1.0, program=1001,
         op_name="ENGINE ROUGH", tool_number=None, rpm=7500,
         dia_mm=12.7, corner_mm=0.127, tool_kind="bull",
         clear_mm=None, wcs=54, dwell_ms=3000, dwell_p_ms=True,
         tool_desc=None, comp_note=True, crlf=True,
         comment_style="paren"):
    """Build a full LNC program (single string) from neutral ``moves``.

    Format follows docs/lnc5800_post_spec.md (rule ids P1..P13, N1..N7).
    Distances in ``dia_mm/corner_mm/clear_mm`` and the move coordinates are
    millimetres (the engine's working unit); ``units_in`` tells the post the
    input units if they are not mm. Output is inch unless ``metric=True``.

    ``dwell_ms`` is the P8 warm-up dwell; by default it is emitted as
    ``G04 P<milliseconds>`` (P8, whole ms, no point). With ``dwell_p_ms=False`` it is
    emitted as ``G04 P<milliseconds>`` (P8, VERIFY: P unit on the X7).

    ``tool_number`` (T and H) must either be given explicitly or be found in
    the X7 tool table (``tools/x7_tools.json``, matched on type + diameter +
    corner radius within 0.001 mm). A spec that is not in the table with no
    explicit number is refused -- never a silent T1.
    """
    if tool_number is None:
        entry = lookup_tool(tool_kind, dia_mm, corner_mm)
        if entry is not None and entry.get("number") is None:
            raise ValueError(
                "X7 tool %s D=%.3fmm is in %s but has no T/H/D number assigned yet "
                "(ask James); pass --tool-number to override" % (tool_kind, dia_mm, TOOL_TABLE_PATH))
        if entry is None:
            raise ValueError(
                "no X7 tool number for %s D=%.3fmm CR=%.3fmm: not in %s and "
                "no --tool-number given" % (tool_kind, dia_mm, corner_mm,
                                           TOOL_TABLE_PATH))
        tool_number = int(entry["number"])

    out_to_mm = 1.0 if metric else 25.4
    scale = units_in / out_to_mm
    cdec = _coord_decimals(metric)

    zs = [mv["z"] for mv in moves if mv.get("z") is not None]
    min_z_mm = min(zs) if zs else 0.0
    if clear_mm is None:
        clear_out = max((mv["z"] * scale for mv in moves if mv.get("z") is not None),
                       default=0.0)
    else:
        clear_out = clear_mm * units_in / out_to_mm
    # round clear to output precision so G43 / retract read cleanly
    clear_out = round(clear_out, cdec)

    # --- header (P1-P6, P12) ---
    out = []
    out.append("%")                                  # P1
    out.append("O%d" % program)                   # P2 (integer, no point: N2)
    dia_out = dia_mm * units_in / out_to_mm
    # CR is the tool's corner radius: D/2 for a ball (the implied geometry),
    # 0 for a flat end mill, the table corner radius for a bull-nose. The
    # neutral file's CR word may carry 0 for balls (the CLI spec is kind:dia),
    # never post that as the ball's corner.
    if tool_kind == "ball":
        cr_hdr_mm = dia_mm / 2.0
    elif tool_kind in ("flat", "endmill"):
        cr_hdr_mm = 0.0
    else:
        cr_hdr_mm = corner_mm
    cr_out = cr_hdr_mm * units_in / out_to_mm
    zmin_out = min_z_mm * units_in / out_to_mm
    type_str = _TYPE.get(tool_kind, "END MILL")
    out.append("(T%d D=%s CR=%s - ZMIN=%s - %s)"
               % (tool_number, fmt_num(dia_out, cdec), fmt_num(cr_out, cdec),
                 fmt_num(zmin_out, cdec), type_str))
    out.append("G90 G94 G17 G49 G40 G80")      # P4 safety line
    out.append("G21" if metric else "G20")      # P5 units, own line
    if comp_note:
        out.append("(CUTTER COMPENSATION OFF - PATHS ARE TOOL CENTRE)")  # P12
    out.append("G53 G00 Z0.")                  # P6 home before tool change
    out.append("")

    # --- op block (P7-P11) ---
    out.append("(%s)" % op_name.upper())          # P3 comment form
    out.append("T%d M06" % tool_number)          # P7
    desc = tool_desc if tool_desc is not None else type_str
    out.append("(%s)" % desc.upper())            # P3 comment form
    out.append("S%d M03" % rpm)                 # P8 (integer S: N2)
    if dwell_p_ms:
        out.append("G04 P%d" % int(round(dwell_ms)))   # P8: P = ms (LNC programming manual p.13)
    else:
        out.append("G04 X%s" % fmt_num(dwell_ms / 1000.0, 3))  # P8: X = sec
    out.append("G%d" % wcs)                     # P9
    out.append("M08")                           # P10

    # first XY rapid (at clear height), then tool-length to clear
    first_xy = next(((mv.get("x"), mv.get("y")) for mv in moves
                     if mv.get("x") is not None or mv.get("y") is not None),
                    (None, None))
    start_x = round(first_xy[0] * scale, cdec) if first_xy[0] is not None else None
    start_y = round(first_xy[1] * scale, cdec) if first_xy[1] is not None else None
    xy_bits = []
    if start_x is not None:
        xy_bits.append("X%s" % fmt_num(start_x, cdec))
    if start_y is not None:
        xy_bits.append("Y%s" % fmt_num(start_y, cdec))
    if xy_bits:
        out.append("G00 " + " ".join(xy_bits))
    out.append("G43 Z%s H%02d" % (fmt_num(clear_out, cdec), tool_number))

    # --- motion (X/Y already positioned at clear; start there for suppression) ---
    out.extend(post_moves(moves, metric=metric, units_in=units_in,
                         start=(start_x, start_y, clear_out)))

    # --- retract to clear if not already there ---
    last_z = round(zs[-1] * scale, cdec) if zs else clear_out
    if last_z is None or last_z < clear_out:
        out.append("G00 Z%s" % fmt_num(clear_out, cdec))

    # --- footer (P13) ---
    out.append("")
    out.append("M09")                           # P10 coolant off
    out.append("M05")                          # P13 explicit spindle stop
    out.append("G53 G00 Z0.")                  # P6 machine-coordinate Z home
    out.append("G49")
    out.append("G28 G91 X0. Y0.")
    out.append("G90")
    out.append("M30")
    out.append("%")                            # P1

    # CRLF line endings per N7
    if comment_style == "slashstar":   # P3: LNC parameter 42 = 0 -> /*...*/ comments
        out = ["/*%s*/" % l[1:-1] if l.startswith("(") and l.endswith(")") else l
               for l in out]
    elif comment_style != "paren":
        raise ValueError("comment_style must be 'paren' or 'slashstar'")
    return ("\r\n" if crlf else "\n").join(out) + ("\r\n" if crlf else "\n")


def post_text(text, **kw):
    """Parse a neutral/engine G-code listing and return the posted program."""
    parsed = parse_neutral(text)
    tool = parsed.get("tool") or {}
    kw.setdefault("units_in", parsed.get("units_in", 1.0))
    if parsed.get("spindle") is not None:
        kw.setdefault("rpm", parsed["spindle"])
    if tool:
        # the neutral file's T-number is an engine placeholder, not an X7 one:
        # the number comes from --tool-number or the tool table, never silently
        kw.setdefault("tool_kind", tool.get("kind", "bull"))
        if tool.get("dia") is not None:
            # engine writes D in mm; keep as mm regardless of input units
            kw.setdefault("dia_mm", tool["dia"])
        if tool.get("cr") is not None:
            kw.setdefault("corner_mm", tool["cr"])
    return post(parsed["moves"], **kw)


# ---------------------------------------------------------------------------
# Structural classification (used by the tests and post_report)
# ---------------------------------------------------------------------------

import re as _re

_CONTROL_RES = [
    ("pct", _re.compile(r"%$")),
    ("oprogram", _re.compile(r"O\d+$")),
    ("comment", _re.compile(r"\(.*\)$")),
    ("modal_header", _re.compile(r"G90 G94 G17 G49 G40 G80$")),   # P4
    ("units", _re.compile(r"G2[01]$")),                             # P5
    ("home_rapid", _re.compile(r"G53 G00 Z0\.$")),                  # P6
    ("toolchange", _re.compile(r"T\d+ M0?6$")),                     # P7
    ("spindle", _re.compile(r"S\d+ M0?3$")),                        # P8
    ("dwell", _re.compile(r"G0?4 [XP]\S+$")),                       # P8
    ("wcs", _re.compile(r"G5[4-9]$")),                              # P9
    ("coolant_on", _re.compile(r"M0?8$")),                          # P10
    ("coolant_off", _re.compile(r"M0?9$")),                         # P10
    ("spindle_stop", _re.compile(r"M0?5$")),                        # P13
    ("tool_len", _re.compile(r"G43 Z\S+ H\d+$")),                    # P11
    ("g49", _re.compile(r"G49$")),                                  # P13
    ("home_g28", _re.compile(r"G28 G91 X0\. Y0\.$")),               # P13
    ("absolute", _re.compile(r"G9[01]$")),
    ("plane", _re.compile(r"G1[789]$")),
    ("end", _re.compile(r"M3?0$")),                                 # P13
]

# Categories whose *values* are allowed to differ between programs (tool
# number, rpm, dwell, tool-length clear/H, program number) plus comments and the
# optional plane-restore that only appears when an op used G18/G19.
MASKS = {
    "oprogram": "O<#>",
    "comment": "(C)",
    "toolchange": "T<#> M06",
    "spindle": "S<#> M03",
    "dwell": "G04 <X/P#>",
    "tool_len": "G43 Z<#> H<#>",
}


def nonmotion_token(line):
    """Classify a NON-motion line into a category, masked so that values which
    are allowed to differ collapse to a common token. Returns ``None`` for
    motion lines (coordinate moves / arc moves / coordinate continuations).
    """
    s = line.rstrip("\r\n").strip()
    if s == "":
        return None                      # blank lines carry no structure here
    for name, rx in _CONTROL_RES:
        if rx.search(s):
            return MASKS.get(name, s)
    return None                          # motion


def control_sequence(lines):
    """Masked, non-comment, non-blank structural tokens (motion dropped)."""
    seq = []
    for ln in lines:
        tok = nonmotion_token(ln)
        if tok is None or tok == "(C)":
            continue
        seq.append(tok)
    return seq


def comment_sequence(lines):
    """Masked comment tokens only (op names / tool descriptions / notes)."""
    seq = []
    for ln in lines:
        tok = nonmotion_token(ln)
        if tok == "(C)":
            seq.append(tok)
    return seq

