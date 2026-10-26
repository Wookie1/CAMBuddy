"""Catalog v1: actions adaptive_rough + slope_split_finish, event
engine_state, and input validation (required / enum / numeric range). All
mm-valued inputs are validated in mm; a run with units=="inch" has its mm
values converted by the runner after validation.
"""
import difflib

import errors

ACTION = "adaptive_rough"
SLOPE_ACTION = "slope_split_finish"
CHECK_ACTION = "check_program"
ACTIONS = (ACTION, SLOPE_ACTION, CHECK_ACTION)
# track 2 (toollib): library + per-document job renumbering, no engine work
TOOLS_LIST = "tools.list"
TOOLS_UPDATE = "tools.update"
JOB_GET = "job.get"
JOB_RENUMBER = "job.renumber"
JOB_SETUP = "job.setup"
TOOL_ACTIONS = (TOOLS_LIST, TOOLS_UPDATE, JOB_GET, JOB_RENUMBER, JOB_SETUP)
# track 2 (b): measure the oriented model (engine prepare path, no cutting)
MEASURE_ACTION = "model.measure"
ENGINE_ACTIONS = ACTIONS + (MEASURE_ACTION,)
EVENT = "engine_state"

# inputs whose numeric value is a length/feeds in mm (or mm/min):
MM_FIELDS = ("stock_xy", "stock_x", "stock_y", "stock_top", "stock_bottom",
             "floor_z",
             "tool_diameter", "corner_radius", "flute_length", "stepdown",
             "optimal_load", "stock_to_leave", "rest_stepup", "feed",
             "ramp_feed",
             # slope_split_finish:
             "stepover", "rough_tool_diameter", "rough_corner_radius",
             "rough_flute_length", "rough_stepdown", "rough_optimal_load",
             "rough_stock_to_leave", "rough_rest_stepup", "min_rest",
             # rest-rough (engine.cli rest-rough):
             "rest_rough_ae", "rest_rough_stepdown", "rest_rough_leave",
             "rest_rough_min_excess", "rest_rough_min_helix_r",
             "rest_rough_cut_feed", "rest_rough_ramp_feed")

_ORIENTATION = {"type": "string",
                "enum": ["as_modeled", "flip_x_180", "flip_y_180",
                         "flip_z_180", "rot_x_90", "rot_x_270", "rot_y_90",
                         "rot_y_270"],
                "description": "how the model stands on the table before "
                               "the stock box is built: flip_*_180 turns it "
                               "over about that axis; rot_x/rot_y_90/270 "
                               "turn it about X or Y by that angle "
                               "(right-hand rule: rot_x_90 carries +Y to "
                               "+Z), all about the model's box centre",
                "default": "as_modeled",
                "title": "Orientation"}

# task (e): the work origin. The runner moves the oriented model so the
# chosen point of the STOCK box (allowances applied) is X0 Y0 Z0;
# model_origin keeps the STEP's own frame (no move).
ORIGINS = ["stock_bottom_centre", "stock_top_centre", "model_origin"]
_ORIGIN_TEXT = ("where X0 Y0 Z0 of the program sits: stock_bottom_centre = "
                "centre of the stock box's bottom face, stock_top_centre = "
                "centre of its top face (both after orientation and stock "
                "allowances), model_origin = the STEP model's own origin")
_ORIGIN = {"type": "string", "enum": ORIGINS,
           "default": "stock_bottom_centre", "title": "Work origin",
           "description": _ORIGIN_TEXT}
# check_program judges a program that was posted elsewhere: TL2 item 1 makes
# origin REQUIRED there - validate() refuses a check_program that omits it
# (no default: the schema never advertises a guess).
_ORIGIN_CHECK = dict({k: v for k, v in _ORIGIN.items() if k != "default"},
                     description=_ORIGIN_TEXT + "; REQUIRED: give the "
                     "origin the program was posted with")

