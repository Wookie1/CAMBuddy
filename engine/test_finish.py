#!/usr/bin/env python3
"""Finish tests (task S1). Pure OCL on generated STLs, no FreeCAD. Run with
VibeCAD python:
    /Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_finish.py
(also pytest-compatible).

Three synthetic parts, each finished with a 6 mm ball (shallow raster
stepover 0.3 / steep waterline stepdown 0.3, threshold 40 deg) and verified
with zmap at a 0.1 mm heightfield:
  1. hemisphere on a plate        - shallow dome cap + steep sides
  2. 60-degree cone on a plate    - all wall is steep, apex shallow-free
  3. vertical-walled boss with a slot narrower than the ball (4 mm < 6 mm)
     - the case that made VibeCAD's SteepShallow gouge (DIAG_steepshallow):
       the ball must ride the slot edges, never below the true CL.
Gouges MUST be 0 on all three; % of surface left > 0.05 mm per slope zone
is reported (and asserted for the shallow zones of cases 1-2).
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, "/Applications/VibeCAD.app/Contents/Resources/lib")
sys.path.insert(0, os.path.join(ROOT, "verify"))

import numpy as np  # noqa: E402

from opencamlib import ocl  # noqa: E402
from engine import model  # noqa: E402
from engine.finish import (finish, finish_to_gcode, surf_bounds,  # noqa: E402
                           batch_drop, make_cutter)
import zmap  # noqa: E402

CELL = 0.1
BALL_DIA = 6.0


# ---------------------------------------------------------------------------
# ASCII STL writing + primitive meshes (outward normals auto-oriented via a
# reference vector per facet: the normal is flipped if it points inward).
# ---------------------------------------------------------------------------

def _nrm(a, b, c, ref):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    L = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / L, ny / L, nz / L
    if nx * ref[0] + ny * ref[1] + nz * ref[2] < 0:
        nx, ny, nz = -nx, -ny, -nz
        b, c = c, b
    return (nx, ny, nz), a, b, c


def write_stl(path, tris):
    n = 0
    with open(path, "w") as fh:
        fh.write("solid part\n")
        for (a, b, c, ref) in tris:
            if math.dist(a, b) < 1e-9 or math.dist(b, c) < 1e-9 \
                    or math.dist(a, c) < 1e-9:
                continue  # degenerate (pole) triangles
            (nx, ny, nz), a, b, c = _nrm(a, b, c, ref)
            fh.write("facet normal %.6f %.6f %.6f\nouter loop\n" %
                    (nx, ny, nz))
            for p in (a, b, c):
                fh.write("vertex %.6f %.6f %.6f\n" % p)
            fh.write("endloop\nendfacet\n")
            n += 1
        fh.write("endsolid part\n")
    assert n > 0, "no non-degenerate triangles"
    return path


def _box(xmin, xmax, ymin, ymax, zmin, zmax):
    """Walls+floor+ceiling of an axis-aligned box (the top face is split
    around a slot when slot_x is given by the caller instead)."""
    v = {(sx, sy, sz): (xmin if sx < 0 else xmax,
                        ymin if sy < 0 else ymax,
                        zmin if sz < 0 else zmax)
         for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)}

    def q(p1, p2, p3, p4, ref):
        return [(p1, p2, p3, ref), (p1, p3, p4, ref)]

    tris = []
    A, B, C, D = v[(-1, -1, 1)], v[(1, -1, 1)], v[(1, 1, 1)], v[(-1, 1, 1)]
    E, F, G, H = v[(-1, -1, -1)], v[(1, -1, -1)], v[(1, 1, -1)], v[(-1, 1, -1)]
    tris += q(A, B, C, D, (0, 0, 1))          # top
    tris += q(E, H, G, F, (0, 0, -1))        # bottom
    tris += q(A, E, F, B, (0, -1, 0))        # y-
    tris += q(D, C, G, H, (0, 1, 0))         # y+
    tris += q(A, D, H, E, (-1, 0, 0))        # x-
    tris += q(B, F, G, C, (1, 0, 0))         # x+
    return tris


def hemisphere_plate_stl(path, R=10.0, plate=16.0, thick=2.0,
                        n_phi=48, n_theta=128):
    """Hemisphere (R) on a plate [-plate, plate]^2, top face z=0."""
    tris = []
    # plate: top split into a ring of 4 quads around the dome footprint,
    # walls and bottom
    q = plate
    d = R + 0.5
    top = [(-q, -q), (q, -q), (q, q), (-q, q)]
    inn = [(-d, -d), (d, -d), (d, d), (-d, d)]
    # 4 trapezoid strips (each 2 triangles) + inner square (2 triangles)
    for i in range(4):
        j = (i + 1) % 4
        tris.append(((top[i][0], top[i][1], 0), (top[j][0], top[j][1], 0),
                     (inn[j][0], inn[j][1], 0), (0, 0, 1)))
        tris.append(((top[i][0], top[i][1], 0), (inn[j][0], inn[j][1], 0),
                     (inn[i][0], inn[i][1], 0), (0, 0, 1)))
    tris.append(((inn[0][0], inn[0][1], 0), (inn[1][0], inn[1][1], 0),
                 (inn[3][0], inn[3][1], 0), (0, 0, 1)))
    tris.append(((inn[1][0], inn[1][1], 0), (inn[2][0], inn[2][1], 0),
                 (inn[3][0], inn[3][1], 0), (0, 0, 1)))
    tris += [(a, b, c, ref) for (a, b, c, ref) in
             _box(-q, q, -q, q, -thick, 0.0)
             if ref != (0, 0, 1)]  # box walls/bottom only (top replaced)
    # hemisphere
    def sph(i, k):
        phi = 0.5 * math.pi * i / n_phi
        th = 2.0 * math.pi * k / n_theta
        r = R * math.cos(phi)
        return (r * math.cos(th), r * math.sin(th), R * math.sin(phi))

    for i in range(n_phi):
        for k in range(n_theta):
            k1 = (k + 1) % n_theta
            a, b = sph(i, k), sph(i, k1)
            c, d2 = sph(i + 1, k1), sph(i + 1, k)
            ctr = tuple(sum(p[s] for p in (a, b, c)) / 3.0 for s in range(3))
            tris.append((a, b, c, (ctr[0], ctr[1], ctr[2])))
            ctr = tuple(sum(p[s] for p in (a, c, d2)) / 3.0 for s in range(3))
            tris.append((a, c, d2, (ctr[0], ctr[1], ctr[2])))
    return write_stl(path, tris)


def cone_plate_stl(path, h=15.0, angle_deg=60.0, plate=15.0, thick=2.0,
                   n=128):
    """Cone with wall at `angle_deg` from horizontal, apex up, on a plate."""
    R = h / math.tan(math.radians(angle_deg))
    tris = []
    q = plate
    tris += _box(-q, q, -q, q, -thick, 0.0)
    # cone: base ring at z=0 (sits on plate top), apex at z=h
    def ring(k):
        th = 2.0 * math.pi * k / n
        return (R * math.cos(th), R * math.sin(th), 0.0)

    apex = (0.0, 0.0, h)
    for k in range(n):
        a, b = ring(k), ring((k + 1) % n)
        ctr = ((a[0] + b[0]) / 3.0, (a[1] + b[1]) / 3.0, h / 3.0)
        ref = (ctr[0], ctr[1], max(ctr[2], 0.1))
        tris.append((apex, a, b, ref))
    return write_stl(path, tris)


def slot_boss_stl(path, half_x=15.0, half_y=10.0, top=10.0,
                  slot_half=2.0, slot_floor=4.0):
    """Block with a straight slot (width 2*slot_half < ball dia) along Y."""
    sx = slot_half
    tris = []
    # walls / bottom of the block minus slot: build as 3 boxes side by side
    # left slab [ -half_x, -sx ], right slab [ sx, half_x ], slot floor box
    tris += _box(-half_x, -sx, -half_y, half_y, 0.0, top)
    tris += _box(sx, half_x, -half_y, half_y, 0.0, top)
    # slot interior floor (the slab side faces at x=+-sx already form the
    # slot walls with outward normals into the void)
    tris.append(((-sx, -half_y, slot_floor), (sx, -half_y, slot_floor),
                 (sx, half_y, slot_floor), (0, 0, 1)))
    tris.append(((-sx, -half_y, slot_floor), (sx, half_y, slot_floor),
                 (-sx, half_y, slot_floor), (0, 0, 1)))
    return write_stl(path, tris)


# ---------------------------------------------------------------------------
# analytic part heightfields (ground truth for zmap)
# ---------------------------------------------------------------------------

def _grid(box):
    xmin, xmax, ymin, ymax = box[:4]
    nx = int(round((xmax - xmin) / CELL))
    ny = int(round((ymax - ymin) / CELL))
    xs = xmin + (np.arange(nx) + 0.5) * CELL
    ys = ymin + (np.arange(ny) + 0.5) * CELL
    X, Y = np.meshgrid(xs, ys)
    return X, Y, nx, ny


def hf_hemisphere(X, Y, R=10.0):
    r2 = X * X + Y * Y
    return np.where(r2 <= R * R, np.sqrt(np.maximum(R * R - r2, 0.0)), 0.0)


def hf_cone(X, Y, h=15.0, angle_deg=60.0):
    R = h / math.tan(math.radians(angle_deg))
    r = np.hypot(X, Y)
    return np.where(r <= R, h - r * math.tan(math.radians(angle_deg)), 0.0)


def hf_slot_boss(X, Y, top=10.0, slot_half=2.0, slot_floor=4.0):
    return np.where(np.abs(X) < slot_half, slot_floor, top)


# ---------------------------------------------------------------------------
# drive one case
# ---------------------------------------------------------------------------

def run_case(name, stl_path, hf_fn, box, floor_z, assert_shallow_lt=None):
    """Finish the STL, simulate with zmap (ball 6) at 0.1 mm, check.
    box: (xmin, xmax, ymin, ymax) of the stock (zmin=0, zmax=part top)."""
    surf = model.load_surf(stl_path)
    zmax = float(surf.getBounds()[5])
    moves, stats = finish(surf, stl_path=stl_path,
                          tool=("ball", BALL_DIA, 0.0), floor_z=floor_z,
                          threads=4)
    assert moves, "%s: no moves" % name
    text = finish_to_gcode(moves)
    gmv = zmap.parse_gcode(text)
    X, Y, nx, ny = _grid(box)
    part = hf_fn(X, Y)
    stock_box = (box[0], box[1], box[2], box[3], 0.0, zmax)
    res = zmap.simulate(gmv, part, CELL, box[0], box[2], stock_box,
                        tool="ball", dia=BALL_DIA)
    gouges = res["gouges"]
    print("%-14s moves=%6d cut=%.0fmm plunge=%.0fmm lifts=%d "
          "steep_runs=%d shallow_runs=%d gouges=%d" %
          (name, len(moves), stats["cut_len"], stats["plunge_len"],
           stats["n_lifts"], stats["n_steep_runs"], stats["n_shallow_runs"],
           gouges["count"]))
    # leftover > 0.05 mm per slope zone (of the part surface). Cells where
    # the ball physically cannot bring its tip within 0.05 mm of the surface
    # (CL - part > 0.05: fillets at convex/concave tangencies) are reported
    # but excluded from the assert - no toolpath can cut them.
    gy, gx = np.gradient(part, CELL, CELL)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    leftover = res["stock"] - part
    fin = np.isfinite(res["stock"])
    cl = batch_drop(surf, make_cutter("ball", BALL_DIA, 0.0),
                   [tuple(p) for p in np.column_stack([X.ravel(), Y.ravel()])],
                   threads=4).reshape(X.shape)
    reachable = np.isfinite(cl) & (cl - part <= 0.05 + 1e-9)
    # on steep flanks CL-part ~ R*sin(slope) > 0.05 by construction, yet the
    # waterlines cut those cells fine (side engagement); treat slope>=40 as
    # reachable and apply the fillet exclusion only to shallow cells.
    reachable = reachable | (slope >= 40.0)
    for zone, zmask in (("steep", slope >= 40.0), ("shallow", slope < 40.0)):
        m = fin & zmask
        frac = float(np.mean(leftover[m] > 0.05)) if m.any() else 0.0
        mx = float(np.max(leftover[m])) if m.any() else 0.0
        mr = m & reachable
        fr = float(np.mean(leftover[mr] > 0.05)) if mr.any() else 0.0
        print("  %-8s cells=%6d  >0.05mm: %5.2f%% (reachable: %5.2f%% of"
              " %d)  max=%.3f" % (zone, int(m.sum()), 100.0 * frac,
                                 100.0 * fr, int(mr.sum()), mx))
        if zone == "shallow" and assert_shallow_lt is not None:
            assert fr < assert_shallow_lt, \
                "%s: %.2f%% of reachable shallow surface left >0.05 mm" % (
                    name, 100 * fr)
    assert gouges["count"] == 0, \
        "%s: %d gouges, max depth %.3f at %s" % (
            name, gouges["count"], gouges["max_depth"], gouges["worst_xy"])
    assert res["rapid_collisions"]["count"] == 0, \
        "%s: rapid collisions at line %s" % (
            name, res["rapid_collisions"]["first_line"])
    return stats


def test_hemisphere_on_plate():
    with tempfile.TemporaryDirectory() as td:
        stl = hemisphere_plate_stl(os.path.join(td, "hemi.stl"))
        run_case("hemisphere", stl, hf_hemisphere, (-16.0, 16.0, -16.0, 16.0),
                 floor_z=0.0, assert_shallow_lt=0.01)


def test_cone_60deg():
    with tempfile.TemporaryDirectory() as td:
        stl = cone_plate_stl(os.path.join(td, "cone.stl"))
        run_case("cone60", stl, hf_cone, (-15.0, 15.0, -15.0, 15.0),
                 floor_z=0.0, assert_shallow_lt=0.01)


def test_slot_narrower_than_ball():
    with tempfile.TemporaryDirectory() as td:
        stl = slot_boss_stl(os.path.join(td, "slot.stl"))
        # slot floor (4 mm) is unreachable by the 6 mm ball - leftover there
        # is expected and only reported; gouges must still be 0.
        run_case("slot-boss", stl, hf_slot_boss,
                 (-15.0, 15.0, -10.0, 10.0), floor_z=0.0)


if __name__ == "__main__":
    for fn in (test_hemisphere_on_plate, test_cone_60deg,
               test_slot_narrower_than_ball):
        t = __import__("time").time()
        fn()
        print("%s OK in %.1fs" % (fn.__name__, __import__("time").time() - t))
    print("ALL FINISH TESTS PASSED")
