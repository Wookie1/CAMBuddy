"""Catalog v1: actions adaptive_rough + slope_split_finish, event
engine_state, and input validation (required / enum / numeric range). All
mm-valued inputs are validated in mm; a run with units=="inch" has its mm
values converted by the runner after validation.
"""

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
             "rough_stock_to_leave", "rough_rest_stepup", "min_rest")

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
              "default": "inch"},
    "program_number": {"type": "integer", "minimum": 1,
                       "maximum": 9999, "default": 1001},
}

ROUGHING_ACTION = {
    "name": ACTION,
    "title": "Adaptive roughing",
    "description": ("Takes a STEP model, stands it the way you choose, "
                    "builds the stock box around it and roughs with a flat "
                    "or bull end mill at steady side load, level by level, "
                    "leaving stock for finishing. Gives back the posted LNC "
                    "program with a time and collision summary, an "
                    "independent zmap check and a leftover preview. Nothing "
                    "is sent to the machine."),
    "confirm": False,
    "inputs": {
        "type": "object",
        "properties": {
            "model": {"x-steve": "file", "format": "step",
                      "title": "STEP model"},
            "orientation": _ORIENTATION,
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

SLOPE_ACTION_SPEC = {
    "name": SLOPE_ACTION,
    "title": "Slope-split finishing",
    "description": ("Roughs first, then finishes with a ball nose split by "
                    "surface slope: contour-style passes on steep walls, "
                    "raster-style on flatter areas, overlapping where they "
                    "meet (run after roughing: a finishing ball must never "
                    "meet raw stock). Gives back BOTH posted LNC programs "
                    "(rough.nc and finish.nc) with a combined time and "
                    "cut-length summary, the exact clcheck of the finish "
                    "program and a chained zmap check (roughing from full "
                    "stock, then the finish with the roughed stock as "
                    "stock-in). Optionally finishes again with a smaller "
                    "ball over the corners the finish ball could not reach "
                    "(rest_tool_number + min_rest): a third posted program "
                    "(rest.nc) with its own clcheck and zmap, chained after "
                    "the finish. Nothing is sent to the machine."),
    "confirm": False,
    "inputs": {
        "type": "object",
        "properties": {
            "model": {"x-steve": "file", "format": "step",
                      "title": "STEP model"},
            "orientation": _ORIENTATION,
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
    "description": ("Judges a posted G-code program against your part and "
                    "stock box with the independent zmap: gouges, rapid "
                    "collisions, over-flute/shank rub, holder clearance and "
                    "the tool footprint, using the program's T word looked up "
                    "in tools/x7_tools.json (one tool per program). The "
                    "program must stay in the supported subset - XY-plane "
                    "moves and arcs (I/J or R), no cutter comp, no canned "
                    "cycles, no other planes - anything else fails with the "
                    "offending code and line. Gives back check.json and "
                    "preview.png. Up to three programs can be checked in "
                    "order (e.g. rough, finish, rest): each program is "
                    "judged on the stock left by the previous one, and the "
                    "first failing program fails the run. Nothing is sent "
                    "to the machine."),
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

CATALOG = {"actions": [ROUGHING_ACTION, SLOPE_ACTION_SPEC,
                       CHECK_ACTION_SPEC, MEASURE_ACTION_SPEC]
           + TOOL_ACTION_SPECS,
           "events": [{
               "name": EVENT,
               "description": "Engine state: idle or busy, the current "
                            "action and its progress.",
           }]}


def get_action(name):
    """The catalog action dict for `name`, or None."""
    for a in CATALOG["actions"]:
        if a["name"] == name:
            return a
    return None


def validate_inputs(values, action=ACTION):
    """Return (ok, error_code, message-or-values). Applies defaults; checks
    required, enum and numeric ranges against the action's catalog spec."""
    spec = get_action(action)
    if spec is None:
        return False, "action_unknown", "unknown action %s" % action
    props = spec["inputs"]["properties"]
    required = spec["inputs"].get("required", [])
    out = {}
    for name, s in props.items():
        v = values.get(name, s.get("default"))
        if name not in values and "default" not in s:
            if name in required:
                return False, "input_missing", "missing required input %s" % name
        out[name] = v
    for name in required:
        if out.get(name) is None:
            return False, "input_missing", "missing required input %s" % name
    for name in values:
        if name not in props:
            return False, "input_unknown", "unknown input %s" % name
    for name, s in props.items():
        v = out.get(name)
        if v is None:
            continue
        if "enum" in s and v not in s["enum"]:
            return False, "input_out_of_range", "%s=%r not in enum %s" % (
                name, v, s["enum"])
        if isinstance(s.get("minimum"), (int, float)) and \
                isinstance(v, (int, float)) and v < s["minimum"]:
            return False, "input_out_of_range", \
                "%s=%s below minimum %s" % (name, v, s["minimum"])
        if isinstance(s.get("maximum"), (int, float)) and \
                isinstance(v, (int, float)) and v > s["maximum"]:
            return False, "input_out_of_range", \
                "%s=%s above maximum %s" % (name, v, s["maximum"])
    # tool shape sanity (per action's own tool inputs; ball was dropped from
    # the roughing enum in RR1a: the engine's rough cannot cut with a ball)
    if "tool_type" in props:  # adaptive_rough
        kind, dia, cr = out["tool_type"], out["tool_diameter"], \
            out["corner_radius"]
        if kind == "bull" and not (0.0 < cr < dia / 2.0):
            return False, "input_out_of_range", \
                "bull corner radius must satisfy 0 < cr < dia/2"
        if kind == "flat":
            out["corner_radius"] = 0.0
    if "rough_tool_type" in props:  # slope_split_finish roughing tool
        kind, dia, cr = out["rough_tool_type"], \
            out["rough_tool_diameter"], out["rough_corner_radius"]
        if kind == "bull" and not (0.0 < cr < dia / 2.0):
            return False, "input_out_of_range", \
                "rough bull corner radius must satisfy 0 < cr < dia/2"
        if kind == "flat":
            out["rough_corner_radius"] = 0.0
    return True, "", out


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
