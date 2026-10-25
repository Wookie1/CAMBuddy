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
from engine.cli import stock_box  # noqa: E402

NEUTRAL = os.path.join(ROOT, "out", "core_front_roughG.ngc")
PART_HF = os.path.join(ROOT, "out", "core_front_setup_hf.npy")
STOCK_BOX = (-128.651, 128.651, -82.55, 82.55, 0.0, 60.96)
TOOL = dict(tool="bull", dia=12.7, corner=0.127, flute=25.4)

_POSTED_CACHE = {}



def _need(*paths):
    """A real-file fixture or tracked input is missing: FAIL (never skip) with the
    regenerate hint from fixtures/manifest.json."""
    import json as _json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        man = {f["path"]: f["regenerate"] for f in _json.load(
            open(os.path.join(root, "fixtures", "manifest.json")))["fixtures"]}
    except OSError:
        man = {}
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise AssertionError("missing fixture(s): " + "; ".join(
            "%s (regenerate: %s)" % (p, man.get(os.path.relpath(p, root),
                                               "tracked in git - restore it"))
            for p in missing))


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
    _need(path)
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
    _need(NEUTRAL, PART_HF)
    sys.path.insert(0, os.path.join(ROOT, "verify"))
    import zmap  # noqa: F401  (an ImportError here is a real failure)
    import numpy  # noqa: F401

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


def test_header_cr_per_tool_type():
    """PQ: header CR is D/2 for a ball, the table corner radius for a bull,
    0 for a flat - never CR=0. on a ball because the neutral file left the
    corner unspecified."""
    moves = [{"g": 0, "x": 0.0, "y": 0.0, "z": 5.0},
             {"g": 1, "x": 5.0, "y": 0.0, "z": 5.0, "f": 1000.0}]
    # ball with CR=0 in the input (the engine CLI spec carries kind:dia only)
    ball = _lines(post_lnc.post(moves, tool_kind="ball", dia_mm=9.525,
                               corner_mm=0.0, tool_number=20, crlf=False))
    hdr = next(l for l in ball if l.startswith("(T20 "))
    assert "D=0.375" in hdr, hdr          # inch: 3/8 in
    assert "CR=0.1875" in hdr, \
        "ball header CR must be D/2, got %r" % hdr
    # bull: the table corner radius
    bull = _lines(post_lnc.post(moves, tool_kind="bull", dia_mm=12.7,
                               corner_mm=0.127, tool_number=3, crlf=False))
    assert "CR=0.005" in next(l for l in bull if l.startswith("(T3 ")), bull[2]
    # flat: corner 0 even if a bogus corner was passed
    flat = _lines(post_lnc.post(moves, tool_kind="flat", dia_mm=6.0,
                               corner_mm=0.3, tool_number=2, crlf=False))
    assert "CR=0." in next(l for l in flat if l.startswith("(T2 ")), flat[2]
    # through post_text: the neutral header's CR=0.000 ball still posts CR=D/2
    neutral = ("G21\nG90\n(T1 ball D=9.525 CR=0.000)\nS7500 M3\n"
               "G0 X0.0000 Y0.0000 Z5.0000\n"
               "G1 X5.0000 Y0.0000 Z5.0000 F1000\n")
    txt = _lines(post_lnc.post_text(neutral, tool_number=20, crlf=False))
    assert "CR=0.1875" in next(l for l in txt if l.startswith("(T20 ")), txt[2]
    print("PASS header CR: ball D/2, bull table corner, flat 0")


