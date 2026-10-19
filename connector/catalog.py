"""Catalog v1: actions adaptive_rough + slope_split_finish, event
engine_state, and input validation (required / enum / numeric range). All
mm-valued inputs are validated in mm; a run with units=="inch" has its mm
values converted by the runner after validation.
"""

ACTION = "adaptive_rough"
SLOPE_ACTION = "slope_split_finish"
ACTIONS = (ACTION, SLOPE_ACTION)
EVENT = "engine_state"

# inputs whose numeric value is a length/feeds in mm (or mm/min):
MM_FIELDS = ("stock_xy", "stock_top", "stock_bottom", "floor_z",
             "tool_diameter", "corner_radius", "flute_length", "stepdown",
             "optimal_load", "stock_to_leave", "rest_stepup", "feed",
             "ramp_feed",
             # slope_split_finish:
             "stepover", "rough_tool_diameter", "rough_corner_radius",
             "rough_flute_length", "rough_stepdown", "rough_optimal_load",
             "rough_stock_to_leave", "rough_rest_stepup")

_ORIENTATION = {"type": "string",
                "enum": ["as_modeled", "flip_x_180", "flip_y_180",
                         "flip_z_180"],
                "default": "as_modeled",
                "title": "Orientation"}

_STOCK_INPUTS = {
    "stock_xy": {"type": "number", "minimum": 0.0, "maximum": 25.4,
                 "default": 1.0,
                 "description": "extra material left around the part, per "
                                "side, mm"},
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
    "tool_type": {"type": "string", "enum": ["flat", "bull", "ball"],
                  "default": "bull", "title": "Tool type"},
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
                    "stock-in). Nothing is sent to the machine."),
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
            # roughing tool + cutting data (defaults as in adaptive_rough)
            **{"rough_" + k: v for k, v in _ROUGHING_INPUTS.items()},
        },
        "required": ["model"],
    },
    "result": ("Combined summary: estimated time and cut length for the "
               "chain, probe_clcheck count (0 required), chained zmap "
               "gouges / rapid collisions / leftover; files: rough.nc, "
               "finish.nc, check.json, preview.png."),
}

CATALOG = {"actions": [ROUGHING_ACTION, SLOPE_ACTION_SPEC],
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
            return False, "input_out_of_range", "%s=%r not in enum" % (name, v)
        if isinstance(s.get("minimum"), (int, float)) and \
                isinstance(v, (int, float)) and v < s["minimum"]:
            return False, "input_out_of_range", \
                "%s=%s below minimum %s" % (name, v, s["minimum"])
        if isinstance(s.get("maximum"), (int, float)) and \
                isinstance(v, (int, float)) and v > s["maximum"]:
            return False, "input_out_of_range", \
                "%s=%s above maximum %s" % (name, v, s["maximum"])
    # tool shape sanity (per action's own tool inputs)
    if "tool_type" in props:  # adaptive_rough
        kind, dia, cr = out["tool_type"], out["tool_diameter"], \
            out["corner_radius"]
        if kind == "ball" and abs(cr - dia / 2.0) > 1e-6:
            out["corner_radius"] = dia / 2.0
        if kind == "bull" and not (0.0 < cr < dia / 2.0):
            return False, "input_out_of_range", \
                "bull corner radius must satisfy 0 < cr < dia/2"
        if kind == "flat":
            out["corner_radius"] = 0.0
    if "rough_tool_type" in props:  # slope_split_finish roughing tool
        kind, dia, cr = out["rough_tool_type"], \
            out["rough_tool_diameter"], out["rough_corner_radius"]
        if kind == "ball" and abs(cr - dia / 2.0) > 1e-6:
            out["rough_corner_radius"] = dia / 2.0
        if kind == "bull" and not (0.0 < cr < dia / 2.0):
            return False, "input_out_of_range", \
                "rough bull corner radius must satisfy 0 < cr < dia/2"
        if kind == "flat":
            out["rough_corner_radius"] = 0.0
    return True, "", out


def to_mm(values: dict) -> dict:
    """Convert mm-valued inputs from inch to mm when units == 'inch'."""
    out = dict(values)
    if out.get("units") == "inch":
        for k in MM_FIELDS:
            if isinstance(out.get(k), (int, float)):
                out[k] = out[k] * 25.4
    return out