_DOCUMENT_ID = {"type": "string", "maxLength": 128,
                "title": "STEVE document id",
                "description": "applies this document's job tool "
                               "renumbering (job.renumber); defaults to the "
                               "model's STEVE document"}

_DOC_ID_INPUT = {"type": "string", "maxLength": 128,
                 "title": "STEVE document id"}

_STOCK_INPUTS = {
    "stock_xy": {"type": "number", "minimum": 0.0, "maximum": 25.4,
                 "default": 1.0,
                 "description": "extra material left around the part, per "
                                "side, mm"},
    "stock_x": {"type": "number", "minimum": 0.0,
                "description": "Extra stock on each side in X (defaults to "
                               "the XY value)"},
    "stock_y": {"type": "number", "minimum": 0.0,
                "description": "Extra stock on each side in Y (defaults to "
                               "the XY value)"},
    "stock_top": {"type": "number", "minimum": 0.0,
                  "maximum": 25.4, "default": 1.0,
                  "description": "extra material above the top of the part, "
                                 "mm"},
    "stock_bottom": {"type": "number", "minimum": 0.0,
                     "maximum": 25.4, "default": 1.0,
                     "description": "extra material under the bottom of the "
                                    "part, mm"},
    "floor_z": {"type": "number", "minimum": 0.0,
                "maximum": 200.0, "default": 0.0,
                "description": "roughing floor height above the stock "
                               "bottom, mm"},
}

# roughing tool + cutting data inputs (defaults mirror adaptive_rough);
# the slope_split_finish action prefixes them with "rough_"
_ROUGHING_INPUTS = {
    "tool_type": {"type": "string", "enum": ["flat", "bull"],
                  "default": "bull", "title": "Tool type",
                  "description": "roughing end mill kind; a ball is refused "
                                 "- adaptive roughing runs flat or bull only"},
    "tool_diameter": {"type": "number", "minimum": 1.0,
                      "maximum": 32.0, "default": 12.7},
    "corner_radius": {"type": "number", "minimum": 0.0,
                      "maximum": 8.0, "default": 0.127},
    "flute_length": {"type": "number", "minimum": 1.0,
                     "maximum": 150.0, "default": 30.0},
    "stepdown": {"type": "number", "minimum": 0.1,
                 "maximum": 25.4, "default": 19.05},
    "optimal_load": {"type": "number", "minimum": 0.05,
                     "maximum": 10.0, "default": 2.03,
                     "description": "steady side load the roughing aims "
                                    "for, mm"},
    "stock_to_leave": {"type": "number", "minimum": 0.0,
                       "maximum": 5.0, "default": 0.381},
    "rest_stepup": {"type": "number", "minimum": 0.1,
                    "maximum": 10.0, "default": 1.905},
}

_CUTTING_INPUTS = {
    "rpm": {"type": "integer", "minimum": 100, "maximum": 30000,
            "default": 7500},
    "feed": {"type": "number", "minimum": 10.0,
             "maximum": 20000.0, "default": 3429.0,
             "description": "cutting feed mm/min"},
    "ramp_feed": {"type": "number", "minimum": 10.0,
                  "maximum": 20000.0, "default": 1270.0},
    "units": {"type": "string", "enum": ["inch", "mm"],
              "default": "inch",
              "description": "units of every length and feed input and of "
                             "the posted program: inch (the default when "
                             "omitted) or mm. Lengths are inch or mm, feeds "
                             "inch/min or mm/min; ranges below are listed "
                             "in both"},
    "program_number": {"type": "integer", "minimum": 1,
                       "maximum": 9999, "default": 1001},
}

