"""Independent ROUGH CLCHECK gate (Task R2 item 2).

One-sided drop-cutter check with the ACTUAL cutter on every rough cutting
move of a neutral G-code file, sampled <= `step` mm:
a sample FAILS when its tip Z sits more than `tol` mm below
CL_part(x, y) + axial_leave, i.e. the tip must stay >= CL + axl - tol.
Non-zero exit with the G-code line and XY of every violator (worst first).

Usage:
    python -m engine.probe_rough_clcheck <file.ngc> --stl S \
        --tool flat:12.686 | bull:12.7:0.127 [--axial-leave 0.381] \
        [--step 0.1] [--tol 0.005] [--max-report 20]

This is a SEPARATE code path from the island generation in engine/rough.py:
it only uses ocl.BatchDropCutter on the raw mesh.
"""
import argparse
import math
import re
import sys

import numpy as np
from opencamlib import ocl


def make_cutter(spec):
    kind, dia, corner = (spec.split(":") + ["0.0"])[:3]
    dia, corner = float(dia), float(corner)
    if kind == "flat":
        return ocl.CylCutter(dia, 50.0)
    if kind == "bull":
        return ocl.BullCutter(dia, corner, 50.0)
    if kind == "ball":
        return ocl.BallCutter(dia, 50.0)
    raise SystemExit("unknown tool kind %r" % kind)


def collect_samples(path, step):
    """G1 cutting moves -> (x, y, z, line) samples every <= step mm.
    Horizontal/ascending moves are sampled along their whole length; a
    descending move is checked at its END only (the descent itself is a
    plunge/ramp: the tool is allowed to be below CL while entering, and at
    its final depth it must be clear)."""
    P = {"X": None, "Y": None, "Z": None}
    prev = None
    xs, ys, zs, ln = [], [], [], []

    def add(a, b, n, line):
        t = np.arange(1, n + 1) / n
        xs.append(a[0] + (b[0] - a[0]) * t)
        ys.append(a[1] + (b[1] - a[1]) * t)
        zs.append(a[2] + (b[2] - a[2]) * t)
        ln.append(np.full(n, line))

    with open(path, newline="") as fh:
        for n, l in enumerate(fh, 1):
            if l.startswith("("):
                continue
            for a in "XYZ":
                m = re.search(a + r"(-?[\d.]+)", l)
                if m:
                    P[a] = float(m.group(1))
            if P["X"] is None or P["Y"] is None or P["Z"] is None:
                continue
            cur = (P["X"], P["Y"], P["Z"])
            if prev is not None and re.search(r"\bG0?1\b", l):
                horiz = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
                desc = cur[2] < prev[2] - 1e-9
                if horiz > 1e-9 and not desc:
                    add(prev, cur, max(1, int(math.ceil(horiz / step))), n)
                elif desc:
                    add(prev, cur, 1, n)
            prev = cur
    return (np.concatenate(xs), np.concatenate(ys), np.concatenate(zs),
            np.concatenate(ln))


def clcheck(xs, ys, zs, surf, cutter, axl, tol, chunk=250_000):
    """CL at every sample; returns (d = CL + axl - z, worst-first idx)."""
    cl = np.full(len(xs), np.nan)
    for a in range(0, len(xs), chunk):
        bd = ocl.BatchDropCutter()
        bd.setSTL(surf)
        bd.setCutter(cutter)
        for i in range(a, min(len(xs), a + chunk)):
            bd.appendPoint(ocl.CLPoint(float(xs[i]), float(ys[i]), -1e30))
        bd.run()
        v = np.array([p.z for p in bd.getCLPoints()])
        cl[a:a + chunk] = np.where(v <= -5e29, np.nan, v)
    fin = np.isfinite(cl)
    d = np.where(fin, cl + axl - zs, -np.inf)   # > tol => tip below safe Z
    order = np.argsort(-d)
    return d, order


def clcheck_moves(surf, cutter, moves, axl, ss=0.1, tol=0.005):
    """Engine-side CLCHECK gate (called at the end of rough()): one-sided
    drop-cutter with the ACTUAL cutter on every G1 cutting move of a neutral
    moves list, sampled <= ss mm. Returns [(move_index, x, y, z, depth)] for
    samples whose tip sits more than tol mm below CL + axl (depth = how far
    the tip is below CL + axl). Descending moves are checked at their end
    only (the plunge itself may pass through material)."""
    xs, ys, zs, idx = [], [], [], []
    prev = None
    for i, mv in enumerate(moves):
        if mv.get("x") is None or mv.get("y") is None or mv.get("z") is None:
            continue
        cur = (mv["x"], mv["y"], mv["z"])
        if prev is not None and mv["g"] == 1:
            horiz = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            desc = cur[2] < prev[2] - 1e-9
            if horiz > 1e-9 and not desc:
                n = max(1, int(math.ceil(horiz / ss)))
                t = np.arange(1, n + 1) / n
                xs.append(prev[0] + (cur[0] - prev[0]) * t)
                ys.append(prev[1] + (cur[1] - prev[1]) * t)
                zs.append(prev[2] + (cur[2] - prev[2]) * t)
                idx.append(np.full(n, i))
            elif desc:
                xs.append(np.array([cur[0]]))
                ys.append(np.array([cur[1]]))
                zs.append(np.array([cur[2]]))
                idx.append(np.array([i]))
        prev = cur
    if not xs:
        return []
    x = np.concatenate(xs); y = np.concatenate(ys)
    z = np.concatenate(zs); im = np.concatenate(idx)
    d, order = clcheck(x, y, z, surf, cutter, axl, tol)
    bad = []
    for k in order:
        if d[k] <= tol:
            break
        bad.append((int(im[k]), float(x[k]), float(y[k]), float(z[k]),
                   float(d[k])))
    return bad


def main(argv=None):
    p = argparse.ArgumentParser(prog="engine.probe_rough_clcheck")
    p.add_argument("ngc")
    p.add_argument("--stl", required=True)
    p.add_argument("--tool", required=True,
                   help="actual roughing cutter: flat:DIA | bull:DIA:CR | ball:DIA")
    p.add_argument("--axial-leave", dest="axl", type=float, default=0.381)
    p.add_argument("--step", type=float, default=0.1)
    p.add_argument("--tol", type=float, default=0.005)
    p.add_argument("--max-report", dest="max_report", type=int, default=20)
    a = p.parse_args(argv)

    if a.stl.lower().endswith((".step", ".stp")):
        raise SystemExit("--stl expects a tessellated .stl (got %s); run "
                        "`python -m engine.cli prepare --step <file> ...` or "
                        "use the cached out/<name>.stl" % a.stl)
    surf = ocl.STLSurf()
    ocl.STLReader(a.stl, surf)
    if surf.size() == 0:
        raise SystemExit("no triangles in %s" % a.stl)
    xs, ys, zs, ln = collect_samples(a.ngc, a.step)
    d, order = clcheck(xs, ys, zs, surf, make_cutter(a.tool), a.axl, a.tol)
    n_bad = int((d > a.tol).sum())
    print("rough clcheck %s: %d samples, %d violate tip >= CL + %.3f - %.3f"
          % (a.ngc, len(xs), n_bad, a.axl, a.tol), flush=True)
    if n_bad:
        for k in order[:a.max_report]:
            if d[k] <= a.tol:
                break
            print("  GOUGE %.3f mm below CL+leave at line %d  X%.3f Y%.3f "
                  "Z%.3f (CL %.3f)" % (d[k], ln[k], xs[k], ys[k], zs[k],
                                       d[k] + zs[k] - a.axl), flush=True)
        return 1
    print("PASS rough clcheck: 0 gouges", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
