# /// script
# /// requires-python = ">=3.10"
# ///
"""Rasterize a STEP part top-down into a max-Z heightfield (.npy + .json).

Run under FreeCAD's console, e.g.:
  /Applications/VibeCAD.app/Contents/Resources/bin/freecadcmd \
      verify/heightfield.py samples/core_front.step out/core_front_hf.npy 0.5
Args may also come from env vars STEP_IN, HF_OUT, CELL, PAD.
PAD (mm, default 0) grows the grid outward from the part bbox so the field
covers a larger machine stock; cells with no geometry keep the fill value
(shape ZMin) exactly like unpadded empty columns.
"""
import json
import math
import os
import sys

import numpy as np

import FreeCAD  # noqa: F401  (provides the runtime; Part needs it loaded)
import Part


def get_args():
    argv = [a for a in sys.argv[1:] if not a.endswith("heightfield.py")]
    argv = [a for a in argv if a != "--"]
    step = os.environ.get("STEP_IN") or (argv[0] if len(argv) > 0 else None)
    out = os.environ.get("HF_OUT") or (argv[1] if len(argv) > 1 else None)
    cell = float(os.environ.get("CELL") or (argv[2] if len(argv) > 2 else 0.5))
    pad = float(os.environ.get("PAD") or (argv[3] if len(argv) > 3 else 0.0))
    if not step or not out:
        raise SystemExit("usage: freecadcmd heightfield.py STEP_IN HF_OUT [CELL]"
                        " [PAD] (or env STEP_IN/HF_OUT/CELL/PAD)")
    return step, out, cell, pad


def rasterize(shape, cell=0.5, tol=0.01, pad=0.0):
    """Tessellate `shape` and rasterize triangles into a max-Z grid.

    Returns (hf, meta). Empty cells get the shape's bottom Z.
    """
    verts, tris = shape.tessellate(tol)
    bb = shape.BoundBox
    x0, y0 = float(bb.XMin) - pad, float(bb.YMin) - pad
    nx = max(1, int(math.ceil((float(bb.XMax) + pad - x0) / cell)))
    ny = max(1, int(math.ceil((float(bb.YMax) + pad - y0) / cell)))
    zmin = float(bb.ZMin)
    hf = np.full((ny, nx), zmin, dtype=np.float64)

    for tri in tris:
        ax, ay, az = (float(verts[tri[0]].x), float(verts[tri[0]].y),
                      float(verts[tri[0]].z))
        bx, by, bz = (float(verts[tri[1]].x), float(verts[tri[1]].y),
                      float(verts[tri[1]].z))
        cx, cy, cz = (float(verts[tri[2]].x), float(verts[tri[2]].y),
                      float(verts[tri[2]].z))
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:
            continue  # degenerate in XY
        ilo = max(0, int(math.floor((min(ax, bx, cx) - x0) / cell)))
        ihi = min(nx - 1, int(math.floor((max(ax, bx, cx) - x0) / cell)))
        jlo = max(0, int(math.floor((min(ay, by, cy) - y0) / cell)))
        jhi = min(ny - 1, int(math.floor((max(ay, by, cy) - y0) / cell)))
        if ilo > ihi or jlo > jhi:
            continue
        gx = x0 + (np.arange(ilo, ihi + 1) + 0.5) * cell
        gy = y0 + (np.arange(jlo, jhi + 1) + 0.5) * cell
        px, py = np.meshgrid(gx, gy)
        l0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det
        l1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det
        l2 = 1.0 - l0 - l1
        inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
        if not inside.any():
            continue
        z = l0 * az + l1 * bz + l2 * cz
        win = hf[jlo:jhi + 1, ilo:ihi + 1]
        np.maximum(win, np.where(inside, z, -np.inf), out=win)

    meta = {"x0": x0, "y0": y0, "cell": cell, "nx": nx, "ny": ny,
            "zmin": zmin, "zmax": float(bb.ZMax), "tess_tol": tol}
    return hf, meta


def main():
    step, out, cell, pad = get_args()
    shape = Part.read(step)
    tol = float(os.environ.get("TESS_TOL", 0.01))  # 0.01 = the engine STL tolerance
    hf, meta = rasterize(shape, cell=cell, tol=tol, pad=pad)
    outdir = os.path.dirname(os.path.abspath(out))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    np.save(out, hf)
    sidecar = os.path.join(outdir, os.path.splitext(os.path.basename(out))[0] + ".json")
    with open(sidecar, "w") as f:
        json.dump(meta, f, indent=2)
    print("wrote %s shape=%s min=%.3f max=%.3f" %
          (out, hf.shape, hf.min(), hf.max()))
    print("wrote %s" % sidecar)


main()