ROUGHING_ACTION = {
    "name": ACTION,
    "title": "Adaptive roughing",
    "description": ("Use to rough a STEP part out of its stock box with a "
                    "flat or bull end mill (nothing is sent to the "
                    "machine). Returns the posted rough.nc, check.json and "
                    "preview.png with a verdict, a one-line summary and "
                    "the items needing attention."),
    "confirm": False,
    "inputs": {
        "type": "object",
        "properties": {
            "model": {"x-steve": "file", "format": "step",
                      "title": "STEP model"},
            "orientation": _ORIENTATION,
            "origin": _ORIGIN,
            **_STOCK_INPUTS,
            **{k: v for k, v in _ROUGHING_INPUTS.items()},
            **_CUTTING_INPUTS,
            "tool_number": {"type": "integer", "minimum": 1,
                            "maximum": 999,
                            "description": "machine tool number; if blank, "
                                         "the X7 tool table picks the tool"},
            "document_id": _DOCUMENT_ID,
        },
        "required": ["model"],
    },
    "result": ("Estimated time, cut length, zmap gouges, rapid "
               "collisions, over-flute and leftover mean/p95/"
               "within_0p5mm; files: .nc, check.json, preview.png."),
}

# rest-rough (engine.cli rest-rough) parameters + CONNECTOR DEFAULTS: James's
# confirmed T20 values (3/8" ball = tools/x7_tools.json #20). Parameters only -
# the engine takes them as arguments and carries no machine-specific numbers.
_REST_ROUGH_INPUTS = {
    "rest_rough_tool_number": {"type": "integer", "minimum": 1, "maximum": 999,
                               "default": 20,
                               "description": "ball tool for the rest-rough pass "
                                            "(default 20 = 3/8\" ball, tools/"
                                            "x7_tools.json: dia 9.525, flute "
                                            "22.225, stickout 46.2, holder "
                                            "BT30-ER20-60)"},
    "rest_rough_ae": {"type": "number", "minimum": 0.1, "maximum": 9.525,
                      "default": 1.905,
                      "description": "max radial engagement / stepover mm "
                                    "(20 % of D 9.525)"},
    "rest_rough_stepdown": {"type": "number", "minimum": 0.1, "maximum": 20.0,
                            "default": 2.0,
                            "description": "level stepdown mm"},
    "rest_rough_leave": {"type": "number", "minimum": 0.05, "maximum": 2.0,
                         "default": 0.2,
                         "description": "stock left on the part for the finish, "
                                        "mm"},
    "rest_rough_min_excess": {"type": "number", "minimum": 0.1,
                              "maximum": 20.0, "default": 0.5,
                              "description": "zone threshold mm: live stock "
                                           "above the T20 ball CL surface that "
                                           "must come off before the finish"},
    "rest_rough_min_helix_r": {"type": "number", "minimum": 0.5,
                               "maximum": 4.7625, "default": 1.903,
                               "description": "smallest largest-CL-circle radius "
                                            "mm that earns a 2-deg helix entry; "
                                            "pockets below it are reported, not "
                                            "entered"},
    "rest_rough_cut_feed": {"type": "number", "minimum": 10.0,
                            "maximum": 10000.0, "default": 1920.0,
                            "description": "cutting feed mm/min (aluminium, "
                                         "0.06 mm/z x 4 flutes x 8000 rpm)"},
    "rest_rough_ramp_feed": {"type": "number", "minimum": 10.0,
                             "maximum": 10000.0, "default": 716.0,
                             "description": "ramp / helix feed mm/min"},
    "rest_rough_spindle": {"type": "integer", "minimum": 100,
                           "maximum": 10000, "default": 8000,
                           "description": "spindle rpm (vc ~239 m/min at D "
                                        "9.525 in aluminium; X7 max 10000)"},
}

