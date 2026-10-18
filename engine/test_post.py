#!/usr/bin/env python3
"""Tests for engine/post_lnc.py (LNCv2 post).

Runnable two ways:
    /opt/homebrew/bin/python3 -m pytest engine/test_post.py -q
    /Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_post.py

(a) structural diff of our posted rough program vs reference/1001.nc over every
    NON-motion line: only tool number / op name / rpm / ZMIN-type values may
    differ (plus the reference's second-op plane restores). Prints a summary.
(b) zmap the posted inch file and confirm gouges / leftover / cutting length are
    identical (within 1e-3) to the neutral metric run out/core_front_roughG.ngc.
(c) number-formatting edge cases (0, negatives, 1.0, 0.00005 rounding, -0.0).
(d) X7 tool table (tools/x7_tools.json): lookup, --tool-number override,
    refusal for unlisted tools without a number (no silent T1).
"""
import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")

from engine import post_lnc  # noqa: E402

NEUTRAL = os.path.join(ROOT, "out", "core_front_roughG.ngc")
REFERENCE = os.path.join(ROOT, "reference", "1001.nc")
PART_HF = os.path.join(ROOT, "out", "core_front_setup_hf.npy")
STOCK_BOX = (-128.651, 128.651, -82.55, 82.55, 0.0, 60.96)
TOOL = dict(tool="bull", dia=12.7, corner=0.127, flute=25.4)

_POSTED_CACHE = {}


def _read(path):
    with open(path, newline="") as fh:
        return fh.read()


def _posted_inch_text():
    """Post the round-7 neutral roughing to LNC inch once, cache it."""
    if "inch" not in _POSTED_CACHE:
        _POSTED_CACHE["inch"] = post_lnc.post_text(
            _read(NEUTRAL), program=1001, op_name="OVERALL ROUGHING")
    return _POSTED_CACHE["inch"]


def _lines(text):
    return text.replace("\r\n", "\n").split("\n")


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
    import re as _r
    assert "T3 M06" in txt, "out/core_front_rough_X7.nc must read T3 M06"
    assert _r.search(r"G43 Z\S+ H03", txt), \
        "out/core_front_rough_X7.nc must carry G43 ... H03"
    assert txt.splitlines()[2].startswith("(T3 "), "header tool comment T-number"
    print("PASS posted X7 file reads T3 / H03")


# ---------------------------------------------------------------------------
# (a) structural diff vs reference over non-motion lines
# ---------------------------------------------------------------------------

def test_structural_diff_vs_reference():
    if not os.path.exists(REFERENCE):
        print("SKIP structural diff: reference/1001.nc missing")
        return
    ours = _lines(_posted_inch_text())
    ref = _lines(_read(REFERENCE))

    oc = post_lnc.control_sequence(ours)
    rc = post_lnc.control_sequence(ref)

    # The reference emits standalone G17 plane-restore lines only because its
    # final op arcs in G18; our line-only roughing stays in G17, so it has none.
    rc_no_plane = [t for t in rc if t != "G17"]

    print("\n--- structural diff (non-motion control lines) ---")
    print("ours control tokens: %d   ref (excl. G17 plane restores): %d"
          % (len(oc), len(rc_no_plane)))
    sm = difflib.SequenceMatcher(a=rc_no_plane, b=oc, autojunk=False)
    diffs = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        diffs += 1
        print("  %-6s ref=%s ours=%s" % (tag, rc_no_plane[i1:i2], oc[j1:j2]))
    equal = sum(i2 - i1 for t, i1, i2, j1, j2 in sm.get_opcodes()
               if t == "equal")
    print("  matching control lines: %d / %d" % (equal, len(rc_no_plane)))

    # core assertion: every non-motion control line matches the reference
    # exactly, except the reference's second-op G17 plane restores.
    assert rc_no_plane == oc, ("control-line structural mismatch; diffs=%d\n"
                               "ref(no G17)=%s\nours=%s"
                               % (diffs, rc_no_plane, oc))

    # header tool comment: only tool number and ZMIN may differ from reference
    ours_hdr = next(l for l in ours if l.startswith("(T"))
    ref_hdr = next(l for l in ref if l.startswith("(T"))
    import re
    pat = r"\(T(\d+) D=(\S+) CR=(\S+) - ZMIN=(\S+) - (.*)\)"
    om, rm = re.match(pat, ours_hdr), re.match(pat, ref_hdr)
    assert om and rm, "header tool comment not in expected form: %r / %r" % (ours_hdr, ref_hdr)
    assert om.group(2) == rm.group(2), "D differs: %s vs %s" % (om.group(2), rm.group(2))
    assert om.group(3) == rm.group(3), "CR differs"
    assert om.group(5) == rm.group(5), "tool type differs: %s vs %s" % (om.group(5), rm.group(5))
    print("  header tool comment: ours=%s\n                     ref =%s"
          % (ours_hdr, ref_hdr))
    print("  -> D=%s CR=%s type=%s identical; T and ZMIN allowed to differ"
          % (om.group(2), om.group(3), om.group(5)))

    # comment lines (op name / tool description / our comp-off note)
    ocm = post_lnc.comment_sequence(ours)
    rcm = post_lnc.comment_sequence(ref)
    print("  comment lines: ours=%d ref=%d (text may differ; both carry "
          "tool/op/description comments)" % (len(ocm), len(rcm)))
    print("PASS structural diff vs reference")


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
    for fn in (test_number_format_edge_cases,
               test_tool_table_lookup,
               test_tool_number_override,
               test_unknown_tool_refused,
               test_posted_x7_file_reads_T3,
               test_structural_diff_vs_reference,
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