def test_post_rounding_noop_on_grid_snapped():
    """PQ: coordinates already on the post's output grid (metric 0.001 mm,
    inch 0.00254 mm) must survive posting unchanged - post(neutral) coords
    == neutral coords."""
    def _coords(text):
        out = []
        for l in _lines(text):
            if l.startswith("(") or not l:
                continue
            if "G53" in l or "G28" in l:
                continue          # machine home lines are not path coordinates
            for m in re.finditer(r"\b([XYZ])(-?[0-9]*\.?[0-9]+)", l):
                out.append(float(m.group(2)))
        return out

    # metric: multiples of 0.001 written at the neutral file's 4 decimals
    mm_pts = [(-30.492, 34.738, 4.051), (-30.492, 34.738, 1.000),
              (-25.123, 30.001, 1.000), (-25.123, 30.001, 4.051)]
    lines = ["G21", "G90", "(T1 bull D=12.700 CR=0.127)",
             "(ENGINE FINISH SLOPE-SPLIT)", "S7500 M3"]
    lines.append("G0 X%.4f Y%.4f Z%.4f" % mm_pts[0])
    for p in mm_pts[1:]:
        lines.append("G1 X%.4f Y%.4f Z%.4f F3429" % p)
    neutral = "\n".join(lines) + "\n"
    want = set()
    for p in mm_pts:
        want.update(round(v, 3) for v in p)
    posted = post_lnc.post_text(neutral, metric=True, program=1001,
                               tool_number=3, crlf=False)
    got = _coords(posted)
    assert got and all(v in want for v in got), \
        "mm rounding changed a coordinate: %s" % sorted(
            set(v for v in got if v not in want))[:5]

    # inch: multiples of 0.00254 mm written with 5 decimals (grid_decimals)
    in_mm = [(30.48254, 34.73196, 4.05384), (25.11428, 30.00246, 1.00064)]
    want_in = set()
    for p in in_mm:
        want_in.update(round(v / 25.4, 4) for v in p)
    lines = ["G21", "G90", "(T1 bull D=12.700 CR=0.127)",
             "(ENGINE FINISH SLOPE-SPLIT)", "S7500 M3"]
    lines.append("G0 X%.5f Y%.5f Z%.5f" % in_mm[0])
    for p in in_mm[1:]:
        lines.append("G1 X%.5f Y%.5f Z%.5f F3429" % p)
    neutral = "\n".join(lines) + "\n"
    posted = post_lnc.post_text(neutral, program=1001, tool_number=3,
                                crlf=False)
    got = _coords(posted)
    assert got and all(v in want_in for v in got), \
        "inch rounding changed a coordinate: %s" % sorted(
            set(v for v in got if v not in want_in))[:5]
    print("PASS post rounding no-op on the output grid (mm + inch)")


