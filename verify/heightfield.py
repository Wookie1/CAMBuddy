# /// script
# /// requires-python = ">=3.10"
# ///
"""Rasterize a STEP part top-down into a max-Z heightfield (.npy + .json).

Run under FreeCAD's console, e.g.:
  /Applications/VibeCAD.app/Contents/Resources/bin/freecadcmd \
      verify/heightfield.py samples/core_front.step out/core_front_hf.npy 0.5
Args may also come from env vars STEP_IN, HF_OUT, CELL, PAD, STOCK_BOX,
TOOL_R, MARGIN (or flags --stock-box, --tool-r, --margin).
PAD (mm, default 0) grows the grid outward from the part bbox so the field
covers a larger machine stock; cells with no geometry keep the fill value
(shape ZMin) exactly like unpadded empty columns.
When STOCK_BOX="xmin xmax ymin ymax" is given, the grid covers the union
of the part bbox and the stock box expanded by TOOL_R + MARGIN (default
5.0 mm) on every side, cell-aligned: the grid always judges the whole
stock plus the largest tool footprint, never a tight part bbox. Outer
cells are part-free (zmin floor), exactly like PAD cells; PAD keeps
working for old callers. The sidecar records stock_box, tool_r, margin,
the resulting pad_mm per side and the grid bounds.
"""
import hashlib
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hf_extent import grid_extent, parse_stock_box

import FreeCAD  # noqa: F401  (provides the runtime; Part needs it loaded)
import Part


def _is_float(tok):
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _pop_opt(argv, name):
    """Remove --name and its value(s) from argv; return the literal value,
    or None when the flag is absent."""
    if name not in argv:
        return None
    i = argv.index(name)
    val = argv[i + 1] if i + 1 < len(argv) else ""
    del argv[i:i + 2]
    return val


def get_args():
    argv = [a for a in sys.argv[1:] if not a.endswith("heightfield.py")]
    argv = [a for a in argv if a != "--"]
    sb = None
    if "--stock-box" in argv:
        i = argv.index("--stock-box")
        del argv[i]
        toks = []
        while len(toks) < 4 and i < len(argv) and _is_float(argv[i]):
            toks.append(argv.pop(i))
        sb = " ".join(toks)
    tr = _pop_opt(argv, "--tool-r")
    mg = _pop_opt(argv, "--margin")
    stock_box = parse_stock_box(sb if sb is not None
                                else os.environ.get("STOCK_BOX"))
    tool_r = float(tr if tr is not None else os.environ.get("TOOL_R", 0.0))
    margin = float(mg if mg is not None else os.environ.get("MARGIN", 5.0))
    step = os.environ.get("STEP_IN") or (argv[0] if len(argv) > 0 else None)
    out = os.environ.get("HF_OUT") or (argv[1] if len(argv) > 1 else None)
    cell = float(os.environ.get("CELL") or (argv[2] if len(argv) > 2 else 0.5))
    pad = float(os.environ.get("PAD") or (argv[3] if len(argv) > 3 else 0.0))
    if not step or not out:
        raise SystemExit("usage: freecadcmd heightfield.py STEP_IN HF_OUT [CELL]"
                        " [PAD] (or env STEP_IN/HF_OUT/CELL/PAD/STOCK_BOX/"
                        "TOOL_R/MARGIN; flags --stock-box/--tool-r/--margin)")
    return step, out, cell, pad, stock_box, tool_r, margin


def rasterize(shape, cell=0.5, tol=0.01, pad=0.0, stock_box=None,
              tool_r=0.0, margin=5.0):
    """Tessellate `shape` and rasterize triangles into a max-Z grid.

    Returns (hf, meta). Empty cells get the shape's bottom Z. When
    stock_box is given the grid covers stock + tool_r + margin on every
    side (see hf_extent.grid_extent); pad keeps the old behaviour.
    """
    verts, tris = shape.tessellate(tol)
    bb = shape.BoundBox
    ext = grid_extent((float(bb.XMin), float(bb.XMax),
                       float(bb.YMin), float(bb.YMax)),
                      stock_box=stock_box, tool_r=tool_r, margin=margin,
                      pad=pad, cell=cell)
    x0, y0, nx, ny = ext["x0"], ext["y0"], ext["nx"], ext["ny"]
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
            "zmin": zmin, "zmax": float(bb.ZMax), "tess_tol": tol,
            "stock_box": list(stock_box) if stock_box is not None else None,
            "tool_r": tool_r, "margin": margin,
            "pad_mm": ext["pad_mm"], "grid_bounds": ext["grid_bounds"]}
    return hf, meta


def main():
    step, out, cell, pad, stock_box, tool_r, margin = get_args()
    shape = Part.read(step)
    tol = float(os.environ.get("TESS_TOL", 0.01))  # 0.01 = the engine STL tolerance
    hf, meta = rasterize(shape, cell=cell, tol=tol, pad=pad,
                         stock_box=stock_box, tool_r=tool_r, margin=margin)
    # task HC: the sidecar pins WHICH STEP this field came from, so a
    # reused run dir can never pass off a stale heightfield
    meta["step_sha256"] = hashlib.sha256(open(step, "rb").read()).hexdigest()
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


# freecadcmd executes scripts with __name__ = script basename and the
# script path in sys.argv; pytest imports this module without that.
if any(a.endswith("heightfield.py") for a in sys.argv[:2]):
    main()
