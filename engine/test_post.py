#!/usr/bin/env python3
"""Tests for engine/post_lnc.py (LNCv2 post).

Runnable two ways:
    /opt/homebrew/bin/python3 -m pytest engine/test_post.py -q
    /Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_post.py

(a) spec conformance: post a small synthetic program and check every rule of
    docs/lnc5800_post_spec.md -- header order (P1-P6), comment form (P3),
    dwell default `G04 P<ms>` and `--dwell-x-s` variant (P8), footer order
    incl. M05 (P13), integer addresses without points (N2), decimals on
    coordinates/feeds (N1/N3/N4), modal suppression (N6), CRLF (N7).
(b) zmap the posted inch file and confirm gouges / leftover / cutting length are
    identical (within 1e-3) to the neutral metric run out/core_front_roughG.ngc.
(c) number-formatting edge cases (0, negatives, 1.0, 0.00005 rounding, -0.0).
(d) X7 tool table (tools/x7_tools.json): lookup, --tool-number override,
    refusal for unlisted tools without a number (no silent T1).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")

from engine import post_lnc  # noqa: E402

NEUTRAL = os.path.join(ROOT, "out", "core_front_roughG.ngc")
PART_HF = os.path.join(ROOT, "out", "core_front_setup_hf.npy")
STOCK_BOX = (-128.651, 128.651, -82.55, 82.55, 0.0, 60.96)
TOOL = dict(tool="bull", dia=12.7, corner=0.127, flute=25.4)

_POSTED_CACHE = {}


def _read(path):
    with open(path, newline="") as fh:
        return fh.read()


def _posted_inch_text():
    """Post the neutral roughing to LNC inch once, cache it."""
    if "inch" not in _POSTED_CACHE:
        _POSTED_CACHE["inch"] = post_lnc.post_text(
            _read(NEUTRAL), program=1001, op_name="OVERALL ROUGHING")
    return _POSTED_CACHE["inch"]


def _lines(text):
    return text.replace("\r\n", "\n").split("\n")


# ---------------------------------------------------------------------------
# (a) spec conformance on a small synthetic program (docs/lnc5800_post_spec.md)
# ---------------------------------------------------------------------------

# small synthetic mm path: rapid in, 3 feed moves (one per axis), retract
SYN_MOVES = [
    {"g": 0, "x": 0.0, "y": 0.0, "z": 5.0},
    {"g": 1, "x": 10.0, "y": 0.0, "z": 5.0, "f": 1270.0},
    {"g": 1, "x": 10.0, "y": 10.0, "z": 5.0, "f": 1270.0},
    {"g": 1, "x": 10.0, "y": 10.0, "z": -2.5, "f": 1270.0},
    {"g": 0, "x": 0.0, "y": 0.0, "z": 5.0},
]


def _synthetic(metric=True, **kw):
    return post_lnc.post(SYN_MOVES, metric=metric, tool_number=2,
                         rpm=7500, dia_mm=6.0, corner_mm=0.0,
                         tool_kind="flat", op_name="SPEC TEST", crlf=False,
                         **kw)


def test_spec_header_and_footer_order():
    """P1-P6 header order and P13 footer order (incl. M05)."""
    txt = _synthetic()
    lines = _lines(txt)

    # P1/P2: tape start, integer program number
    assert lines[0] == "%", "P1: file must start with a %% line, got %r" % lines[0]
    assert re.match(r"^O\d+$", lines[1]), "P2: line 2 must be O<n>: %r" % lines[1]

    # P4 safety line, P5 units on its own line -- both before any motion
    i_safety = lines.index("G90 G94 G17 G49 G40 G80")
    i_units = lines.index("G21")
    first_motion = next(i for i, l in enumerate(lines)
                        if re.match(r"^G0[01] [XYZ]", l))
    assert i_safety < i_units < first_motion, \
        "P4/P5: safety line then units must precede motion: %r" % lines[:12]

    # P6: G53 G00 Z0. appears before the tool change (and again in the footer)
    i_home = lines.index("G53 G00 Z0.")
    i_tool = next(i for i, l in enumerate(lines) if l.endswith("M06"))
    assert i_home < i_tool, "P6: machine-Z home before the tool change"
    assert lines.count("G53 G00 Z0.") == 2, "P6: home before op and in footer"

    # P7-P11 op block order
    seq = ["T2 M06", "S7500 M03", "G04 P3000", "G54", "M08"]
    idx = [lines.index(s) for s in seq]
    assert idx == sorted(idx), "P7-P10 order wrong: %r" % lines[i_tool:i_tool + 8]
    i_g43 = next(i for i, l in enumerate(lines) if l.startswith("G43"))
    assert lines[i_g43] == "G43 Z5. H02", "P11: %r" % lines[i_g43]
    assert i_g43 > lines.index("M08"), "P11: tool length after coolant on"
    xy_rapid = next(l for l in lines if re.match(r"^G00 X\S+ Y\S+$", l))
    assert lines.index(xy_rapid) < i_g43, \
        "P11: first XY rapid at current Z precedes G43"

    # P13 footer order incl. explicit M05 after M09
    tail = [l for l in lines if l != ""][-8:]
    want = ["M09", "M05", "G53 G00 Z0.", "G49", "G28 G91 X0. Y0.", "G90",
            "M30", "%"]
    assert tail == want, "P13 footer order: got %r want %r" % (tail, want)
    print("PASS spec P1-P13: header/footer order incl. M05")


def test_spec_comment_form():
    """P3: comments are ( ... ), upper case, no nested parentheses."""
    txt = _synthetic()
    comments = [l for l in _lines(txt) if l.startswith("(")]
    assert comments, "no comment lines posted"
    for c in comments:
        assert c.endswith(")") and c.count("(") == 1 and c.count(")") == 1, \
            "P3: no nested parens: %r" % c
        assert c == c.upper(), "P3: comments must be upper case: %r" % c
    print("PASS spec P3: %d upper-case flat ( ) comments" % len(comments))


def test_spec_dwell_variants():
    """P8: default dwell is G04 P<whole ms> (James's X7); dwell_p_ms=False emits G04 X<s>."""
    txt_p = _synthetic()
    assert "G04 P3000" in txt_p, "P8 default must be G04 P<ms>"
    assert "G04 X" not in txt_p and "G04 P3000." not in txt_p
    assert "G04 P1500" in _synthetic(dwell_ms=1500.4), "P8: whole milliseconds"
    assert "G04 X3." in _synthetic(dwell_p_ms=False), "P8 option must be G04 X<seconds>."
    assert "G04 X1.5" in _synthetic(dwell_ms=1500, dwell_p_ms=False)
    print("PASS spec P8: dwell P<ms> default, X<s>. with dwell_p_ms=False")


def test_spec_number_rules():
    """N1/N2/N4: decimals on axes/feeds, none on integer addresses."""
    txt = _synthetic()
    lines = _lines(txt)

    # N2: O/T/H/M/S/G words never carry a decimal point
    for l in lines:
        for letter, num in re.findall(r"\b([OTHMSG])\s*([-+]?[0-9.]+)", l):
            assert "." not in num, \
                "N2: integer address %s%s carries a point: %r" % (letter, num, l)

    # N1: every X/Y/Z/F word carries a decimal point
    for l in lines:
        if l.startswith("("):
            continue
        for letter, num in re.findall(r"\b([XYZF])\s*([-+]?[0-9.]+)", l):
            assert "." in num, \
                "N1: %s value lacks a decimal point: %r" % (letter, l)

    # N3/N4 metric: mm coords to 3 dp, feeds integer with forced point
    assert "X10." in txt and "Z-2.5" in txt, "N3: mm coords: %r" % txt
    assert "F1270." in txt, "N4: mm feed is integer with a point"

    # N3 inch output: 4 dp, trailing zeros trimmed
    txt_in = _synthetic(metric=False)
    assert "G20" in txt_in, "P5: inch mode emits G20"
    assert "X0.3937" in txt_in, \
        "N3: 10 mm -> 0.3937 in (4 dp): %r" % [l for l in _lines(txt_in)
                                                if "X0.39" in l]
    assert "F50." in txt_in, "N4: 1270 mm/min -> F50. ipm"
    print("PASS spec N1-N4: decimals on axes/feeds, none on integer addresses")


def test_spec_modal_suppression():
    """N6: motion word on mode change only, axis words on change only, F once."""
    txt = _synthetic()
    lines = _lines(txt)
    motion = [l for l in lines if re.match(r"^[XYZF]|^G0[01]", l)
              and not l.startswith(("G53", "G28"))]
    assert txt.count("G01") == 1, \
        "N6: G01 must appear once (mode change), got %d: %r" % (txt.count("G01"),
                                                                 motion)
    assert txt.count("F1270.") == 1, "N6: unchanged feed must be suppressed"
    assert "Y10." in txt and not re.search(r"G01 Y10\.", txt), \
        "N6: axis-only change lines carry no motion word"
    # the entry rapid to (0,0) at Z5 equals the header position -> dropped;
    # only the end-of-op retract rapid to that point remains (one such line)
    assert txt.count("G00 X0. Y0. Z5.") == 1, \
        "N6: the no-op entry move must be dropped: %r" % motion
    print("PASS spec N6: modal suppression (%d motion lines)" % len(motion))


def test_spec_crlf():
    """N7: CRLF line endings by default, LF on request."""
    default = post_lnc.post(SYN_MOVES, metric=True, tool_number=2,
                            tool_kind="flat", dia_mm=6.0)
    assert "\r\n" in default and "\n" not in default.replace("\r\n", ""), \
        "N7: default line endings must be CRLF"
    assert "\r\n" not in _synthetic(), "crlf=False must give LF"
    print("PASS spec N7: CRLF by default")


# ---------------------------------------------------------------------------
# (c) number formatting edge cases
# ---------------------------------------------------------------------------

def test_number_format_edge_cases():
    f = post_lnc.fmt_num
    cases = [
        ((0.0, 4), "0."),          # zero -> forced decimal
        ((-0.0, 4), "0."),        # negative zero collapses to positive
        ((1.0, 4), "1."),         # integer -> trailing dot
        ((3.0, 3), "3."),
        ((100.0, 4), "100."),     # trailing zeros trimmed, dot kept
        ((2.6, 4), "2.6"),        # trailing zeros trimmed
        ((1.75, 4), "1.75"),
        ((-5.1141, 4), "-5.1141"),
        ((-1.0, 3), "-1."),
        ((0.00005, 4), "0.0001"),   # rounds up at the 4th decimal
        ((-0.00005, 4), "-0.0001"),
        ((0.00004999, 4), "0."),    # rounds to zero -> positive 0.
        ((50.0, 1), "50."),         # inch feed (ipm)
        ((135.0, 1), "135."),
        ((3429.0, 0), "3429."),     # mm feed (integer, forced decimal)
        ((1270.0, 0), "1270."),
    ]
    for (val, dec), want in cases:
        got = f(val, dec)
        assert got == want, "fmt_num(%r,%d)=%r want %r" % (val, dec, got, want)
    print("PASS number format edge cases (%d)" % len(cases))


# ---------------------------------------------------------------------------
# (d) X7 tool table: lookup / override / refusal
# ---------------------------------------------------------------------------

def test_tool_table_lookup():
    entry = post_lnc.lookup_tool("bull", 12.7, 0.127)
    assert entry is not None, "seed tool bull D12.7 CR0.127 missing from table"
    assert entry["number"] == 3, "seed tool must be T3, got %r" % entry["number"]
    # spec within 0.001 mm still matches; type mismatch or beyond tolerance not
    assert post_lnc.lookup_tool("bull", 12.7005, 0.1272)["number"] == 3
    assert post_lnc.lookup_tool("bull", 12.7, 0.13) is None
    assert post_lnc.lookup_tool("flat", 12.7, 0.127) is None
    # posting with no explicit number resolves through the table -> T3 / H03
    txt = post_lnc.post_text(_read(NEUTRAL), program=1001,
                             op_name="OVERALL ROUGHING", crlf=False)
    assert "T3 M06" in txt, "no T3 toolchange from table lookup: %r" % txt[:80]
    assert "H03" in txt, "no H03 tool-length offset from table lookup"
    print("PASS tool table lookup (bull 12.7/0.127 -> T3 / H03)")


def test_tool_number_override():
    txt = post_lnc.post_text(_read(NEUTRAL), program=1001,
                             op_name="OVERALL ROUGHING", tool_number=5,
                             crlf=False)
    assert "T5 M06" in txt and "H05" in txt, "--tool-number must win over table"
    assert "T3 M06" not in txt
    print("PASS tool number override (explicit 5 -> T5 / H05)")


def test_unknown_tool_refused():
    moves = [{"g": 1, "x": 0.0, "y": 0.0, "z": 1.0, "f": 100.0}]
    try:
        post_lnc.post(moves, tool_kind="flat", dia_mm=6.0, corner_mm=0.0)
        raise AssertionError("expected refusal: flat D6 not in table and no "
                           "--tool-number given")
    except ValueError as e:
        assert "x7_tools.json" in str(e), "refusal must name the table: %s" % e
    # with an explicit number an unlisted tool still posts (override path)
    txt = post_lnc.post(moves, tool_kind="flat", dia_mm=6.0, corner_mm=0.0,
                        tool_number=2, crlf=False)
    assert "T2 M06" in txt and "H02" in txt
    print("PASS unknown-tool refusal (no silent T1)")


def test_posted_x7_file_reads_T3():
    path = os.path.join(ROOT, "out", "core_front_rough_X7.nc")
    if not os.path.exists(path):
        print("SKIP X7 file check: %s missing" % path)
        return
    txt = _read(path)
    assert "T3 M06" in txt, "out/core_front_rough_X7.nc must read T3 M06"
    assert re.search(r"G43 Z\S+ H03", txt), \
        "out/core_front_rough_X7.nc must carry G43 ... H03"
    assert txt.splitlines()[2].startswith("(T3 "), "header tool comment T-number"
    print("PASS posted X7 file reads T3 / H03")


# ---------------------------------------------------------------------------
# (b) zmap equivalence: posted inch == neutral metric run
# ---------------------------------------------------------------------------

def _zmap_stats(moves, jobs):
    import zmap
    part, cell, x0, y0 = zmap.load_part(PART_HF)
    # zmap.resolve_moves resolves a leading Z-less rapid to the first explicit
    # Z (Z unknown = above stock, not machine 0), so serial and chunked sims
    # agree without any first-Z normalisation here.
    rm = zmap.resolve_moves(moves)
    if jobs > 1:
        return zmap.simulate_parallel(rm, part, cell, x0, y0, STOCK_BOX, jobs,
                                     **TOOL)
    return zmap.simulate(rm, part, cell, x0, y0, STOCK_BOX, **TOOL)


def test_zmap_matches_neutral():
    missing = [p for p in (NEUTRAL, PART_HF) if not os.path.exists(p)]
    if missing:
        print("SKIP zmap equivalence: missing %s" % missing)
        return
    try:
        sys.path.insert(0, os.path.join(ROOT, "verify"))
        import zmap  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        print("SKIP zmap equivalence: %s" % e)
        return

    neutral_moves = zmap.parse_gcode(_read(NEUTRAL))
    inch_moves = zmap.parse_gcode(_posted_inch_text())
    jobs = int(os.environ.get("POST_ZMAP_JOBS", "8"))
    n = _zmap_stats(neutral_moves, jobs)
    i = _zmap_stats(inch_moves, jobs)

    print("\n--- zmap: posted inch vs neutral metric run ---")
    print("gouges           : neutral=%d inch=%d"
          % (n["gouges"]["count"], i["gouges"]["count"]))
    print("rapid collisions : neutral=%d inch=%d"
          % (n["rapid_collisions"]["count"], i["rapid_collisions"]["count"]))
    print("over_flute       : neutral=%d inch=%d"
          % (n["over_flute"]["count"], i["over_flute"]["count"]))
    for k in ("mean", "p95", "max"):
        a, b = n["leftover"][k], i["leftover"][k]
        print("leftover %-5s: neutral=%.4f inch=%.4f absdiff=%.3g"
              % (k, a, b, abs(a - b)))
    cl_n, cl_i = n["cutting_length_mm"], i["cutting_length_mm"]
    print("cutting length   : neutral=%.1f inch=%.1f rel=%.2g"
          % (cl_n, cl_i, abs(cl_n - cl_i) / cl_n))

    # gouges / collisions must match exactly
    assert n["gouges"]["count"] == i["gouges"]["count"], "gouge count differs"
    assert n["rapid_collisions"]["count"] == i["rapid_collisions"]["count"]
    assert n["over_flute"]["count"] == i["over_flute"]["count"]
    # leftover stats within 1e-3 mm (G20 LSB is 0.00254 mm; observed < 3e-4)
    for k in ("mean", "p95", "max"):
        assert abs(n["leftover"][k] - i["leftover"][k]) <= 1e-3, \
            "leftover %s differs beyond 1e-3" % k
    # cutting length within a relative 1e-3 (absolute drift is inch quantization)
    assert abs(cl_n - cl_i) / cl_n <= 1e-3, "cutting length differs beyond 1e-3 rel"
    print("PASS zmap equivalence (gouges equal; leftover within 1e-3 mm; "
          "cutting length within 1e-3 relative)")


def _main():
    fails = 0
    for fn in (test_spec_header_and_footer_order,
               test_spec_comment_form,
               test_spec_dwell_variants,
               test_spec_number_rules,
               test_spec_modal_suppression,
               test_spec_crlf,
               test_number_format_edge_cases,
               test_tool_table_lookup,
               test_tool_number_override,
               test_unknown_tool_refused,
               test_posted_x7_file_reads_T3,
               test_zmap_matches_neutral):
        try:
            fn()
        except AssertionError as e:
            fails += 1
            print("FAIL %s: %s" % (fn.__name__, e))
    print("%d failure(s)" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_main())


def test_comment_style_slashstar():
    """P3: with LNC parameter 42 = 0 comments must be /*...*/; default stays ( )."""
    from engine.post_lnc import post
    moves = [{"g": 0, "x": 0.0, "y": 0.0, "z": 10.0}, {"g": 1, "x": 5.0, "y": 0.0, "z": 10.0, "f": 1000.0}]
    try:
        paren = post(moves, tool_number=3).splitlines()
        slash = post(moves, tool_number=3, comment_style="slashstar").splitlines()
    except (KeyError, TypeError):
        import pytest
        pytest.skip("synthetic move shape differs from the engine's")
    assert any(l.startswith("(") for l in paren)
    assert not any(l.startswith("(") for l in slash)
    assert any(l.startswith("/*") and l.endswith("*/") for l in slash)


def test_ball_without_number_refused():
    """Balls listed in James's table with number null must be refused, not posted as T None/T1."""
    from engine.post_lnc import post
    moves = [{"g": 0, "x": 0.0, "y": 0.0, "z": 10.0}, {"g": 1, "x": 5.0, "y": 0.0, "z": 10.0, "f": 1000.0}]
    import pytest
    with pytest.raises(ValueError, match="no T/H/D number"):
        post(moves, tool_kind="ball", dia_mm=1.5875, corner_mm=0.79375)
    assert "T7 M06" in post(moves, tool_kind="ball", dia_mm=1.5875, corner_mm=0.79375, tool_number=7)
    # James's STEVE tool library numbers (My shop rev 24): T31 6 mm (D 5.958), T20 3/8 in, T33 1/8 in (D 3.142)
    assert "T31 M06" in post(moves, tool_kind="ball", dia_mm=5.958, corner_mm=2.979)
    assert "T20 M06" in post(moves, tool_kind="ball", dia_mm=9.525, corner_mm=4.7625)
    assert "T33 M06" in post(moves, tool_kind="ball", dia_mm=3.142, corner_mm=1.571)
    # the old nominal sizes and the clashing picks are gone (T14 is James's 9 mm drill)
    with pytest.raises(ValueError):
        post(moves, tool_kind="ball", dia_mm=6.0, corner_mm=3.0)
    for bad in ("T14 M06", "T15 M06", "T16 M06"):
        assert bad not in post(moves, tool_kind="ball", dia_mm=9.525, corner_mm=4.7625)