def _main():
    fails = 0
    for fn in (test_spec_header_and_footer_order,
               test_spec_comment_form,
               test_spec_dwell_variants,
               test_spec_number_rules,
               test_spec_modal_suppression,
               test_spec_crlf,
               test_number_format_edge_cases,
               test_header_cr_per_tool_type,
               test_post_rounding_noop_on_grid_snapped,
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
    paren = post(moves, tool_number=3).splitlines()
    slash = post(moves, tool_number=3, comment_style="slashstar").splitlines()
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


# ---------------------------------------------------------------------------
# task SX: stock_box per-axis stock margins (pure, no FreeCAD)
# ---------------------------------------------------------------------------

_CORE_FRONT_BBOX = [-126.365, 126.365, -69.85, 69.85, 0.0, 47.06239]


def test_stock_box_core_front_per_axis_exact():
    """James's real Core Front blank: 2.286 mm per side in X, 12.7 mm in Y,
    top 13.89761, bottom 0 -> the exact stock box (to 1e-6)."""
    got = stock_box(_CORE_FRONT_BBOX, 2.286, 12.7, 13.89761, 0.0)
    want = [-128.651, 128.651, -82.55, 82.55, 0.0, 60.96]
    assert len(got) == 6
    for g, w in zip(got, want):
        assert abs(g - w) < 1e-6, (got, want)


def test_stock_box_absent_axes_default_to_xy_identical():
    """stock_x/stock_y absent (both = stock_xy) gives exactly the same box
    as the old stock_xy-only arithmetic - identical floats, not just close."""
    sxy = 1.0
    pxmin, pxmax, pymin, pymax, pzmin, pzmax = _CORE_FRONT_BBOX
    legacy = [pxmin - sxy, pxmax + sxy, pymin - sxy, pymax + sxy,
              pzmin - 1.0, pzmax + 1.0]
    got = stock_box(_CORE_FRONT_BBOX, sxy, sxy, 1.0, 1.0)
    assert got == legacy, (got, legacy)


def test_stock_box_negative_is_error():
    import pytest
    with pytest.raises(ValueError):
        stock_box(_CORE_FRONT_BBOX, -0.1, 12.7, 1.0, 0.0)
    with pytest.raises(ValueError):
        stock_box(_CORE_FRONT_BBOX, 2.286, -0.1, 1.0, 0.0)


# ---------------------------------------------------------------------------
# post_arcs: engine/arcfit.py units, arcs=False byte identity, arc posting,
# G02/G03-without-centre refusal (docs/lnc5800_post_spec.md A1-A8)
# ---------------------------------------------------------------------------

import math as _math  # noqa: E402

from engine import arcfit as _arcfit  # noqa: E402


def _circle_pts(r, deg_from, deg_to, step_deg, cx=0.0, cy=0.0):
    n = int(round(abs(deg_to - deg_from) / step_deg))
    return [(cx + r * _math.cos(_math.radians(deg_from + (deg_to - deg_from) * k / n)),
             cy + r * _math.sin(_math.radians(deg_from + (deg_to - deg_from) * k / n)))
            for k in range(n + 1)]


def test_arcfit_circle_one_arc_per_half():
    """Full circle -> two <=180 deg arcs; 270 deg -> two; all CCW, on the circle."""
    for sweep, want in ((360, 2), (270, 2), (180, 1), (90, 1)):
        pts = _circle_pts(10.0, 0, sweep, 1.0)
        arcs = _arcfit.fit_polyline(pts)
        assert len(arcs) == want, (sweep, [(a[0], a[1]) for a in arcs])
        assert arcs[0][0] == 0 and arcs[-1][1] == len(pts) - 1, "arcs cover the run"
        for i0, i1, cx, cy, r, ccw, dev in arcs:
            assert ccw and abs(r - 10.0) < 1e-6 and abs(cx) < 1e-6 and abs(cy) < 1e-6
            chk = _arcfit.arc_check(pts[i0:i1 + 1], cx, cy, r)
            assert chk[1] <= _math.pi + 1e-9 and dev <= _arcfit.ARC_TOL
    # clockwise
    arcs = _arcfit.fit_polyline(_circle_pts(10.0, 90, -90, 1.0))
    assert len(arcs) == 1 and not arcs[0][5]


def test_arcfit_noise_gives_lines():
    import random
    rnd = random.Random(7)
    noisy = [(0.1 * k, rnd.uniform(-0.05, 0.05)) for k in range(200)]
    assert _arcfit.fit_polyline(noisy) == []
    jitter = [(x + rnd.uniform(-0.05, 0.05), y + rnd.uniform(-0.05, 0.05))
              for x, y in _circle_pts(10.0, 0, 180, 1.0)]
    assert _arcfit.fit_polyline(jitter) == []
    straight = [(0.1 * k, 0.0) for k in range(50)]
    assert _arcfit.fit_polyline(straight) == []
    # radius limits: 0.05 mm and 600 mm circles stay lines
    assert _arcfit.fit_polyline(_circle_pts(0.05, 0, 180, 10.0)) == []
    assert _arcfit.fit_polyline(_circle_pts(600.0, 0, 1, 0.05)) == []
    # fewer than 4 moves stays lines
    assert _arcfit.fit_polyline(_circle_pts(10.0, 0, 3, 1.0)) == []


def test_arcfit_s_curve_split():
    """S-curve (CCW half then CW half) -> one arc each way, split at the join."""
    a = _circle_pts(5.0, 180, 360, 2.0, cx=-5.0)         # CCW about (-5,0) to (0,0)
    b = _circle_pts(5.0, 180, 0, 2.0, cx=5.0)            # CW about (5,0) from (0,0)
    pts = a + b[1:]
    arcs = _arcfit.fit_polyline(pts)
    assert [x[5] for x in arcs] == [True, False], [(x[0], x[1], x[5]) for x in arcs]
    assert arcs[0][1] == len(a) - 1 == arcs[1][0], "split at the inflection"


def _circle_moves(r=10.0, step=1.0, z=-1.0, cx=0.0, cy=0.0):
    pts = _circle_pts(r, 0, 360, step, cx, cy)
    mv = [{"g": 0, "x": pts[0][0], "y": pts[0][1], "z": 5.0},
          {"g": 1, "x": pts[0][0], "y": pts[0][1], "z": z, "f": 1000.0}]
    mv += [{"g": 1, "x": x, "y": y, "z": z, "f": 1000.0} for x, y in pts[1:]]
    mv.append({"g": 0, "x": pts[-1][0], "y": pts[-1][1], "z": 5.0})
    return mv


# sha256 of main 681f551's post_lnc output on the test_post fixtures
_MAIN_SHA = {
    "syn_mm": "2c0dc6b104c4dc36ce3366b6563b387af29d50a9b6b6dc850772da7c4017369b",
    "syn_in": "4aefb21242d900bfdb6c3878f449ceeea2e982eb092e7a735197a3f013a9695a",
    "syn_dwell_x": "a6de7b890174ab7d8ffa11eaf879389f684996183c8337b69ae9a6118d48c987",
    "syn_crlf": "056ebfd4a754c1d53c7ca3bb12ea5a0c804668da09e72077bd8453698ef43098",
    "syn_slash": "4ea92f2483738a167d91674abcd9533501457f9e938ba0a605ac34b8c2de60bc",
    "cf_inch": "1f8b89ae6a8d2cb3654e9ad9adc50ee42eb4ad17bec3bfdf6f97f934f33f2b29",
    "cf_mm_t5": "bfbbf7ead9c11b44873d5304f747b0e6a3d44aa1e1c2348ee0bc254521e5b015",
    "cr_ball": "dcd5501b4b51e3f1d0cd4aaed8ed01a6b8ec1734bf515427f5f4a3eef6455800",
}


def test_arcs_off_byte_identical_to_main():
    """arcs=False (explicit and default) reproduces main's bytes on every fixture."""
    import hashlib
    _need(NEUTRAL)
    neu = _read(NEUTRAL)
    mv = [{"g": 0, "x": 0.0, "y": 0.0, "z": 5.0},
          {"g": 1, "x": 5.0, "y": 0.0, "z": 5.0, "f": 1000.0}]
    for extra in ({}, {"arcs": False}):
        syn = lambda **kw: post_lnc.post(SYN_MOVES, tool_number=2, rpm=7500,  # noqa: E731
                                         dia_mm=6.0, corner_mm=0.0, tool_kind="flat",
                                         op_name="SPEC TEST", crlf=False, **dict(extra, **kw))
        got = {
            "syn_mm": syn(metric=True), "syn_in": syn(metric=False),
            "syn_dwell_x": syn(metric=True, dwell_p_ms=False),
            "syn_crlf": post_lnc.post(SYN_MOVES, metric=True, tool_number=2,
                                      tool_kind="flat", dia_mm=6.0, **extra),
            "syn_slash": post_lnc.post(SYN_MOVES, tool_number=3,
                                       comment_style="slashstar", **extra),
            "cf_inch": post_lnc.post_text(neu, program=1001,
                                          op_name="OVERALL ROUGHING", **extra),
            "cf_mm_t5": post_lnc.post_text(neu, program=1001, op_name="OVERALL ROUGHING",
                                           tool_number=5, metric=True, crlf=False, **extra),
            "cr_ball": post_lnc.post(mv, tool_kind="ball", dia_mm=9.525, corner_mm=0.0,
                                     tool_number=20, crlf=False, **extra),
        }
        for k, txt in got.items():
            assert hashlib.sha256(txt.encode()).hexdigest() == _MAIN_SHA[k], \
                "arcs off changed %s (%r)" % (k, extra)


def _arc_lines(txt):
    return [l for l in _lines(txt) if re.search(r"\bI-?[0-9.]+ J-?[0-9.]+", l)]


def test_arcs_on_circle_posts_ij_arcs():
    """arcs=True: circle -> G03 arcs with incremental I/J, decimals on I/J,
    start/end radius within 0.0005 mm after rounding, strict-judge clean."""
    sys.path.insert(0, os.path.join(ROOT, "verify"))
    import zmap
    for metric, dec in ((True, 3), (False, 4)):
        for cx, cy in ((0.0, 0.0), (3.21234, -7.65432)):
            mv = _circle_moves(cx=cx, cy=cy)
            txt = post_lnc.post(mv, metric=metric, tool_number=2, tool_kind="flat",
                                dia_mm=6.0, crlf=False, arcs=True)
            arcs = _arc_lines(txt)
            assert len(arcs) == 2, arcs
            assert arcs[0].startswith("G03 "), arcs[0]
            assert "G02" not in txt
            assert zmap.strict_check(txt) == [], zmap.strict_check(txt)
            for l in arcs:
                for letter, num in re.findall(r"\b([IJ])(-?[0-9.]+)", l):
                    assert "." in num and len(num.split(".")[1]) <= dec, l
            # replay: centre = start + (I, J); radii agree within the A6 limit
            u = 1.0 if metric else 25.4
            pos = None
            for m in zmap.resolve_moves(zmap.parse_gcode(txt)):
                if m["motion"] in ("G2", "G3"):
                    c = (pos[0] + m["i"], pos[1] + m["j"])
                    r1 = _math.hypot(pos[0] - c[0], pos[1] - c[1])
                    r2 = _math.hypot(m["x"] - c[0], m["y"] - c[1])
                    assert abs(r1 - r2) <= _arcfit.ARC_END_MISMATCH + 1e-12
                    assert abs(r1 - 10.0) <= 0.003, r1
                    assert abs(c[0] - cx) <= 0.002 * u and abs(c[1] - cy) <= 0.002 * u
                pos = (m["x"], m["y"], m["z"])
    # fewer lines than the linear post
    lin = post_lnc.post(_circle_moves(), metric=True, tool_number=2, tool_kind="flat",
                        dia_mm=6.0, crlf=False)
    arc = post_lnc.post(_circle_moves(), metric=True, tool_number=2, tool_kind="flat",
                        dia_mm=6.0, crlf=False, arcs=True)
    assert len(_lines(arc)) < len(_lines(lin)) - 300


def test_arcs_on_keeps_non_planar_and_short_runs_as_lines():
    """A ramp (Z changes) and SYN_MOVES (3 feed moves) post unchanged with arcs."""
    ramp = [{"g": 0, "x": 10.0, "y": 0.0, "z": 5.0}]
    for k, (x, y) in enumerate(_circle_pts(10.0, 0, 180, 1.0)):
        ramp.append({"g": 1, "x": x, "y": y, "z": -0.01 * k, "f": 1000.0})
    kw = dict(metric=True, tool_number=2, tool_kind="flat", dia_mm=6.0, crlf=False)
    assert post_lnc.post(ramp, arcs=True, **kw) == post_lnc.post(ramp, **kw)
    assert post_lnc.post(SYN_MOVES, arcs=True, **kw) == post_lnc.post(SYN_MOVES, **kw)
    # a feed change mid-circle splits the run but still fits both parts
    mv = _circle_moves()
    for m in mv[100:]:
        if m["g"] == 1:
            m["f"] = 500.0
    txt = post_lnc.post(mv, arcs=True, **kw)
    assert "F500." in txt and len(_arc_lines(txt)) >= 3


def test_g2_g3_without_centre_refused():
    """The latent bug: g 2/3 moves used to post as G02/G03 with no I/J."""
    import pytest
    base = [{"g": 0, "x": 0.0, "y": 0.0, "z": 5.0},
            {"g": 1, "x": 0.0, "y": 0.0, "z": 0.0, "f": 500.0}]
    kw = dict(metric=True, tool_number=2, tool_kind="flat", dia_mm=6.0)
    for g in (2, 3):
        with pytest.raises(ValueError, match="no centre data"):
            post_lnc.post(base + [{"g": g, "x": 10.0, "y": 0.0, "z": 0.0, "f": 500.0}], **kw)
        with pytest.raises(ValueError, match="no centre data"):
            post_lnc.post_text("G21\nG90\nG0 X0 Y0 Z5\nG1 Z0 F500\nG%d X10 Y0 I5 J0\n" % g, **kw)
    # an explicit arc with a centre posts; a helical one is refused
    txt = post_lnc.post(base + [{"g": 3, "x": 10.0, "y": 0.0, "z": 0.0, "f": 500.0,
                                 "cx": 5.0, "cy": 0.0}], crlf=False, **kw)
    assert "G03 X10. I5. J0." in txt
    with pytest.raises(ValueError, match="helical"):
        post_lnc.post(base + [{"g": 3, "x": 10.0, "y": 0.0, "z": -1.0, "f": 500.0,
                               "cx": 5.0, "cy": 0.0}], **kw)
    with pytest.raises(ValueError, match="not on the arc"):
        post_lnc.post(base + [{"g": 3, "x": 10.0, "y": 0.0, "z": 0.0, "f": 500.0,
                               "cx": 4.0, "cy": 0.0}], **kw)


def test_arc_rounding_failure_falls_back_to_lines():
    """An arc whose rounded centre misses A6 / ARC_TOL is posted as its source lines."""
    kw = dict(metric=True, tool_number=2, tool_kind="flat", dia_mm=6.0, crlf=False)
    mv = _circle_moves()
    lin = post_lnc.post(mv, **kw)
    bad = mv[:2] + [{"g": 3, "x": mv[-2]["x"], "y": mv[-2]["y"], "z": -1.0,
                     "f": 1000.0, "cx": 0.5, "cy": 0.0, "src": mv[2:-1]}] + mv[-1:]
    assert post_lnc.post(bad, **kw) == lin


def test_cli_post_arcs_flag(tmp_path):
    from engine import cli
    src = tmp_path / "c.ngc"
    lines = ["G21", "G90", "(T1 flat D=6.000 CR=0.000)", "S7500 M3"]
    for m in _circle_moves():
        lines.append("G%d X%.4f Y%.4f Z%.4f%s" % (m["g"], m["x"], m["y"], m["z"],
                                               " F1000" if m["g"] == 1 else ""))
    src.write_text("\n".join(lines) + "\n")
    off, on = tmp_path / "off.nc", tmp_path / "on.nc"
    base = ["post", "--in", str(src), "--metric", "--tool-number", "2"]
    assert cli.main(base + ["--out", str(off)]) == 0
    assert cli.main(base + ["--out", str(on), "--arcs"]) == 0
    assert not _arc_lines(off.read_text()) and len(_arc_lines(on.read_text())) == 2


def _seg_dist(p, a, b):
    d = [b[k] - a[k] for k in range(3)]
    L2 = sum(v * v for v in d)
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, sum((p[k] - a[k]) * d[k] for k in range(3)) / L2))
    return _math.sqrt(sum((p[k] - a[k] - t * d[k]) ** 2 for k in range(3)))


