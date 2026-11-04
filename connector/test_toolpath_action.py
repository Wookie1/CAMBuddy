"""TP1: adaptive_rough_toolpath against mock STEVE.

Run: /opt/homebrew/bin/python3 -m pytest connector/test_toolpath_action.py -q
REQUEST is STEVE's first real request (testdata/steve_toolpath_request.json)
with synth_pocket's stock, heights and boxes.
"""
import copy
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import catalog as catalog_mod  # noqa: E402
import toolpath_action as tpa  # noqa: E402
from runner import EngineError  # noqa: E402
from test_connector import live, _final_body, STEP  # noqa: E402,F401

# STEVE's first live request (TP1b, SteveCAM test block, T13 flat)
with open(os.path.join(HERE, "testdata", "steve_toolpath_request.json")) as _fh:
    REAL = json.load(_fh)

# synth_pocket.step: 60 x 60 x 12 block (z 0..12) with pockets; stock = the
# block + 1 mm per side, 0.4 on top, 1 below (as test_connector's runs). The
# real request with this part's stock, heights and boxes; tool, frames and
# every field name stay as STEVE sent them.
REQUEST = copy.deepcopy(REAL["request"])
REQUEST.update({
    "setup": dict(REQUEST["setup"], stock_mm={"minimum_mm": [-31, -31, -1],
                                              "maximum_mm": [31, 31, 12.4]}),
    "limits": dict(REQUEST["limits"], feed_mm_min=3000.0, plunge_mm_min=800.0,
                   top_mm=12.4, bottom_mm=4.0, clearance_mm=20.0),
    "start_tip_mm": [-200.0, -150.0, 50.0],     # machine home, outside the box
    "retract_z_mm": 20.0,
    "margin_box": {"minimum_mm": [-45, -45, -2], "maximum_mm": [45, 45, 60]},
    "tip_envelope": {"minimum_mm": [-200, -150, -300],
                     "maximum_mm": [200, 150, 60]},
    "predecessor_stock_sha256": None,
})
SETTINGS = {"stepdown_mm": 4.0, "optimal_load_mm": 2.0}
TP = tpa.parse_request(REQUEST)
SHA = "a" * 64


def _doc():
    """A small valid document: up, over, plunge at plunge feed, cut, up."""
    return tpa.document([
        {"kind": "rapid", "end_mm": [0, 0, 30]},
        {"kind": "rapid", "end_mm": [10, 10, 30]},
        {"kind": "feed", "end_mm": [10, 10, 5], "feed_mm_min": 800},
        {"kind": "feed", "end_mm": [20, 10, 5], "feed_mm_min": 3000},
        {"kind": "rapid", "end_mm": [20, 10, 30]}], SHA)


# ------------------------------------------------------------ catalog ----

