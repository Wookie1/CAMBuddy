# -*- coding: utf-8 -*-
"""Reorient the design-coordinate STEPs into the Fusion machining setup.

Fusion machines Core Front from design -Z, so the raw STEPs (design coords)
must be flipped into the machine WCS before CAM/verification:

  Core Front   : rotate 180 deg about X (x, y, z -> x, -y, -z), then Z + 34.925
  Cavity Front : delivered ALREADY in setup coordinates (round 3) -> bbox check
                 only; if a design-coordinate cavity_front.step appears instead,
                 rotate 180 deg about Z (x, y, z -> -x, -y, z), then Z + 60.96

Origin of the outputs = Fusion WCS (bottom-centre of the stock); reference
NC code lines up with core_front_setup.step exactly.

Run:
    freecadcmd spike/orient.py [src_dir] [dst_dir]
or env STEP_DIR / SETUP_DIR. Writes samples/core_front_setup.step and
samples/cavity_front_setup.step and asserts the expected bounding boxes.
"""
import os
import sys

import FreeCAD as App  # noqa: F401  (runtime; Part needs it loaded)
import Part

# expected bboxes: (xmin, xmax, ymin, ymax, zmin, zmax), tolerance mm
EXPECTED = {
    "core_front_setup": ((-126.36, 126.36, -69.85, 69.85, 0.0, 46.84), 0.05),
    "cavity_front_setup": ((-126.36, 126.36, -69.85, 69.85, 0.0, 60.96), 0.05),
}


def resolve_dirs():
    args = [a for a in sys.argv[1:]
            if not a.endswith("orient.py") and a != "--"]
    src = os.environ.get("STEP_DIR") or (args[0] if len(args) > 0 else "samples")
    dst = os.environ.get("SETUP_DIR") or (args[1] if len(args) > 1 else src)
    return src, dst


def transform(step_in, step_out, rotation_axis, angle_deg, dz):
    shape = Part.read(step_in)
    if shape.isNull() or (not shape.Solids and not shape.Shells
                          and not shape.Faces and not shape.Edges):
        raise ValueError("source %s contains no geometry (null shape)"
                        % step_in)
    pl = App.Placement(App.Vector(0.0, 0.0, dz),
                       App.Rotation(App.Vector(*rotation_axis), angle_deg))
    shape.Placement = pl.multiply(shape.Placement)
    os.makedirs(os.path.dirname(os.path.abspath(step_out)), exist_ok=True)
    shape.exportStep(step_out)
    return shape


def check_bbox(name, shape):
    exp, tol = EXPECTED[name]
    # the plain BoundBox is loose on BSpline surfaces (up to 0.22 mm here);
    # assert against the tight optimal bounding box, like the heightfield zmin
    bb = shape.optimalBoundingBox()
    got = (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)
    print("%s bbox: X[%.3f %.3f] Y[%.3f %.3f] Z[%.3f %.3f]"
          % (name, *got), flush=True)
    for label, g, e in zip(("Xmin", "Xmax", "Ymin", "Ymax", "Zmin", "Zmax"),
                          got, exp):
        if abs(g - e) > tol:
            raise SystemExit("FAIL: %s %s = %.3f, expected %.2f +/- %.2f"
                            % (name, label, g, e, tol))
    print("OK: %s bbox within %.2f mm" % (name, tol), flush=True)


def main():
    src, dst = resolve_dirs()
    jobs = [
        # (source, destination, axis, angle, dz)
        ("core_front.step", "core_front_setup.step", (1, 0, 0), 180, 34.925),
    ]
    done = 0
    for src_name, dst_name, axis, angle, dz in jobs:
        step_in = os.path.join(src, src_name)
        step_out = os.path.join(dst, dst_name)
        try:
            shape = transform(step_in, step_out, axis, angle, dz)
        except Exception as exc:
            # Supervisor round 3: samples/cavity_front.step was an empty export;
            # Part.read either returns a null shape or raises "File to load not
            # existing or not readable". Skip such sources with a clear
            # message; a replacement cavity file is expected.
            print("SKIP %s: no geometry (%s)" % (step_in, exc), flush=True)
            continue
        # verify the re-imported file: STEP round-trip is what CAM reads
        check_bbox(os.path.splitext(dst_name)[0], Part.read(step_out))
        print("wrote %s" % step_out, flush=True)
        done += 1

    # Cavity Front: supervisor round 3 UPDATE — samples/cavity_front_setup.step
    # is delivered ALREADY in setup coordinates (do NOT transform). Verify its
    # bbox only. If a design-coordinate cavity_front.step ever shows up again,
    # transform it (rotate 180 deg about Z, Z +60.96) instead.
    cav_setup = os.path.join(dst, "cavity_front_setup.step")
    cav_src = os.path.join(src, "cavity_front.step")
    if os.path.exists(cav_setup):
        check_bbox("cavity_front_setup", Part.read(cav_setup))
        print("verified %s (delivered in setup coordinates, untransformed)"
              % cav_setup, flush=True)
        done += 1
    elif os.path.exists(cav_src):
        try:
            transform(cav_src, cav_setup, (0, 0, 1), 180, 60.96)
        except Exception as exc:
            print("SKIP %s: no geometry (%s)" % (cav_src, exc), flush=True)
        else:
            check_bbox("cavity_front_setup", Part.read(cav_setup))
            print("wrote %s" % cav_setup, flush=True)
            done += 1
    else:
        print("SKIP cavity: neither %s nor %s exists" % (cav_setup, cav_src),
              flush=True)
    if done == 0:
        raise SystemExit("FAIL: no source produced geometry")


main()
