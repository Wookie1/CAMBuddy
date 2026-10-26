#!/usr/bin/env python3
"""Orient a STEP (180 deg flips, or 90/270 deg turns about X or Y, about
the part bbox centre) and export it.

Run under freecadcmd. Env: STEP_IN, STEP_OUT, ORIENT
(as_modeled|flip_x_180|flip_y_180|flip_z_180|rot_x_90|rot_x_270|rot_y_90|
rot_y_270), META_OUT (json with bbox). Angles follow the right-hand rule
(rot_x_90 carries +Y to +Z, rot_y_90 carries +Z to +X). Optional TRANSLATE
"dx dy dz" (mm) moves the oriented shape afterwards (work origin, task e).
"""
import json
import math
import os

import FreeCAD  # noqa: F401
import Part

step = os.environ["STEP_IN"]
out = os.environ["STEP_OUT"]
orient = os.environ.get("ORIENT", "as_modeled")
meta_out = os.environ["META_OUT"]

shape = Part.Shape()
shape.read(step)
if shape.isNull():
    raise SystemExit("null shape: %s" % step)

bb = shape.BoundBox
cx = (float(bb.XMin) + float(bb.XMax)) / 2.0
cy = (float(bb.YMin) + float(bb.YMax)) / 2.0
cz = (float(bb.ZMin) + float(bb.ZMax)) / 2.0

axes = {"flip_x_180": ((cx, cy, cz), (1, 0, 0), 180.0),
        "flip_y_180": ((cx, cy, cz), (0, 1, 0), 180.0),
        "flip_z_180": ((cx, cy, cz), (0, 0, 1), 180.0),
        "rot_x_90": ((cx, cy, cz), (1, 0, 0), 90.0),
        "rot_x_270": ((cx, cy, cz), (1, 0, 0), 270.0),
        "rot_y_90": ((cx, cy, cz), (0, 1, 0), 90.0),
        "rot_y_270": ((cx, cy, cz), (0, 1, 0), 270.0)}
if orient != "as_modeled":
    if orient not in axes:
        raise SystemExit("unknown orientation: %s" % orient)
    centre, axis, angle = axes[orient]
    shape = shape.rotate(FreeCAD.Vector(*centre), FreeCAD.Vector(*axis),
                         angle)

if os.environ.get("TRANSLATE"):
    dx, dy, dz = (float(v) for v in os.environ["TRANSLATE"].split())
    shape.translate(FreeCAD.Vector(dx, dy, dz))

os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
shape.exportStep(out)
bb2 = shape.BoundBox
with open(meta_out, "w") as fh:
    json.dump({"orient": orient,
               "bbox": [float(bb2.XMin), float(bb2.XMax), float(bb2.YMin),
                       float(bb2.YMax), float(bb2.ZMin), float(bb2.ZMax)]},
              fh)
print("oriented %s -> %s" % (orient, out))
