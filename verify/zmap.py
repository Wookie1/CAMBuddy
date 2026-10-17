#!/usr/bin/env python3
"""Independent toolpath checker: simulate a 2.5D toolpath against a part
heightfield and report gouges, leftover stock, rapid collisions and air time.

Plain Python 3 + numpy. No FreeCAD imports.
"""
import argparse
import json
import math
import os
import re
import sys

import numpy as np

WORD_RE = re.compile(r"([A-Za-z])\s*([-+]?[0-9]*\.?[0-9]+)")
GOUGE_TOL = 0.02  # mm below part surface before a cell counts as gouged
REMOVE_EPS = 1e-9  # mm^3 of removal below which a sample counts as air


# --------------------------------------------------------------------------
# G-code parsing
# --------------------------------------------------------------------------

def strip_comments(line):
    """Remove ( ... ) comments and ; to end of line."""
    out = []
    depth = 0
    for ch in line:
        if ch == ";":
            break
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def parse_gcode(text):
    """Parse G-code into a list of moves (absolute, mm where units known).

    Each move is a dict:
      line   : 1-based source line number
      motion : 'G0' | 'G1' | 'G2' | 'G3'
      x, y, z: target coordinates (may be None -> modal / unchanged)
      i, j   : arc center offsets from start (arcs only)
    """
    moves = []
    units = 1.0
    modal = "G1"
    absolute = True
    for lineno, raw in enumerate(text.splitlines(), 1):
        s = strip_comments(raw)
        words = WORD_RE.findall(s)
        if not words:
            continue
        params = {}
        gcodes = []
        for letter, num in words:
            try:
                val = float(num)
            except ValueError:
                continue
            L = letter.upper()
            if L == "G":
                gcodes.append(val)
            elif L in ("X", "Y", "Z", "I", "J"):
                params[L] = val
        for g in gcodes:
            if g == 20:
                units = 25.4
            elif g == 21:
                units = 1.0
            elif g == 90:
                absolute = True
            elif g == 91:
                absolute = False
            elif g in (0.0, 1.0, 2.0, 3.0):
                modal = "G%d" % g
        if not any(k in params for k in ("X", "Y", "Z")) and modal not in ("G2", "G3"):
            continue
        move = {"line": lineno, "motion": modal}
        for k in ("X", "Y", "Z"):
            move[k.lower()] = params[k] * units if k in params else None
        if modal in ("G2", "G3"):
            for k in ("I", "J"):
                move[k.lower()] = params[k] * units if k in params else 0.0
        moves.append(move)
    return moves


# --------------------------------------------------------------------------
# Tool profiles
# --------------------------------------------------------------------------

def tool_dz(tool, dia, corner):
    """Return f(d) -> height of tool surface above the tip at radial dist d."""
    R = dia / 2.0
    if tool == "flat":
        def dz(d):
            return np.zeros_like(np.asarray(d, dtype=float))
    elif tool == "ball":
        def dz(d):
            d = np.asarray(d, dtype=float)
            return R - np.sqrt(np.maximum(R * R - d * d, 0.0))
    elif tool == "bull":
        a = R - corner

        def dz(d):
            d = np.asarray(d, dtype=float)
            t = np.maximum(d - a, 0.0)
            return np.where(d <= a, 0.0, corner - np.sqrt(np.maximum(corner * corner - t * t, 0.0)))
    else:
        raise ValueError("unknown tool type %r" % tool)
    return dz


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def _move_samples(mv, cur, cell):
    """Sample a resolved move (x0,y0,z0)->(x1,y1,z1) at <= cell/4 spacing.

    Returns (samples, length): list of (x, y, z) and total path length.
    """
    x0, y0, z0 = cur
    x1, y1, z1 = mv["x"], mv["y"], mv["z"]
    step = cell / 4.0
    if mv["motion"] in ("G2", "G3") and mv.get("arc"):
        cx, cy, R, a0, sweep = mv["arc"]
        length = abs(sweep) * R
        if R <= 0 or length <= 0:
            return [(x1, y1, z1)], 0.0
        n = max(2, int(math.ceil(length / step)))
        samples = []
        for t in np.linspace(0.0, 1.0, n + 1):
            a = a0 + sweep * t
            samples.append((cx + R * math.cos(a), cy + R * math.sin(a),
                           z0 + (z1 - z0) * t))
        return samples, length
    dx, dy, dzv = x1 - x0, y1 - y0, z1 - z0
    length = math.sqrt(dx * dx + dy * dy + dzv * dzv)
    if length <= 0:
        return [(x1, y1, z1)], 0.0
    n = max(2, int(math.ceil(length / step)))
    ts = np.linspace(0.0, 1.0, n + 1)
    samples = [(x0 + dx * t, y0 + dy * t, z0 + dzv * t) for t in ts]
    return samples, length