def test_posted_arcs_replay_onto_original_path():
    """Replay the POSTED program with verify/zmap's own G2/G3 interpreter
    (parse_gcode -> resolve_moves/_arc_geom -> _move_samples, the sampler its
    simulator sweeps; nothing from post_lnc/arcfit), sample every arc along its
    stated direction and measure the max distance to the ORIGINAL neutral feed path.
    Catches a flipped G02/G03 (the wrong-way sweep is ~radius off)."""
    sys.path.insert(0, os.path.join(ROOT, "verify"))
    import zmap
    quarter = [{"g": 0, "x": 10.0, "y": 0.0, "z": 5.0},
               {"g": 1, "x": 10.0, "y": 0.0, "z": -1.0, "f": 1000.0}]
    quarter += [{"g": 1, "x": x, "y": y, "z": -1.0, "f": 1000.0}
                for x, y in _circle_pts(10.0, 0, 90, 1.0)[1:]]
    quarter.append({"g": 0, "x": 0.0, "y": 10.0, "z": 5.0})
    cw = [dict(m, y=-m["y"]) for m in quarter]          # mirrored: clockwise quarter
    for name, mv in (("circle", _circle_moves()), ("quarter_ccw", quarter),
                     ("quarter_cw", cw)):
        feed = [m for m in mv if m["g"] == 1]
        orig = [(m["x"], m["y"], m["z"]) for m in feed]
        segs = list(zip(orig, orig[1:]))
        for metric in (True, False):
            txt = post_lnc.post(mv, metric=metric, tool_number=2, tool_kind="flat",
                                dia_mm=6.0, crlf=False, arcs=True)
            n_arcs, max_dev, pos = 0, 0.0, None
            for m in zmap.resolve_moves(zmap.parse_gcode(txt)):
                if m["motion"] in ("G2", "G3") and pos is not None:
                    assert m.get("arc"), "zmap could not resolve the arc: %r" % m
                    n_arcs += 1
                    # zmap's own interpolator (the one its simulator sweeps)
                    pts, _ = zmap._move_samples(m, pos, 0.4)
                    for p in pts:
                        max_dev = max(max_dev, min(_seg_dist(p, s0, s1) for s0, s1 in segs))
                pos = (m["x"], m["y"], m["z"])
            assert n_arcs >= 1, (name, metric)
            # inch output carries up to 0.00254/2 mm of coordinate rounding on top
            lim = _arcfit.ARC_TOL + (0.0 if metric else 0.0013)
            assert max_dev <= lim, \
                "%s metric=%s: posted arcs replay %.4f mm from the original path (limit %.4f)" \
                % (name, metric, max_dev, lim)