SLOPE_ACTION_SPEC = {
    "name": SLOPE_ACTION,
    "title": "Slope-split finishing",
    "description": ("Use to finish a STEP part with a ball nose: it roughs "
                    "first, then finishes steep walls and flat areas "
                    "separately (run after roughing: rough.nc before "
                    "finish.nc, plus rest.nc with rest_tool_number). "
                    "Returns all posted programs and check.json with a "
                    "verdict, summary and attention items."),
    "confirm": False,
    "inputs": {
        "type": "object",
        "properties": {
            "model": {"x-steve": "file", "format": "step",
                      "title": "STEP model"},
            "orientation": _ORIENTATION,
            "origin": _ORIGIN,
            **_STOCK_INPUTS,
            # finishing tool (ball) + cutting data
            "tool_diameter": {"type": "number", "minimum": 1.0,
                              "maximum": 25.0, "default": 6.0,
                              "description": "finishing ball nose diameter, "
                                             "mm"},
            "stepover": {"type": "number", "minimum": 0.05,
                         "maximum": 2.0, "default": 0.3,
                         "description": "distance between raster rows on flat "
                                      "areas, mm"},
            "stepdown": {"type": "number", "minimum": 0.05,
                         "maximum": 2.0, "default": 0.3,
                         "description": "depth of each contour level on steep "
                                      "walls, mm"},
            "slope_threshold": {"type": "number", "minimum": 10.0,
                                "maximum": 80.0, "default": 40.0,
                                "description": "angle in degrees that splits "
                                             "steep walls from flat areas"},
            **_CUTTING_INPUTS,
            "tool_number": {"type": "integer", "minimum": 1,
                            "maximum": 999,
                            "description": "machine tool number for the "
                                         "finishing ball; if blank, tools/"
                                         "x7_tools.json is used - the run "
                                         "fails if the ball is not in the "
                                         "table and no number is given"},
            # optional corner rest pass after the finish (task CR): a smaller
            # ball from tools/x7_tools.json cuts only where the finish ball
            # left more than min_rest mm standing; absent = no rest pass
            "rest_tool_number": {"type": "integer", "minimum": 1,
                                 "maximum": 999,
                                 "description": "optional machine tool number "
                                              "of a ball in tools/"
                                              "x7_tools.json for a corner rest "
                                              "pass after the finish (posted as "
                                              "rest.nc, program number +2); "
                                              "absent = no rest pass; an "
                                              "unknown tool or a tool without "
                                              "a holder fails the run"},
            "min_rest": {"type": "number", "minimum": 0.1,
                         "default": 0.5,
                         "description": "rest the finish ball leaves (mm) that "
                                        "triggers the rest pass; minimum 0.1"},
            # roughing tool + cutting data (defaults as in adaptive_rough)
            **{"rough_" + k: v for k, v in _ROUGHING_INPUTS.items()},
            # rest-rough parameters + defaults live in _REST_ROUGH_INPUTS
            # (above) and runner.REST_ROUGH_DEFAULTS: they are NOT merged
            # into this action's inputs - the action-shape contract caps
            # inputs at 30 (test_action_shape) and rest-rough is a separate
            # engine.cli command.
            "document_id": _DOCUMENT_ID,
        },
        "required": ["model"],
    },
    "result": ("Combined summary: estimated time and cut length for the "
               "chain, probe_clcheck count (0 required), chained zmap "
               "gouges / rapid collisions / leftover; files: rough.nc, "
               "finish.nc, check.json, preview.png (plus rest.nc and a rest "
               "section when a rest tool is given)."),
}

CHECK_ACTION_SPEC = {
    "name": CHECK_ACTION,
    "title": "Check a posted program",
    "description": ("Use to judge up to three posted programs (yours or "
                    "STEVE's) against the part and stock with the "
                    "independent zmap; the program's T word picks the tool. "
                    "Returns check.json and preview.png with a verdict, "
                    "summary and attention items; no program is posted."),
    "confirm": False,
    "inputs": {
        "type": "object",
        "properties": {
            "program": {"x-steve": "program", "title": "Posted program"},
            "program_2": {"x-steve": "program",
                          "title": "Second program (optional)"},
            "program_3": {"x-steve": "program",
                          "title": "Third program (optional)"},
            "model": {"x-steve": "file", "format": "step",
                      "title": "STEP model"},
            "orientation": _ORIENTATION,
            "origin": _ORIGIN_CHECK,
            **{k: v for k, v in _STOCK_INPUTS.items() if k != "floor_z"},
            "tool_number": {"type": "integer", "minimum": 1,
                            "maximum": 999,
                            "description": "optional override of the "
                                         "program's T word; the tool comes "
                                         "from tools/x7_tools.json"},
            "document_id": _DOCUMENT_ID,
        },
        "required": ["program", "model"],
    },
    "result": ("zmap gates (gouges, rapid collisions, over-flute/shank, "
               "holder, outside grid), the engagement report (no threshold "
               "unless an optimal load is given) and any unsupported codes "
               "with their lines; files: check.json, preview.png."),
}