def _resolve_arcs(moves, x_init, y_init):
    """Attach arc geometry (cx, cy, R, a0, sweep) to G2/G3 moves."""
    out = []
    cx_, cy_ = x_init, y_init
    for mv in moves:
        m = dict(mv)
        x1 = mv.get("x") if mv.get("x") is not None else cx_
        y1 = mv.get("y") if mv.get("y") is not None else cy_
        if mv["motion"] in ("G2", "G3"):
            acx = cx_ + mv.get("i", 0.0)
            acy = cy_ + mv.get("j", 0.0)
            R = math.hypot(cx_ - acx, cy_ - acy)
            a0 = math.atan2(cy_ - acy, cx_ - acx)
            a1 = math.atan2(y1 - acy, x1 - acx)
            sweep = a1 - a0
            if mv["motion"] == "G2":
                sweep = (sweep + 2 * math.pi) % (2 * math.pi) - 2 * math.pi
            else:
                sweep = (sweep - 2 * math.pi) % (2 * math.pi)
            if abs(sweep) < 1e-12 and (x1 != cx_ or y1 != cy_):
                sweep = 2 * math.pi  # full circle
            m["arc"] = (acx, acy, R, a0, sweep)
        out.append(m)
        cx_, cy_ = x1, y1
    return out


def simulate(moves, part, cell, x0, y0, stock_box, tool="flat", dia=6.0,
             corner=0.0, stock_init=None):
    """Run the toolpath over a stock heightfield.

    part      : (ny, nx) array of part top-Z heights
    cell,x0,y0: grid geometry (cell center of [j, i] is x0+(i+.5)*cell, ...)
    stock_box : (xmin, xmax, ymin, ymax, zmin, zmax)
    stock_init: optional (ny, nx) array; starting stock heights (e.g. the
                'stock' output of a previous op via --stock-out) so multiple
                toolpaths can be chained. Cells outside stock_box are still
                set to -inf. Default: start from the stock box top.
    Returns dict with 'stock' array and report fields.
    """
    sxmin, sxmax, symin, symax, szmin, szmax = stock_box
    ny, nx = part.shape
    if stock_init is not None:
        stock = np.array(stock_init, dtype=float)
        if stock.shape != (ny, nx):
            raise ValueError("stock_init shape %r does not match part grid %r"
                             % (stock.shape, (ny, nx)))
    else:
        stock = np.full((ny, nx), float(szmax))
    ii = np.arange(nx)
    jj = np.arange(ny)
    xs = x0 + (ii + 0.5) * cell
    ys = y0 + (jj + 0.5) * cell
    in_box = ((xs >= sxmin) & (xs <= sxmax))[None, :] & \
             ((ys >= symin) & (ys <= symax))[:, None]
    stock[~in_box] = -np.inf

    R = dia / 2.0
    dz = tool_dz(tool, dia, corner)
    k = int(math.ceil(R / cell)) + 1  # +1 so the padded engagement mask fits

    resolved = _resolve_arcs(moves, 0.0, 0.0)

    cur = [0.0, 0.0, float(szmax)]
    rapid_collisions = 0
    first_rapid_line = None
    cut_length = 0.0
    air_length = 0.0

    for mv in resolved:
        x1 = mv["x"] if mv["x"] is not None else cur[0]
        y1 = mv["y"] if mv["y"] is not None else cur[1]
        z1 = mv["z"] if mv["z"] is not None else cur[2]
        m = dict(mv)
        m["x"], m["y"], m["z"] = x1, y1, z1
        samples, length = _move_samples(m, cur, cell)
        cutting = mv["motion"] in ("G1", "G2", "G3")
        move_collided = False
        seg_len = length / max(1, len(samples))
        for (sx, sy, sz) in samples:
            i0 = int(math.floor((sx - x0) / cell))
            j0 = int(math.floor((sy - y0) / cell))
            ilo, ihi = max(0, i0 - k), min(nx, i0 + k + 1)
            jlo, jhi = max(0, j0 - k), min(ny, j0 + k + 1)
            if ilo >= ihi or jlo >= jhi:
                continue
            gx = xs[ilo:ihi] - sx
            gy = ys[jlo:jhi] - sy
            dxg, dyg = np.meshgrid(gx, gy)
            d = np.hypot(dxg, dyg)
            msk = d <= R + 1e-9
            if not msk.any():
                continue
            newv = np.where(msk, sz + dz(d), np.inf)
            win = stock[jlo:jhi, ilo:ihi]
            cut = win - newv
            removed = float(np.sum(np.clip(np.where(msk, cut, 0.0), 0.0, None)))
            if cutting:
                # engaged = any stock cell at/over the footprint edge above the
                # tip. The radius is padded by half a cell diagonal so that
                # slivers of cells clipped by the disk edge still count (the
                # cell-center mask alone would report false air while cutting).
                msk_e = d <= R + 0.75 * cell
                engaged = float(np.max(np.where(msk_e, win, -np.inf))) > sz + 1e-6
            if removed > REMOVE_EPS:
                stock[jlo:jhi, ilo:ihi] = np.minimum(win, newv)
            if cutting and not engaged:
                air_length += seg_len
            else:  # rapid
                if np.any(np.where(msk, cut > REMOVE_EPS, False)):
                    move_collided = True
        if cutting:
            cut_length += length
        elif move_collided:
            rapid_collisions += 1
            if first_rapid_line is None:
                first_rapid_line = mv["line"]
        cur = [x1, y1, z1]

    result = {
        "stock": stock,
        "rapid_collisions": {"count": rapid_collisions,
                            "first_line": first_rapid_line},
        "air_fraction": (air_length / cut_length) if cut_length > 0 else 0.0,
    }
    result.update(analyze(stock, part, cell, x0, y0))
    return result