class TestCatalog:
    def test_shape(self):
        a = catalog_mod.get_action(tpa.ACTION)
        tp = a["x-steve"]["toolpath"]
        assert set(a["x-steve"]) == {"toolpath"}
        assert tp["cutters"] == ["flat"]
        assert len(tp["title"]) <= 80 and len(tp["description"]) <= 1000
        props = a["inputs"]["properties"]
        assert set(props) == {"stepdown_mm", "optimal_load_mm",
                              "stock_to_leave_mm", "load_limit"}
        for name, p in props.items():
            assert "x-steve" not in p
            assert name not in ("part", "setup", "tool", "stock", "request")
            assert not name.startswith("steve_")
        assert props["stock_to_leave_mm"]["default"] == 0.381
        assert props["load_limit"]["default"] is True
        assert "stepover" in props["optimal_load_mm"]["title"].lower()

    def test_published_with_x_steve_and_never_inch(self):
        pub = {a["name"]: a for a in catalog_mod.published_catalog()["actions"]}
        a = pub[tpa.ACTION]
        assert a["x-steve"]["toolpath"]["cutters"] == ["flat"]
        # no MM_FIELDS name: published minimums are never inch-scaled
        assert a["inputs"]["properties"]["stepdown_mm"]["minimum"] == 0.05
        assert not set(a["inputs"]["properties"]) & set(catalog_mod.MM_FIELDS)

    def test_tool_relative_defaults_and_ranges(self):
        s = tpa.settings_for({}, TP)
        assert s["stepdown_mm"] == 12.686                # 1 x D
        assert s["optimal_load_mm"] == pytest.approx(0.16 * 12.686)
        short = dict(TP, flute=8.0)
        assert tpa.settings_for({}, short)["stepdown_mm"] == 8.0
        with pytest.raises(EngineError) as e:
            tpa.settings_for({"stepdown_mm": 8.5}, short)
        assert e.value.field == "stepdown_mm"
        with pytest.raises(EngineError) as e:          # 0.5 x D = 6.343
            tpa.settings_for({"optimal_load_mm": 6.4}, TP)
        assert e.value.field == "optimal_load_mm"
        tpa.settings_for({"optimal_load_mm": 6.34}, TP)

    def test_request_refusals(self):
        ball = copy.deepcopy(REQUEST)
        ball["tool"]["cutter_type"] = "ball_end_mill"
        with pytest.raises(EngineError) as e:
            tpa.parse_request(ball)
        assert e.value.code == "tool_not_supported"
        nofl = copy.deepcopy(REQUEST)
        del nofl["tool"]["geometry"]["cutter_diameter_mm"]
        with pytest.raises(EngineError) as e:
            tpa.parse_request(nofl)
        assert e.value.field == "request.tool.geometry.cutter_diameter_mm"


# ----------------------------------------------- the real request ----

class TestRealRequest:
    """Every value the reader takes from STEVE's real request, measured."""

    def test_reader_values(self):
        tp = tpa.parse_request(REAL["request"])
        assert tp["dia"] == 12.686
        assert tp["flute"] == 50.8                   # cutter region top
        assert tp["shank"] == 2 * 6.343
        assert tp["stickout"] == 71.6
        # holder regions 71.6..106.6 r25 and 106.6..141.6 r27->23, above
        # the nose at tip + stick-out
        assert tp["holder"] == [[0.0, pytest.approx(35.0), 25.0, 25.0],
                                [pytest.approx(35.0), pytest.approx(70.0),
                                 27.0, 23.0]]
        assert tp["stock"] == ([-50.0, -40.0, 0.0], [50.0, 40.0, 38.0])
        assert (tp["feed"], tp["plunge"], tp["max_feed"], tp["rpm"]) == \
            (3429.0, 1270.0, 10000.0, 7500.0)
        assert (tp["top"], tp["bottom"], tp["clearance"]) == (35.0, 20.0, 45.0)
        assert tp["start"] == [-200.0, -150.0, 78.4]
        assert tp["retract_z"] == 45.0
        assert tp["margin_box"] == ([-61.343, -51.343, 20.0],
                                    [61.343, 51.343, 78.4])
        assert tp["posts_arcs"] is False

    def test_flat_end_mill_accepted_others_refused(self):
        for kind in ("ball_end_mill", "bull_nose_end_mill", "flat"):
            r = copy.deepcopy(REAL["request"])
            r["tool"]["cutter_type"] = kind
            with pytest.raises(EngineError) as e:
                tpa.parse_request(r)
            assert e.value.code == "tool_not_supported" and kind in str(e.value)
        r = copy.deepcopy(REAL["request"])
        r["tool"]["geometry"]["regions"][0]["segment"]["corner_radius_mm"] = 0.5
        with pytest.raises(EngineError) as e:
            tpa.parse_request(r)
        assert e.value.code == "tool_not_supported"

    def test_fingerprint_is_canonical_json_sha256(self):
        import crypto
        import hashlib
        assert hashlib.sha256(crypto.canonical_json(REAL["request"])) \
            .hexdigest() == REAL["steve_request_sha256"]

    def test_settings_and_stock_inputs_are_not_settings(self):
        values = {k: v for k, v in REAL.items()
                  if k not in tpa.STEVE_INPUTS and not k.startswith("_")}
        ok, out = catalog_mod.validate(values, tpa.ACTION)
        assert ok, out
        assert REAL["request"]["settings"] == {
            k: out[k] for k in REAL["request"]["settings"]}
        assert REAL["stock"]["format"] == "glb" and \
            REAL["stock"]["snapshot_sha256"] == \
            REAL["request"]["predecessor_stock_sha256"]

    def test_first_move_from_home_lands_inside_margin_box(self):
        """start_tip_mm is machine home, outside margin_box at its very top
        Z: the first move goes over at retract_z_mm (inside), never at the
        start height (78.4 = the box top, not one step inside)."""
        tp = tpa.parse_request(REAL["request"])
        ngc = "G21\nG0 X0 Y0 Z40\nG1 Z36 F1270\nG1 X10 F3429\nG0 Z40\n"
        mv = tpa.ngc_to_moves(ngc, tp)
        assert mv[0]["end_mm"] == [0.0, 0.0, 45.0]
        doc = tpa.document(mv, REAL["steve_request_sha256"])
        assert tpa.violations(doc, tp, REAL["steve_request_sha256"]) == []
        doc["moves"][0]["end_mm"][2] = 78.4         # the old start-height hop
        assert [lim for _f, _m, lim, _s in tpa.violations(
            doc, tp, REAL["steve_request_sha256"])] == ["margin_box",
                                                         "tip_envelope"]


