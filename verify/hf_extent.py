"""Pure grid-extent math for verify/heightfield.py (no FreeCAD imports).

The zmap part grid must always cover the machine stock plus the largest
tool footprint the grid will judge: when STOCK_BOX is given the grid covers
the union of the part bbox and the stock box expanded by TOOL_R + MARGIN on
every side. PAD (part bbox grown per side) keeps working for old callers.
"""
import math


def grid_extent(bbox, stock_box=None, tool_r=0.0, margin=5.0, pad=0.0,
                cell=0.5):
    """Cell-aligned grid bounds covering the part bbox and (when given)
    the stock box grown by tool_r + margin on every side.

    bbox:      (xmin, xmax, ymin, ymax) of the part
    stock_box: (xmin, xmax, ymin, ymax) of the stock, or None
    Returns a dict with x0/y0/nx/ny, the resulting grid_bounds and the
    per-side pad_mm (distance from the part bbox to the grid edge).
    Outer cells hold no geometry and keep the zmin floor, exactly like
    today's PAD cells.
    """
    pxmin, pxmax, pymin, pymax = (float(v) for v in bbox)
    xmin = pxmin - pad
    xmax = pxmax + pad
    ymin = pymin - pad
    ymax = pymax + pad
    if stock_box is not None:
        sxmin, sxmax, symin, symax = (float(v) for v in stock_box)
        grow = float(tool_r) + float(margin)
        xmin = min(xmin, sxmin - grow)
        xmax = max(xmax, sxmax + grow)
        ymin = min(ymin, symin - grow)
        ymax = max(ymax, symax + grow)
    nx = max(1, int(math.ceil((xmax - xmin) / cell - 1e-9)))
    ny = max(1, int(math.ceil((ymax - ymin) / cell - 1e-9)))
    return {
        "x0": xmin,
        "y0": ymin,
        "nx": nx,
        "ny": ny,
        "grid_bounds": [xmin, xmin + nx * cell, ymin, ymin + ny * cell],
        "pad_mm": {"xmin": pxmin - xmin,
                   "xmax": (xmin + nx * cell) - pxmax,
                   "ymin": pymin - ymin,
                   "ymax": (ymin + ny * cell) - pymax},
    }


def parse_stock_box(text):
    """Parse 'xmin xmax ymin ymax' (env STOCK_BOX / --stock-box) into 4
    floats, or None when text is empty/absent."""
    if not text:
        return None
    vals = [float(t) for t in str(text).split()]
    if len(vals) != 4:
        raise SystemExit("STOCK_BOX needs exactly 4 numbers "
                         "'xmin xmax ymin ymax', got %r" % (text,))
    if vals[0] >= vals[1] or vals[2] >= vals[3]:
        raise SystemExit("STOCK_BOX bounds not increasing: %r" % (text,))
    return vals