# --------------------------------------------------------------------------
# Analysis / report
# --------------------------------------------------------------------------

def analyze(stock, part, cell, x0, y0):
    ny, nx = part.shape
    valid = np.isfinite(stock)
    bottom = float(np.min(part))
    footprint = part > bottom + 1e-9
    mask = valid & footprint
    depth = part - stock
    gouge_mask = mask & (stock < part - GOUGE_TOL)
    if gouge_mask.any():
        flat = np.argmax(np.where(gouge_mask, depth, -np.inf))
        gj, gi = np.unravel_index(flat, part.shape)
        worst = [float(x0 + (gi + 0.5) * cell), float(y0 + (gj + 0.5) * cell)]
        max_depth = float(depth[gouge_mask].max())
    else:
        worst = None
        max_depth = 0.0
    if mask.any():
        leftover = (stock - part)[mask]
        lv = {
            "max": float(leftover.max()),
            "mean": float(leftover.mean()),
            "p95": float(np.percentile(leftover, 95)),
        }
    else:
        lv = {"max": 0.0, "mean": 0.0, "p95": 0.0}
    return {
        "gouges": {"count": int(gouge_mask.sum()), "max_depth": max_depth,
                   "worst_xy": worst},
        "leftover": lv,
    }


def write_png(stock, part, cell, x0, y0, path):
    """Heatmap of leftover stock. Returns True if written, False if skipped."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    with np.errstate(invalid="ignore"):
        data = np.where(np.isfinite(stock), stock - part, np.nan)
    fig, ax = plt.subplots(figsize=(8, 8))
    im = ax.imshow(data, origin="lower", cmap="viridis",
                   extent=[x0, x0 + data.shape[1] * cell,
                         y0, y0 + data.shape[0] * cell])
    fig.colorbar(im, ax=ax, label="leftover stock (mm)")
    ax.set_title("leftover stock")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_part(path):
    part = np.load(path)
    sidecar = re.sub(r"\.npy$", "", path) + ".json"
    with open(sidecar) as f:
        meta = json.load(f)
    return part, float(meta["cell"]), float(meta["x0"]), float(meta["y0"])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("gcode", help="input G-code file")
    p.add_argument("--part", required=True, help="part heightfield .npy "
                   "(with .json sidecar)")
    p.add_argument("--tool", choices=("flat", "ball", "bull"), default="flat")
    p.add_argument("--dia", type=float, default=6.0, help="tool diameter mm")
    p.add_argument("--corner", type=float, default=0.0,
                   help="bull-nose corner radius mm")
    p.add_argument("--stock", type=float, nargs=6, metavar=("XMIN", "XMAX",
                   "YMIN", "YMAX", "ZMIN", "ZMAX"), default=None,
                   help="stock bounding box mm (required unless --stock-in)")
    p.add_argument("--stock-in", dest="stock_in", default=None,
                  help="continue from a stock heightfield .npy saved by a "
                       "previous run's --stock-out (same grid as --part)")
    p.add_argument("--stock-out", dest="stock_out", default=None,
                  help="save the final stock heightfield to this .npy so a "
                       "later toolpath can continue via --stock-in")
    p.add_argument("--out-json", default=None, help="write report JSON here")
    p.add_argument("--png", default=None, help="optional leftover heatmap PNG")
    args = p.parse_args(argv)

    if args.stock is None and not args.stock_in:
        p.error("--stock is required unless --stock-in provides the stock state")

    if args.tool == "ball" and abs(args.corner - args.dia / 2) > 1e-9:
        args.corner = args.dia / 2
    if args.tool == "bull" and not (0 < args.corner < args.dia / 2):
        p.error("--corner must satisfy 0 < corner < dia/2 for a bull nose")

    with open(args.gcode) as f:
        moves = parse_gcode(f.read())
    part, cell, x0, y0 = load_part(args.part)

    stock_init = None
    if args.stock_in:
        stock_init = np.load(args.stock_in)
    if args.stock is not None:
        stock_box = tuple(args.stock)
    else:
        # Derive the box from the saved state's finite cells.
        jj, ii = np.where(np.isfinite(stock_init))
        if jj.size == 0:
            p.error("--stock-in file has no finite cells")
        stock_box = (x0 + ii.min() * cell, x0 + (ii.max() + 1) * cell,
                    y0 + jj.min() * cell, y0 + (jj.max() + 1) * cell,
                    float(np.nanmin(stock_init)),
                    float(np.nanmax(stock_init)))
    res = simulate(moves, part, cell, x0, y0, stock_box,
                   tool=args.tool, dia=args.dia, corner=args.corner,
                   stock_init=stock_init)

    report = {
        "gcode": os.path.abspath(args.gcode),
        "part": os.path.abspath(args.part),
        "tool": {"type": args.tool, "dia": args.dia, "corner": args.corner},
        "stock_box": [float(v) for v in stock_box],
        "stock_in": os.path.abspath(args.stock_in) if args.stock_in else None,
        "cell": cell,
        "gouges": res["gouges"],
        "leftover": res["leftover"],
        "rapid_collisions": res["rapid_collisions"],
        "air_fraction": res["air_fraction"],
    }
    text = json.dumps(report, indent=2)
    if args.out_json:
        with open(args.out_json, "w") as f:
            f.write(text + "\n")
    else:
        print(text)
    if args.stock_out:
        np.save(args.stock_out, res["stock"])
    if args.png:
        ok = write_png(res["stock"], part, cell, x0, y0, args.png)
        if not ok:
            print("PNG skipped (matplotlib unavailable)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
