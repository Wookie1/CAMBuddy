"""TP1: adaptive_rough_toolpath against mock STEVE.

Run: /opt/homebrew/bin/python3 -m pytest connector/test_toolpath_action.py -q
GUESS: REQUEST below follows docs/steve_toolpath_actions.md; every nested
shape the docs do not state is marked GUESS (TP1b confirms with a real
request).
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

with open(os.path.join(HERE, "..", "tools", "x7_tools.json")) as _fh:
    _HOLDER = json.load(_fh)["holders"]["BT30-ER32-70"]["segments"]

# synth_pocket.step: 60 x 60 x 12 block (z 0..12) with pockets; stock = the
# block + 1 mm per side, 0.4 on top, 1 below (as test_connector's runs)
REQUEST = {
    "action": tpa.ACTION,
    "part": {"document_id": "doc-tp", "revision": 1},          # GUESS
    "operation_id": "rough",                                   # GUESS
    "setup": {"stock_mm": {"minimum_mm": [-31, -31, -1],       # GUESS shape
                           "maximum_mm": [31, 31, 12.4]},
              "work_offset": 1, "model_to_work": None,
              "work_to_machine": None},
    "tool": {"assembly_sha256": "0" * 64, "cutter_type": "flat",
             "geometry": {                                     # GUESS
                 "tool": {"diameter_mm": 12.686, "corner_radius_mm": 0.0,
                          "flute_length_mm": 50.8,
                          "shank_diameter_mm": 12.686, "stickout_mm": 71.6},
                 "holder": {"segments": _HOLDER}}},
    "predecessor_stock_sha256": None,
    "limits": {"spindle_rpm": 7500, "feed_mm_min": 3000,      # GUESS keys
               "plunge_mm_min": 800, "machine_max_feed_mm_min": 10000,
               "top_mm": 12.4, "bottom_mm": 4.0, "clearance_mm": 20.0,
               "tolerance_mm": 0.01},
    "start_tip_mm": [0, 0, 50.0],
    "retract_z_mm": 20.0,
    "margin_box": {"minimum_mm": [-45, -45, -2],              # GUESS shape
                   "maximum_mm": [45, 45, 60]},
    "tip_envelope": {"minimum_mm": [-45, -45, -2],            # GUESS shape
                     "maximum_mm": [45, 45, 60]},
    "posts_arcs": False,
}
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
        ball["tool"]["cutter_type"] = "ball"
        with pytest.raises(EngineError) as e:
            tpa.parse_request(ball)
        assert e.value.code == "tool_not_supported"
        nofl = copy.deepcopy(REQUEST)
        del nofl["tool"]["geometry"]["tool"]["flute_length_mm"]
        with pytest.raises(EngineError) as e:
            tpa.parse_request(nofl)
        assert e.value.field == "request.tool.geometry.tool.flute_length_mm"


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
        assert mv[0] == {"kind": "rapid", "end_mm": [10.0, 10.0, 50.0]}
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
