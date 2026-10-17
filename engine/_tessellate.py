#!/usr/bin/env python3
"""Tessellate a STEP to STL at a given deflection. Run under freecadcmd.

Usage: freecadcmd _tessellate.py <step> <stl> [deflection]
(env STEP_IN / STL_OUT / TOL also work).
"""
import os
import sys

import FreeCAD  # noqa: F401
import Part


def get_args():
    argv = [a for a in sys.argv[1:] if not os.path.basename(a) == "_tessellate.py"]
    argv = [a for a in argv if a != "--"]
    step = os.environ.get("STEP_IN") or (argv[0] if len(argv) > 0 else None)
    stl = os.environ.get("STL_OUT") or (argv[1] if len(argv) > 1 else None)
    tol = float(os.environ.get("TOL") or (argv[2] if len(argv) > 2 else 0.01))
    if not step or not stl:
        raise SystemExit("usage: freecadcmd _tessellate.py STEP STL [TOL]")
    return step, stl, tol


def main():
    step, stl, tol = get_args()
    shape = Part.Shape()
    shape.read(step)
    if shape.isNull():
        raise SystemExit("null shape: %s" % step)
    bb = shape.BoundBox
    print("bbox X %.3f..%.3f Y %.3f..%.3f Z %.3f..%.3f" %
          (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax), flush=True)
    # tessellate + manual STL write (avoids Mesh export deflection surprises)
    verts, tris = shape.tessellate(tol)
    tmp = stl + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("solid tess\n")
        for t in tris:
            a, b, c = (verts[t[0]], verts[t[1]], verts[t[2]])
            ax, ay, az = float(a.x), float(a.y), float(a.z)
            bx, by, bz = float(b.x), float(b.y), float(b.z)
            cx, cy, cz = float(c.x), float(c.y), float(c.z)
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            nn = (nx * nx + ny * ny + nz * nz) ** 0.5
            if nn > 0:
                nx, ny, nz = nx / nn, ny / nn, nz / nn
            fh.write(" facet normal %g %g %g\n" % (nx, ny, nz))
            fh.write("  outer loop\n")
            fh.write("   vertex %.6f %.6f %.6f\n" % (ax, ay, az))
            fh.write("   vertex %.6f %.6f %.6f\n" % (bx, by, bz))
            fh.write("   vertex %.6f %.6f %.6f\n" % (cx, cy, cz))
            fh.write("  endloop\n endfacet\n")
        fh.write("endsolid tess\n")
    os.replace(tmp, stl)
    print("wrote %s (%d triangles)" % (stl, len(tris)))


main()
sys.stdout.flush()