# ------------------------------------------------- validator mutants ----

def _bad(doc, tp=TP, sha=SHA):
    return [(f, lim) for f, _m, lim, _msg in tpa.violations(doc, tp, sha)]


class TestValidatorMutants:
    """Each gate passes the good document and fails its mutant BY the
    measured amount: a value just inside passes, just outside fails."""

    def test_good_passes(self):
        assert _bad(_doc()) == []

    def test_outside_margin_box(self):
        hi = TP["margin_box"][1][0] - tpa.INSIDE_MM
        d = _doc()
        d["moves"][3]["end_mm"][0] = hi                 # on the inner step
        assert _bad(d) == []
        d["moves"][3]["end_mm"][0] = hi + 0.0005        # 0.5 um past it
        assert ("moves[3].end_mm", "margin_box") in _bad(d)

    def test_feed_above_op_feed(self):
        d = _doc()
        d["moves"][3]["feed_mm_min"] = 3000.0
        assert _bad(d) == []
        d["moves"][3]["feed_mm_min"] = 3000.1
        assert _bad(d) == [("moves[3].feed_mm_min", 3000.0)]

    def test_plunge_above_plunge_feed(self):
        d = _doc()
        d["moves"][2]["feed_mm_min"] = 800.1
        assert _bad(d) == [("moves[2].feed_mm_min", 800.0)]
        d["moves"][2]["end_mm"][0] = 10.5             # a ramp, not a plunge
        assert _bad(d) == []

    def test_last_move_below_retract(self):
        d = _doc()
        d["moves"][-1]["end_mm"][2] = 20.0
        assert _bad(d) == []
        d["moves"][-1]["end_mm"][2] = 19.999
        assert _bad(d) == [("moves[4].end_mm", "retract_z_mm")]

    def test_wrong_request_sha256(self):
        assert _bad(_doc(), sha="b" * 64) == [("request_sha256", "b" * 64)]

    def test_arc_when_posts_arcs_false(self):
        d = _doc()
        d["moves"][3] = {"kind": "arc", "end_mm": [20, 10, 5],
                         "center_mm": [15, 10], "direction": "cw",
                         "turns": 0, "feed_mm_min": 3000}
        assert _bad(d) == [("moves[3].kind", "posts_arcs")]
        assert _bad(d, tp=dict(TP, posts_arcs=True)) == []

    def test_extra_field_and_move_count(self):
        d = _doc()
        d["note"] = "x"
        assert ("toolpath", None) in _bad(d)
        d = _doc()
        d["moves"] = d["moves"][:2] * ((tpa.MAX_MOVES + 1) // 2) + \
            [d["moves"][-1]]
        assert ("moves", tpa.MAX_MOVES) in _bad(d)

    def test_converter_plunge_and_retract(self):
        ngc = "G21\nG0 X10 Y10 Z13.4\nG1 Z5 F3000\nG1 X20 F3000\nG0 Z14.4\n"
        mv = tpa.ngc_to_moves(ngc, TP)
        assert mv[0] == {"kind": "rapid", "end_mm": [10.0, 10.0, 20.0]}
        assert mv[2]["feed_mm_min"] == 800              # plunge held down
        assert mv[3]["feed_mm_min"] == 3000
        assert mv[-1]["end_mm"][2] == 20.0              # up to retract_z
        assert _bad(tpa.document(mv, SHA)) == []


# ------------------------------------------------------- end to end ----

class TestToolpathRun:
    def test_run_on_pocket_block(self, live):
        mock, home, _ = live
        assert tpa.ACTION in [a["name"] for a in mock.catalog["actions"]]
        mock.enqueue_run(9101, action=tpa.ACTION,
                         inputs=mock.toolpath_inputs(STEP, REQUEST, SETTINGS))
        final, body = _final_body(mock, 9101, timeout=600)
        assert final == "succeeded", body
        assert mock.file_names(9101) == ["toolpath.json"]
        info = mock.file_info(9101, "toolpath.json")
        raw = info["body"]
        doc = json.loads(raw.decode("utf-8"))
        sha = mock.toolpath_inputs(STEP, REQUEST, SETTINGS)[
            "steve_request_sha256"]
        assert doc["request_sha256"] == sha
        assert tpa.violations(doc, TP, sha) == []
        # independent of the validator: every feed <= op feed, every end
        # inside the margin box, last end at/above retract_z
        lo, hi = TP["margin_box"]
        for m in doc["moves"]:
            assert all(lo[a] < m["end_mm"][a] < hi[a] for a in range(3))
            assert m.get("feed_mm_min", 0) <= 3000
            assert m["kind"] in ("rapid", "feed")
        assert doc["moves"][-1]["end_mm"][2] >= 20.0
        r = body["result"]
        assert r["verdict"] in ("ready", "needs_review")
        assert set(r["gates"].values()) == {0}
        assert r["settings"]["stepdown_mm"] == 4.0
        assert r["n_moves"] == len(doc["moves"])
        assert "reduced_feed_windows" in r and r["max_load_mm"] > 0
        print("TP1_E2E", json.dumps({k: r[k] for k in (
            "verdict", "summary", "estimated_time_min", "n_moves",
            "max_load_mm", "engagement_over_threshold",
            "reduced_feed_windows", "gates", "clcheck_violations",
            "leftover")}), "bytes", len(raw))

    def test_limit_violation_fails_and_uploads_nothing(self, live):
        """The engine's own rapid height (stock top + 2 = 14.4) sits above a
        margin box topped at 14.0: the run fails naming margin_box, no file."""
        mock, _, _ = live
        req = copy.deepcopy(REQUEST)
        req["margin_box"]["maximum_mm"][2] = 14.0
        req["retract_z_mm"] = 13.5
        req["start_tip_mm"] = [0, 0, 13.9]
        mock.enqueue_run(9102, action=tpa.ACTION,
                         inputs=mock.toolpath_inputs(STEP, req, SETTINGS))
        final, body = _final_body(mock, 9102, timeout=600)
        assert final == "failed", body
        assert body["error"]["code"] == "toolpath_limit"
        assert body["error"]["allowed"] == "margin_box"
        assert mock.file_names(9102) == []

    def test_bad_part_digest_fails(self, live):
        mock, _, _ = live
        inp = mock.toolpath_inputs(STEP, REQUEST, SETTINGS)
        inp["part"]["sha256"] = "0" * 64
        mock.enqueue_run(9103, action=tpa.ACTION, inputs=inp)
        final, body = _final_body(mock, 9103, timeout=60)
        assert final == "failed"
        assert body["error"]["code"] == "input_digest_mismatch"
        assert mock.file_names(9103) == []