MEASURE_ACTION_SPEC = {
    "name": MEASURE_ACTION,
    "title": "Measure the model",
    "description": "Stands the STEP model the way you choose and returns "
                   "its size and bounding box in mm, from the same "
                   "orientation code the cutting actions use to build the "
                   "stock box. Nothing is cut or posted.",
    "confirm": False,
    "inputs": {"type": "object", "properties": {
        "model": {"x-steve": "file", "format": "step",
                  "title": "STEP model"},
        "orientation": _ORIENTATION},
        "required": ["model"]},
    "result": "{size_mm: {x, y, z}, bbox_mm: {min: [x, y, z], max: "
              "[x, y, z]}} after orientation",
}

TOOL_ACTION_SPECS = [
    {"name": TOOLS_LIST, "title": "List the tool library",
     "description": "The X7 tool library (~/.stevecam/tools.json): every "
                    "tool with its stable tool_id and library T/H/D, plus "
                    "the pocket count. Unknown fields are null.",
     "confirm": False,
     "inputs": {"type": "object", "properties": {}},
     "result": "{tools: [{tool_id, t, h, d, name, type, dia_mm, "
               "corner_r_mm, flute_len_mm, reach_mm, holder, rpm, "
               "feed_mm_min, plunge_mm_min}], pockets}"},
    {"name": TOOLS_UPDATE, "title": "Edit a library tool",
     "description": "Changes one tool in the library (never the repo "
                    "table): changes is {field: value} over t, name, type, "
                    "dia_mm, corner_r_mm, flute_len_mm, reach_mm, holder, "
                    "rpm, feed_mm_min, plunge_mm_min (h and d follow t). "
                    "pockets sets the pocket count.",
     "confirm": False,
     "inputs": {"type": "object", "properties": {
         "tool_id": {"type": "string", "maxLength": 64},
         "changes": {"type": "object"},
         "pockets": {"type": "integer"}}},
     "result": "{tool: <tools.list entry>, pockets} or {code, message}"},
    {"name": JOB_GET, "title": "Job tool numbers",
     "description": "This document's job renumbering and the tools its "
                    "runs used.",
     "confirm": False,
     "inputs": {"type": "object",
                "properties": {"document_id": _DOC_ID_INPUT},
                "required": ["document_id"]},
     "result": "{document_id, renumber: {tool_id: t}, tools_used: "
               "[tool_id], setup: {...} or null}"},
    {"name": JOB_RENUMBER, "title": "Renumber a tool for this job",
     "description": "Posts tool_id as T t (and H/D) for this document "
                    "only; the library is unchanged. Refused when another "
                    "tool already has T t in the job (duplicate_t) or t is "
                    "outside 1..pockets (out_of_range).",
     "confirm": False,
     "inputs": {"type": "object", "properties": {
         "document_id": _DOC_ID_INPUT,
         "tool_id": {"type": "string", "maxLength": 64},
         "t": {"type": "integer"}},
         "required": ["document_id", "tool_id", "t"]},
     "result": "the job (as job.get) or {code, message}"},
    {"name": JOB_SETUP, "title": "Save this job's setup",
     "description": "Remembers the document's setup: orientation, units, "
                    "stock allowances and floor (mm values, same ranges as "
                    "the cutting actions) and the raw blank size {x, y, z} "
                    "mm or null. job.get returns it.",
     "confirm": False,
     "inputs": {"type": "object", "properties": {
         "document_id": _DOC_ID_INPUT,
         "setup": {"type": "object"}},
         "required": ["document_id", "setup"]},
     "result": "the job (as job.get, with setup) or {code, message}"},
]

