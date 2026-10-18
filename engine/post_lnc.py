"""Neutral / engine move list -> James's SyilCNC LNCv2 G-code (post_lnc).

The engine's neutral moves (mm, ``G0``/``G1`` with explicit X/Y/Z/F words as
written by :func:`engine.gcode.moves_to_gcode`) are re-posted into the shape of
``reference/1001.nc`` -- the program that runs on James's LNC 5800.

Conventions learned from ``reference/1001.nc`` (and the vendor ``.cps`` used only
to understand the number formats; none of its code is copied):

* Header: ``%`` / ``O<prog>`` / tool comment
  ``(T<n> D=<dia> CR=<cr> - ZMIN=<min z> - <type>)`` /
  ``G90 G94 G17 G49 G40 G80`` / ``G20`` (or ``G21``) / ``G53 G00 Z0.``.
* Per op: ``(OP NAME)`` / ``T<n> M06`` / tool description comment /
  ``S<rpm> M03`` / ``G04 P<dwell>`` / work offset (``G54``) / ``M08`` /
  first XY rapid / ``G43 Z<clear> H<n>`` / motion.
* Number format: maximum fraction digits with trailing zeros trimmed and a
  forced decimal point (``3.`` for integers, ``2.6`` not ``2.6000``, leading
  zeros kept). Inch = up to 4 decimals, mm = up to 3; feeds inch up to 1,
  mm integer.
* Modal suppression exactly like the reference: the motion word (``G00``/``G1``)
  is emitted only when the motion mode changes, an axis word only when that
  axis value changes at output precision, and ``F`` only when the feed changes.
* Footer: exactly what ``1001.nc`` ends with -- a clearance rapid, blank line,
  ``M09 / G53 G00 Z0. / G49 / G28 G91 X0. Y0. / G90 / M30 / %``. (No ``M05``;
  the LNC post relies on ``M30`` to stop the spindle.)

No cutter compensation is emitted (roughing paths are tool centre); a header
comment states this. Arcs (``G02``/``G03`` with I/J in G17) are emitted only if
the input path actually contains arcs.

Line endings: the reference file is CRLF, so the posted program uses CRLF by
default (``crlf=False`` switches to LF for diffing/tests).
"""

# Motion G-codes that are "group 1" modal moves in this post.
_MOTION = {0: "G00", 1: "G01", 2: "G02", 3: "G03"}

# Human tool-type suffix used in the header tool comment.
_TYPE = {
    "bull": "BULLNOSE END MILL",
    "flat": "FLAT END MILL",
    "endmill": "END MILL",
    "ball": "BALL NOSE END MILL",
}


# ---------------------------------------------------------------------------
# Number formatting (matches the vendor createFormat: max fraction digits,
# trailing zeros trimmed, decimal point forced)
# ---------------------------------------------------------------------------

def fmt_num(value, decimals):
    """Format one number the way 1001.nc does.

    ``decimals`` is the maximum number of fractional digits; trailing zeros are
    trimmed but a decimal point is always kept (``3.`` for integers). ``-0.0``
    and values that round to zero collapse to a positive ``0.``.
    """
    if decimals <= 0:
        # integer field; forceDecimal still wants the trailing dot
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
    cutting move suppress axes that have not changed, exactly like 1001.nc.
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
         op_name="ENGINE ROUGH", tool_number=1, rpm=7500,
         dia_mm=12.7, corner_mm=0.127, tool_kind="bull",
         clear_mm=None, wcs=54, dwell_ms=3000, tool_desc=None,
         comp_note=True, crlf=True):
    """Build a full LNC program (list of lines) from neutral ``moves``.

    Distances in ``dia_mm/corner_mm/clear_mm`` and the move coordinates are
    millimetres (the engine's working unit); ``units_in`` tells the post the
    input units if they are not mm. Output is inch unless ``metric=True``.
    """
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

    # --- header ---
    out = []
    out.append("%")
    out.append("O%d" % program)
    dia_out = dia_mm * units_in / out_to_mm
    cr_out = corner_mm * units_in / out_to_mm
    zmin_out = min_z_mm * units_in / out_to_mm
    type_str = _TYPE.get(tool_kind, "END MILL")
    out.append("(T%d D=%s CR=%s - ZMIN=%s - %s)"
               % (tool_number, fmt_num(dia_out, cdec), fmt_num(cr_out, cdec),
                 fmt_num(zmin_out, cdec), type_str))
    out.append("G90 G94 G17 G49 G40 G80")
    out.append("G21" if metric else "G20")
    if comp_note:
        out.append("(CUTTER COMPENSATION OFF - PATHS ARE TOOL CENTRE)")
    out.append("G53 G00 Z0.")
    out.append("")

    # --- op block ---
    out.append("(%s)" % op_name.upper())
    out.append("T%d M06" % tool_number)
    desc = tool_desc if tool_desc is not None else type_str
    out.append("(%s)" % desc.upper())
    out.append("S%d M03" % rpm)
    out.append("G04 P%d" % dwell_ms)
    out.append("G%d" % wcs)
    out.append("M08")

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

    # --- footer (exactly what 1001.nc ends with) ---
    out.append("")
    out.append("M09")
    out.append("G53 G00 Z0.")
    out.append("G49")
    out.append("G28 G91 X0. Y0.")
    out.append("G90")
    out.append("M30")
    out.append("%")

    return ("\r\n" if crlf else "\n").join(out) + ("\r\n" if crlf else "\n")


def post_text(text, **kw):
    """Parse a neutral/engine G-code listing and return the posted program."""
    parsed = parse_neutral(text)
    tool = parsed.get("tool") or {}
    kw.setdefault("units_in", parsed.get("units_in", 1.0))
    if parsed.get("spindle") is not None:
        kw.setdefault("rpm", parsed["spindle"])
    if tool:
        kw.setdefault("tool_number", tool.get("number", 1))
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
    ("modal_header", _re.compile(r"G90 G94 G17 G49 G40 G80$")),
    ("units", _re.compile(r"G2[01]$")),
    ("home_rapid", _re.compile(r"G53 G00 Z0\.$")),
    ("toolchange", _re.compile(r"T\d+ M0?6$")),
    ("spindle", _re.compile(r"S\d+ M0?3$")),
    ("dwell", _re.compile(r"G0?4 P\d+$")),
    ("wcs", _re.compile(r"G5[4-9]$")),
    ("coolant_on", _re.compile(r"M0?8$")),
    ("coolant_off", _re.compile(r"M0?9$")),
    ("tool_len", _re.compile(r"G43 Z\S+ H\d+$")),
    ("g49", _re.compile(r"G49$")),
    ("home_g28", _re.compile(r"G28 G91 X0\. Y0\.$")),
    ("absolute", _re.compile(r"G9[01]$")),
    ("plane", _re.compile(r"G1[789]$")),
    ("end", _re.compile(r"M3?0$")),
]

# Categories whose *values* are allowed to differ from the reference (tool
# number, rpm, dwell, tool-length clear/H, program number) plus comments and the
# optional plane-restore that only appears when an op used G18/G19.
MASKS = {
    "oprogram": "O<#>",
    "comment": "(C)",
    "toolchange": "T<#> M06",
    "spindle": "S<#> M03",
    "dwell": "G04 P<#>",
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

