"""Catalog v1: action adaptive_rough + event engine_state, and input
validation (required / enum / numeric range). All mm-valued inputs are
validated in mm; a run with units=="inch" has its mm values converted by
the runner after validation.
"""

ACTION = "adaptive_rough"
EVENT = "engine_state"

# inputs whose numeric value is a length/feeds in mm (or mm/min):
MM_FIELDS = ("stock_xy", "stock_top", "stock_bottom", "floor_z",
             "tool_diameter", "corner_radius", "flute_length", "stepdown",
             "optimal_load", "stock_to_leave", "rest_stepup", "feed",
             "ramp_feed")

CATALOG = {
    "actions": [{
        "name": ACTION,
        "title": "Adaptive roughing",
        "description": ("Orient a STEP model, derive the stock box and run "
                        "adaptive roughing; returns a time/collision summary "
                        "with the posted LNC program, a zmap check and a "
                        "leftover preview. Never touches the machine."),
        "confirm": False,
        "inputs": {
            "type": "object",
            "properties": {
                "model": {"x-steve": "file", "format": "step",
                         "title": "STEP model"},
                "orientation": {"type": "string",
                              "enum": ["as_modeled", "flip_x_180",
                                      "flip_y_180", "flip_z_180"],
                              "default": "as_modeled",
                              "title": "Orientation"},
                "stock_xy": {"type": "number", "minimum": 0.0, "maximum": 25.4,
                            "default": 1.0,
                            "description": "XY stock offset per side, mm"},
                "stock_top": {"type": "number", "minimum": 0.0,
                            "maximum": 25.4, "default": 1.0,
                            "description": "stock above part top, mm"},
                "stock_bottom": {"type": "number", "minimum": 0.0,
                               "maximum": 25.4, "default": 1.0,
                               "description": "stock below part bottom, mm"},
                "floor_z": {"type": "number", "minimum": 0.0,
                           "maximum": 200.0, "default": 0.0,
                           "description": "main floor above stock bottom, mm"},
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
                                "description": "adaptive optimal load mm"},
                "stock_to_leave": {"type": "number", "minimum": 0.0,
                                 "maximum": 5.0, "default": 0.381},
                "rest_stepup": {"type": "number", "minimum": 0.1,
                              "maximum": 10.0, "default": 1.905},
                "rpm": {"type": "integer", "minimum": 100, "maximum": 30000,
                       "default": 7500},
                "feed": {"type": "number", "minimum": 10.0,
                        "maximum": 20000.0, "default": 3429.0,
                        "description": "cut feed mm/min"},
                "ramp_feed": {"type": "number", "minimum": 10.0,
                             "maximum": 20000.0, "default": 1270.0},
                "tool_number": {"type": "integer", "minimum": 1,
                              "maximum": 999,
                              "description": "machine tool number; else the "
                                           "X7 tool table is consulted"},
                "units": {"type": "string", "enum": ["inch", "mm"],
                         "default": "inch"},
                "program_number": {"type": "integer", "minimum": 1,
                                 "maximum": 9999, "default": 1001},
            },
            "required": ["model"],
        },
        "result": ("Estimated time, cut length, zmap gouges, rapid "
                   "collisions, over-flute and leftover mean/p95/"
                   "within_0p5mm; files: .nc, check.json, preview.png."),
    }],
    "events": [{
        "name": EVENT,
        "description": "Engine state: idle|busy, current action, progress.",
    }],
}


def validate_inputs(values: dict):
    """Return (ok, error_code, message). Applies defaults; checks required,
    enum and numeric ranges against the catalog."""
    props = CATALOG["actions"][0]["inputs"]["properties"]
    out = {}
    for name, spec in props.items():
        v = values.get(name, spec.get("default"))
        if name not in values and "default" not in spec:
            if name in CATALOG["actions"][0]["inputs"].get("required", []):
                return False, "input_missing", "missing required input %s" % name
        out[name] = v
    for name in CATALOG["actions"][0]["inputs"].get("required", []):
        if out.get(name) is None:
            return False, "input_missing", "missing required input %s" % name
    for name, v in values.items():
        if name not in props:
            return False, "input_unknown", "unknown input %s" % name
    for name, spec in props.items():
        v = out.get(name)
        if v is None:
            continue
        if "enum" in spec and v not in spec["enum"]:
            return False, "input_out_of_range", "%s=%r not in enum" % (name, v)
        if isinstance(spec.get("minimum"), (int, float)) and \
                isinstance(v, (int, float)) and v < spec["minimum"]:
            return False, "input_out_of_range", \
                "%s=%s below minimum %s" % (name, v, spec["minimum"])
        if isinstance(spec.get("maximum"), (int, float)) and \
                isinstance(v, (int, float)) and v > spec["maximum"]:
            return False, "input_out_of_range", \
                "%s=%s above maximum %s" % (name, v, spec["maximum"])
    # tool shape sanity
    kind, dia, cr = out["tool_type"], out["tool_diameter"], out["corner_radius"]
    if kind == "ball" and abs(cr - dia / 2.0) > 1e-6:
        out["corner_radius"] = dia / 2.0
    if kind == "bull" and not (0.0 < cr < dia / 2.0):
        return False, "input_out_of_range", \
            "bull corner radius must satisfy 0 < cr < dia/2"
    if kind == "flat":
        out["corner_radius"] = 0.0
    return True, "", out


def to_mm(values: dict) -> dict:
    """Convert mm-valued inputs from inch to mm when units == 'inch'."""
    out = dict(values)
    if out.get("units") == "inch":
        for k in MM_FIELDS:
            if isinstance(out.get(k), (int, float)):
                out[k] = out[k] * 25.4
    return out