_FEEDS = ("feed", "ramp_feed")


def _fmt(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


def _annotate(action):
    """Task f: every value input's description states its unit, range and
    default (lengths follow `units`). Applied once to the catalog."""
    props = action["inputs"]["properties"] = {
        k: dict(v) for k, v in action["inputs"]["properties"].items()}
    for name, p in props.items():
        if "x-steve" in p or p.get("type") == "object":
            continue
        bits = []
        lo, hi = p.get("minimum"), p.get("maximum")
        if name in MM_FIELDS:
            unit = "mm/min" if name in _FEEDS else "mm"
            iunit = "in/min" if name in _FEEDS else "in"
            bits.append("%s, follows `units`" % ("feed" if name in _FEEDS
                                                 else "length"))
            if lo is not None or hi is not None:
                bits.append("range %s..%s %s (%s..%s %s)" % (
                    "" if lo is None else _fmt(lo),
                    "" if hi is None else _fmt(hi), unit,
                    "" if lo is None else _fmt(lo / 25.4),
                    "" if hi is None else _fmt(hi / 25.4), iunit))
        elif "enum" in p:
            bits.append("one of %s" % ", ".join(map(str, p["enum"])))
        elif lo is not None or hi is not None:
            bits.append("range %s..%s" % ("" if lo is None else _fmt(lo),
                                          "" if hi is None else _fmt(hi)))
        if "default" in p:
            d = p["default"]
            bits.append("default %s%s" % (
                d, (" mm (%s in)" % _fmt(d / 25.4))
                if name in MM_FIELDS and name not in _FEEDS else
                (" mm/min (%s in/min)" % _fmt(d / 25.4))
                if name in _FEEDS else ""))
        else:
            bits.append("optional")
        base = p.get("description") or p.get("title") or \
            name.replace("_", " ")
        p["description"] = "%s (%s)" % (base, "; ".join(bits))


CATALOG = {"actions": [ROUGHING_ACTION, SLOPE_ACTION_SPEC,
                       CHECK_ACTION_SPEC, MEASURE_ACTION_SPEC]
           + TOOL_ACTION_SPECS,
           "events": [{
               "name": EVENT,
               "description": "Engine state: idle or busy, the current "
                            "action and its progress.",
           }]}


for _a in CATALOG["actions"]:
    _annotate(_a)


def get_action(name):
    """The catalog action dict for `name`, or None."""
    for a in CATALOG["actions"]:
        if a["name"] == name:
            return a
    return None


def validate_inputs(values, action=ACTION):
    """Return (ok, error_code, message-or-values). Applies defaults; checks
    required, enum and numeric ranges against the action's catalog spec.
    (validate() gives the same check with the full agent error.)"""
    ok, out = validate(values, action)
    if not ok:
        return False, out["code"], out["message"]
    return True, "", out


def _caller_units(values, name, v, raw):
    """(got, scale): the value as the caller sent it and the mm->caller
    factor, for range messages in the caller's units (task f)."""
    if raw is not None and values.get("units") == "inch" and \
            name in MM_FIELDS:
        return raw.get(name, v), 1.0 / 25.4
    return v, 1.0


def _bound(x, scale):
    return round(x * scale, 4) if scale != 1.0 else x


def validate(values, action=ACTION, raw=None):
    """(True, values with defaults) or (False, agent error {code, message,
    field?, got?, allowed?, next_step}). `raw` = the inputs as the caller
    sent them (before to_mm), so ranges are reported in the caller's
    units."""
    spec = get_action(action)
    if spec is None:
        return False, errors.make_error(
            "action_unknown", "unknown action %s" % action, field="action",
            got=action, allowed=[a["name"] for a in CATALOG["actions"]])
    props = spec["inputs"]["properties"]
    required = spec["inputs"].get("required", [])
    units = values.get("units")
    out = {}
    for name, s in props.items():
        out[name] = values.get(name, s.get("default"))
    for name in required:
        if out.get(name) is None:
            return False, errors.make_error(
                "input_missing", "missing required input %s" % name,
                field=name)
    if action == CHECK_ACTION and values.get("origin") is None:
        # TL2 item 1: check_program has no origin default.
        err = errors.make_error("input_missing", "missing required input "
                                "origin", field="origin")
        err["next_step"] = ("pass the origin the program was posted with; "
                            "runs from this connector record it in their "
                            "check.json setup")
        return False, err
    for name in values:
        if name not in props:
            close = difflib.get_close_matches(name, list(props), n=3)
            return False, errors.make_error(
                "input_unknown", "unknown input %s%s" % (
                    name, " (did you mean %s?)" % close[0] if close else ""),
                field=name, got=values[name], allowed=close or sorted(props))
    for name, s in props.items():
        v = out.get(name)
        if v is None:
            continue
        if "enum" in s and v not in s["enum"]:
            return False, errors.make_error(
                "input_out_of_range", "%s=%r not in enum %s" % (
                    name, v, s["enum"]), field=name, got=v,
                allowed={"enum": s["enum"]})
        lo, hi = s.get("minimum"), s.get("maximum")
        if isinstance(v, (int, float)) and (
                (isinstance(lo, (int, float)) and v < lo) or
                (isinstance(hi, (int, float)) and v > hi)):
            got, k = _caller_units(values, name, v, raw)
            allowed = {"minimum": None if lo is None else _bound(lo, k),
                       "maximum": None if hi is None else _bound(hi, k),
                       "units": ("inch" if k != 1.0 else
                                 "mm" if name in MM_FIELDS else None)}
            word, lim = (("below minimum", allowed["minimum"])
                         if lo is not None and v < lo
                         else ("above maximum", allowed["maximum"]))
            return False, errors.make_error(
                "input_out_of_range", "%s=%s %s %s%s" % (
                    name, got, word, lim,
                    " " + allowed["units"] if allowed["units"] else ""),
                field=name, got=got, allowed=allowed)
    # tool shape sanity (per action's own tool inputs; ball was dropped from
    # the roughing enum in RR1a: the engine's rough cannot cut with a ball)
    for pre in ("", "rough_"):
        if pre + "tool_type" not in props:
            continue
        kind, dia, cr = out[pre + "tool_type"], out[pre + "tool_diameter"], \
            out[pre + "corner_radius"]
        if kind == "bull" and not (0.0 < cr < dia / 2.0):
            got, k = _caller_units(values, pre + "corner_radius", cr, raw)
            return False, errors.make_error(
                "input_out_of_range",
                "%sbull corner radius must satisfy 0 < cr < dia/2"
                % ("rough " if pre else ""), field=pre + "corner_radius",
                got=got, allowed={"exclusive_minimum": 0.0,
                                  "exclusive_maximum": _bound(dia / 2.0, k),
                                  "units": "inch" if k != 1.0 else "mm"})
        if kind == "flat":
            out[pre + "corner_radius"] = 0.0
    return True, out


def to_mm(values: dict, action=None) -> dict:
    """Convert mm-valued inputs from inch to mm when units == 'inch'. With
    `action`, an omitted units input first takes the action's catalog
    default (inch), so omitted units mean inch everywhere: values, post and
    G20 agree (task (a): defaults used to be applied only after this
    conversion, so omitted units were read as mm but posted G20)."""
    out = dict(values)
    spec = get_action(action) if action else None
    units = (spec or {}).get("inputs", {}).get("properties", {}).get("units")
    if units and out.get("units") is None and "default" in units:
        out["units"] = units["default"]
    if out.get("units") == "inch":
        for k in MM_FIELDS:
            if isinstance(out.get(k), (int, float)):
                out[k] = out[k] * 25.4
    return out
