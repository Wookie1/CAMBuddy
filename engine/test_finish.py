#!/usr/bin/env python3
"""Finish tests (tasks S1 + S2 PLAN B). Pure OCL on generated STLs, no
FreeCAD. Run with VibeCAD python:
    /Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_finish.py
(also pytest-compatible).

Synthetic parts, each finished with a 6 mm ball (shallow raster stepover
0.3 / steep stepdown 0.3, threshold 40 deg) and verified with zmap at a
0.1 mm heightfield:
  1. hemisphere on a plate        - shallow dome cap + steep sides
  2. 60-degree cone on a plate    - all wall is steep, apex shallow-free
  3. vertical-walled boss with a slot narrower than the ball (4 mm < 6 mm)
     - the case that made VibeCAD's SteepShallow gouge (DIAG_steepshallow):
       the ball must ride the slot edges, never below the true CL.
  4. plate-at-floor: boss whose plate top equals the requested floor Z
     (S1d item 3) - the degenerate coplanar waterline case.
Gouges MUST be 0 on all five (incl. the S2b cylinder boss: one circle of
radius R + r at every level from floor up to H - r, the CL jump line);
% of surface left > 0.05 mm per slope zone
is reported (and asserted for the shallow zones of cases 1-2). Every output
additionally gets the exact one-sided CL check of engine/probe_clcheck.py
(every cutting move sampled at 0.25 mm, BallCutter(6) drop-cutter): MUST
report 0 points below CL by > 0.005 mm. PLAN B unit checks: refined
marching-squares contours vs analytic CL radii (hemisphere, cone), and a
gap-split whose link is verified clear.
"""
import json
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
                           batch_drop, make_cutter, cl_grid, march_level,
                           refine_contours, steep_runs_grid, segment_net,
                           link_plan, compute_rest_mask, CHORD_TOL,
                           RAPID_MARGIN, RAPID_STOCK_ALLOW, box_max,
                           load_heightfield, tool_geometry, SHANK_TOL,
                           holder_segments)
import zmap  # noqa: E402
from engine import post_lnc  # noqa: E402

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


def boss_plate_stl(path, q=15.0, top=10.0, bx=4.0, bh=20.0):
    """Plate [-q,q]^2 with top face at z=top (== the requested floor Z)
    and a raised square boss [-bx,bx]^2 up to z=bh (S1d item 3: the floor
    level is coplanar with the plate's main flat face)."""
    tris = _box(-q, q, -q, q, 0.0, top)
    tris += _box(-bx, bx, -bx, bx, top, bh)
    return write_stl(path, tris)


def hf_boss_plate(X, Y, top=10.0, bx=4.0, bh=20.0):
    return np.where((np.abs(X) < bx) & (np.abs(Y) < bx), bh, top)


def cylinder_boss_stl(path, q=15.0, R=5.0, H=12.0, n=96):
    """Vertical cylinder boss (radius R, height H > r + several stepdowns)
    on a flat plate top z=0 (S2b item 3: CL jumps from floor to H - r at
    distance r from the wall)."""
    tris = _box(-q, q, -q, q, -2.0, 0.0)

    def ring(k, z):
        th = 2.0 * math.pi * k / n
        return (R * math.cos(th), R * math.sin(th), z)

    for k in range(n):
        a, b = ring(k, 0.0), ring((k + 1) % n, 0.0)
        a2, b2 = ring(k, H), ring((k + 1) % n, H)
        ref = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, H / 2.0)
        tris.append((a, b, b2, ref))
        tris.append((a, b2, a2, ref))
    for k in range(n):
        tris.append(((0.0, 0.0, H), ring(k, H), ring((k + 1) % n, H),
                     (0.0, 0.0, 1.0)))
    return write_stl(path, tris)


def hf_cyl(X, Y, R=5.0, H=12.0):
    return np.where(np.hypot(X, Y) <= R, H, 0.0)


# ---------------------------------------------------------------------------
# exact one-sided CL check (same criterion as engine/probe_clcheck.py):
# every cutting move sampled at 0.25 mm, BallCutter(6) drop-cutter,
# CL - z <= 0.005 mm at every sample.
# ---------------------------------------------------------------------------

def clcheck_moves(surf, moves, step=0.25, threads=4, dia=None):
    """(n_points, n_below, max_depth) for all G1 moves of `moves`."""
    cutter = make_cutter("ball", dia or BALL_DIA, 0.0)
    xs, ys, zs = [], [], []
    prev = None
    for mv in moves:
        cur = (mv.get("x"), mv.get("y"), mv.get("z"))
        if None in cur:
            continue
        if prev is not None and mv["g"] == 1:
            m = max(1, int(math.ceil(math.hypot(cur[0] - prev[0],
                                               cur[1] - prev[1]) / step)))
            t = np.arange(1, m + 1) / m
            xs.append(prev[0] + (cur[0] - prev[0]) * t)
            ys.append(prev[1] + (cur[1] - prev[1]) * t)
            zs.append(prev[2] + (cur[2] - prev[2]) * t)
        prev = cur
    if not xs:
        return 0, 0, 0.0
    x = np.concatenate(xs)
    y = np.concatenate(ys)
    z = np.concatenate(zs)
    cl = batch_drop(surf, cutter, list(zip(x.tolist(), y.tolist())),
                   threads=threads)
    d = cl - z
    bad = d > CHORD_TOL
    return len(x), int(bad.sum()), float(np.nanmax(d)) if len(d) else 0.0


# ---------------------------------------------------------------------------
# S2c: no duplicated shallow raster rows - no two emitted cutting segments
# overlap (same Y row, overlapping X span, same Z within 0.01 mm)
# ---------------------------------------------------------------------------

def dup_cut_segments(moves, ztol=0.01, ytol=0.2, overlap=1.0):
    """Count pairs of G1 constant-Z moves that are row-like (|dY| < 0.35,
    dX > 1 mm) and overlap: |Y center diff| < ytol (half a stepover), X
    spans overlap > `overlap` mm, |Z diff| <= ztol. A full-width drag
    between raster rows (the S2c bug) matches both neighbouring rows."""
    segs = []
    prev = None
    for mv in moves:
        cur = (mv.get("x"), mv.get("y"), mv.get("z"))
        if None in cur:
            continue
        if prev is not None and mv["g"] == 1 and abs(cur[2] - prev[2]) < 1e-6:
            dx, dy = cur[0] - prev[0], cur[1] - prev[1]
            if abs(dx) > 1.0 and abs(dy) < 0.35:
                segs.append((min(prev[0], cur[0]), max(prev[0], cur[0]),
                            0.5 * (prev[1] + cur[1]), cur[2]))
        prev = cur
    byz = {}
    for idx, s in enumerate(segs):
        byz.setdefault(round(s[3], 2), []).append(idx)
    pairs = set()
    for idx, s in enumerate(segs):
        zz = round(s[3], 2)
        for dz2 in (-1, 0, 1):  # z rounding can straddle a bucket edge
            for jdx in byz.get(round(zz + dz2 * 0.01, 2), ()):
                if jdx <= idx:
                    continue
                t = segs[jdx]
                if abs(s[2] - t[2]) < ytol and abs(s[3] - t[3]) <= ztol \
                        and min(s[1], t[1]) - max(s[0], t[0]) > overlap:
                    pairs.add((idx, jdx))
    return len(pairs)


# ---------------------------------------------------------------------------
# drive one case
# ---------------------------------------------------------------------------

def run_case(name, stl_path, hf_fn, box, floor_z, assert_shallow_lt=None,
             dia=None, extra_calls=0):
    """Finish the STL, simulate with zmap at 0.1 mm, check.
    box: (xmin, xmax, ymin, ymax) of the stock (zmin=0, zmax=part top)."""
    dia = dia or BALL_DIA
    surf = model.load_surf(stl_path)
    zmax = float(surf.getBounds()[5])
    moves, stats = finish(surf, stl_path=stl_path,
                          tool=("ball", dia, 0.0), floor_z=floor_z,
                          threads=4)
    assert moves, "%s: no moves" % name
    text = finish_to_gcode(moves)
    gmv = zmap.parse_gcode(text)
    X, Y, nx, ny = _grid(box)
    part = hf_fn(X, Y)
    stock_box = (box[0], box[1], box[2], box[3], 0.0, zmax)
    # finish starts from POST-ROUGHING stock (part + axial leave), matching
    # the acceptance chain --stock-in out/stock_roughG_01.npy; a raw full-box
    # start would flag verified rapids (CL + margin + allow) against material
    # no finish op ever sees.
    stock_init = np.minimum(zmax, part + 0.381)
    res = zmap.simulate(gmv, part, CELL, box[0], box[2], stock_box,
                        tool="ball", dia=dia, stock_init=stock_init)
    gouges = res["gouges"]
    print("%-14s moves=%6d cut=%.0fmm plunge=%.0fmm lifts=%d "
          "rapid_links=%d/%d(%.0fmm) feed_links=%d(%.0fmm) "
          "steep_runs=%d shallow_runs=%d gouges=%d removed=%d splits=%d "
          "drop_calls=%d (rounds=%d chords=%d)" %
          (name, len(moves), stats["cut_len"], stats["plunge_len"],
           stats["n_lifts"], stats["n_rapid_links"],
           stats["n_rapid_links"] + stats["n_feed_links"]
           + stats["n_lift_links"], stats["rapid_link_len"],
           stats["n_feed_links"] + stats["n_lift_links"],
           stats["feed_link_len"],
           stats["n_steep_runs"], stats["n_shallow_runs"],
           gouges["count"], stats["n_steep_removed"], stats["n_seg_splits"],
           stats["n_drop_calls"],
           stats["n_simplify_rounds"], stats["n_chords_checked"]))
    # S1c: the gouge-safe simplification must verify its chords in O(rounds)
    # batched drop-cutter calls (one per round), not one call per chord -
    # every call re-indexes the whole STL (setSTL). Fixed overhead: raster
    # row batches, window probe, CL grid, refine rounds (<=6) + jump check,
    # segment net, curve-sample extras, links, S4 shank nets (steep+shallow:
    # +2), PQ grid_snap (candidate CL + snapped-chord net, steep+shallow:
    # +4).
    assert stats["n_drop_calls"] <= 32 + 2 * stats["n_simplify_rounds"] \
        + extra_calls, \
        "%s: %d drop-cutter calls vs rounds=%d (expected O(rounds))" % (
            name, stats["n_drop_calls"], stats["n_simplify_rounds"])
    # leftover > 0.05 mm per slope zone (of the part surface). Cells where
    # the ball physically cannot bring its tip within 0.05 mm of the surface
    # (CL - part > 0.05: fillets at convex/concave tangencies) are reported
    # but excluded from the assert - no toolpath can cut them.
    gy, gx = np.gradient(part, CELL, CELL)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    leftover = res["stock"] - part
    fin = np.isfinite(res["stock"])
    cl = batch_drop(surf, make_cutter("ball", dia, 0.0),
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
    # S2 acceptance (engine/probe_clcheck.py criterion): 0 points below CL
    n_ck, n_bad, mx = clcheck_moves(surf, moves, dia=dia)
    print("  clcheck: %d samples, below CL by >%.3f mm: %d (max %.4f)"
          % (n_ck, CHORD_TOL, n_bad, mx))
    assert n_bad == 0, "%s: clcheck %d points below CL, max %.3f" % (
        name, n_bad, mx)
    # S2c: no duplicated cutting rows (full-width drags between raster rows)
    n_dup = dup_cut_segments(moves)
    print("  dup-row segments: %d" % n_dup)
    assert n_dup == 0, "%s: %d duplicated overlapping cutting segments" % (
        name, n_dup)
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
        stats = run_case("slot-boss", stl, hf_slot_boss,
                         (-15.0, 15.0, -10.0, 10.0), floor_z=0.0)
        # S2b item 4: wall contours at CL jumps are back - near the S1b
        # waterline baseline (steep_runs=35).
        assert stats["n_steep_runs"] >= 30, \
            "slot-boss steep runs %d < 30 (S1b: 35)" % stats["n_steep_runs"]
        # S2c: cut_len now counts only cutting travel - the S1b figure
        # (~7.6 m) also contained the full-width row-transition drags and
        # lift-height traverses (verified non-cutting, now rapid_len).
        assert stats["cut_len"] >= 4500.0, \
            "slot-boss cut %.0f mm < 4500 (honest S2c ~5240)" % \
            stats["cut_len"]


def test_cylinder_boss_wall():
    """S2b item 3: vertical cylinder boss R on a floor - the CL jumps from
    floor to H - r at distance r, so every level from the floor up to
    H - r must produce ONE circle of radius R + r (+-0.01); zmap 0.1 mm
    0 gouges and probe_clcheck criterion 0."""
    R, H = 5.0, 12.0
    r = 0.5 * BALL_DIA
    with tempfile.TemporaryDirectory() as td:
        stl = cylinder_boss_stl(os.path.join(td, "cyl.stl"))
        surf = model.load_surf(stl)
        cutter = make_cutter("ball", BALL_DIA, 0.0)
        xs, ys, Zg, gxA, gyA = _cl_grid_full(surf)
        zs = [0.3, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0]
        for z in zs:
            loops = [(P, K) for (P, c, K) in march_level(Zg, xs, ys, z)
                     if len(P) >= 2]
            assert len(loops) == 1, "z=%.1f: %d loops (want 1)" % (
                z, len(loops))
            ref = refine_contours(surf, cutter, [(z, loops[0][0], loops[0][1],
                                                 True)], Zg, xs[0], ys[0],
                                 0.1, threads=4)
            (_z, pos, cl, ok, _c) = ref[0]
            assert ok.all(), "z=%.1f: points below CL" % z
            rho = np.hypot(pos[:, 0], pos[:, 1])
            err = float(np.max(np.abs(rho - (R + r))))
            assert err <= 0.01, "z=%.1f: radius err %.4f mm" % (z, err)
        print("cyl contours: 1 circle of radius R+r at %d levels" % len(zs))
        stats = run_case("cyl-boss", stl, hf_cyl,
                         (-15.0, 15.0, -15.0, 15.0), floor_z=0.0)
        assert stats["n_steep_runs"] >= len(zs), \
            "cyl-boss steep runs %d < %d" % (stats["n_steep_runs"], len(zs))


def test_cl_jump_between_grid_points_posts_zero_below_cl():
    """PQ item 4: vertical-wall part whose CL jump circle sits BETWEEN
    output-grid points (R = 5.0005 -> jump at rho = R + r = 8.0005 mm for
    the 6 mm ball). The engine snaps every emitted point onto the post grid
    (metric post: 0.001 mm) with Z rounded UP to the closest-side CL, so
    the posted 3-decimal program keeps every point at or above CL:
    engine/probe_clcheck.py must report 0 points below CL, and the post's
    rounding is a no-op on the neutral (snapped) coordinates."""
    import re
    import subprocess
    from engine.finish import grid_decimals
    R, H = 5.0005, 12.0
    r = 0.5 * BALL_DIA
    assert abs((R + r) / 0.001 - round((R + r) / 0.001)) > 0.2, \
        "jump line must fall between 0.001 mm grid points"
    with tempfile.TemporaryDirectory() as td:
        stl = cylinder_boss_stl(os.path.join(td, "wall.stl"), q=15.0,
                                R=R, H=H)
        surf = model.load_surf(stl)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", BALL_DIA, 0.0),
                             floor_z=0.0, threads=4)
        assert stats["n_steep_pts"] > 0 and moves
        # every emitted coordinate is exactly on the output grid
        for mv in moves:
            for a in ("x", "y", "z"):
                v = mv.get(a)
                if v is not None:
                    assert abs(v / 0.001 - round(v / 0.001)) < 1e-6, \
                        "off-grid %s=%r" % (a, v)
        neutral = os.path.join(td, "finish_neutral.ngc")
        with open(neutral, "w") as fh:
            fh.write(finish_to_gcode(moves, decimals=grid_decimals(0.001)))
        posted = os.path.join(td, "finish.nc")
        with open(posted, "w", newline="") as fh:
            fh.write(post_lnc.post_text(open(neutral).read(), metric=True,
                                       program=1001, tool_number=20,
                                       crlf=False))
        # post rounding is a no-op: every posted coordinate equals a
        # neutral (grid-snapped) coordinate
        want = set()
        for mv in moves:
            for a in ("x", "y", "z"):
                if mv.get(a) is not None:
                    want.add(round(mv[a], 3))
        got = [float(m.group(2))
               for l in open(posted).read().splitlines()
               if not l.startswith("(") and "G53" not in l and "G28" not in l
               for m in re.finditer(r"\b([XYZ])(-?[0-9]*\.?[0-9]+)", l)]
        assert got, "no coordinates in posted program"
        assert all(v in want for v in got), \
            "post rounding changed a coordinate: %s" % (
                sorted(set(v for v in got if v not in want))[:5],)
        # the judge: probe_clcheck on the posted program (0 below CL)
        py = sys.executable
        r_ = subprocess.run([py, os.path.join(ROOT, "engine",
                                             "probe_clcheck.py"),
                             posted, stl, "%.4f" % BALL_DIA],
                            capture_output=True, text=True)
        assert r_.returncode == 0, r_.stderr[-500:]
        rep = json.loads(r_.stdout.strip().splitlines()[-1])
        print("grid-jump post: points=%d below_cl=%d max=%.4f"
              % (rep["points"], rep["below_cl"], rep["max_depth_mm"]))
        assert rep["points"] > 0 and rep["below_cl"] == 0, \
            "posted program has %d points below CL (max %.3f mm)" % (
                rep["below_cl"], rep.get("max_depth_mm", 0.0))


def test_plate_at_floor():
    """Plate top == requested floor Z (coplanar-flat degenerate level):
    zmap 0.1 mm must show 0 gouges, clcheck 0."""
    with tempfile.TemporaryDirectory() as td:
        stl = boss_plate_stl(os.path.join(td, "bossfloor.stl"))
        run_case("plate-floor", stl, hf_boss_plate,
                 (-15.0, 15.0, -15.0, 15.0), floor_z=10.0)


def test_no_duplicate_raster_rows():
    """S2c: shallow raster rows must be emitted ONCE. No two cutting
    segments may overlap (same Y row, overlapping X span, same Z within
    0.01 mm) - the full-width drags between raster rows duplicated them
    (full part: 11,749 long rows at 2,050 distinct Y). Cut length stays
    within 20% of the S1b synthetic numbers at equal zmap coverage:
    S1b's stats cut_len (hemisphere ~7.8 m, slot-boss ~7.6 m) included
    the duplicated drags and the horizontal travel at lift height (>= local
    max CL + 1 mm, verified non-cutting); the honest S2c cutting lengths
    are hemisphere ~3.6 m, slot-boss ~5.2 m, with identical leftover/gouge
    results."""
    for name, maker, hf, box, floor, s1b_cut in (
            ("hemisphere", hemisphere_plate_stl, hf_hemisphere,
             (-16.0, 16.0, -16.0, 16.0), 0.0, 3641.0),
            ("slot-boss", slot_boss_stl, hf_slot_boss,
             (-15.0, 15.0, -10.0, 10.0), 0.0, 5241.0)):
        with tempfile.TemporaryDirectory() as td:
            stl = maker(os.path.join(td, "p.stl"))
            stats = run_case(name, stl, hf, box, floor_z=floor)
            assert 0.8 * s1b_cut <= stats["cut_len"] <= 1.2 * s1b_cut, \
                "%s: cut %.0f mm outside 20%% of S1b %.0f" % (
                    name, stats["cut_len"], s1b_cut)


# ---------------------------------------------------------------------------
# PLAN B unit checks: grid contours vs analytic CL radii, gap split + link
# ---------------------------------------------------------------------------

def _cl_grid_full(surf, sp=0.1):
    b = surf_bounds(surf)
    xs = np.arange(b[0], b[1] + 0.5 * sp, sp)
    ys = np.arange(b[2], b[3] + 0.5 * sp, sp)
    cutter = make_cutter("ball", BALL_DIA, 0.0)
    Zg = cl_grid(surf, cutter, xs, ys,
                 np.ones((len(ys), len(xs)), dtype=bool), threads=4)
    with np.errstate(invalid="ignore"):
        gyA, gxA = np.gradient(Zg, sp, sp)
    return xs, ys, Zg, gxA, gyA


def _contour_radii(stl_path, zs, rho_fn, cl_rule="smooth"):
    """Refined contours at `zs` vs the analytic CL radius rho_fn(z);
    returns (n_pts, worst radial err, worst cl-rule violation). cl_rule
    "smooth": |CL - Z| (no CL jumps on the shape); "low": CL <= Z + 0.005
    (jump shapes: the low-side endpoint sits at floor CL below Z)."""
    surf = model.load_surf(stl_path)
    cutter = make_cutter("ball", BALL_DIA, 0.0)
    xs, ys, Zg, gxA, gyA = _cl_grid_full(surf)
    loops = []
    for z in zs:
        for (P, closed, K) in march_level(Zg, xs, ys, z):
            if len(P) >= 2:
                loops.append((z, P, K, closed))
    assert loops, "%s: no contours" % stl_path
    refined = refine_contours(surf, cutter, loops, Zg, xs[0], ys[0],
                              0.1, threads=4)
    n = 0
    wr = 0.0
    wc = -1e9
    by_z = {}
    for item in refined:
        by_z.setdefault(item[0], []).append(item)
    for z, items in by_z.items():
        # the loop nearest the analytic radius is the dome/wall contour; other
        # loops (CL-jump rings at tangencies) are separate and not checked
        items.sort(key=lambda it: abs(float(np.mean(np.hypot(
            it[1][:, 0], it[1][:, 1]))) - rho_fn(z)))
        (_z, pos, cl, ok, _c) = items[0]
        assert ok.all(), "%s z=%.2f: refine left points below CL" % (
            stl_path, z)
        rho = np.hypot(pos[:, 0], pos[:, 1])
        wr = max(wr, float(np.max(np.abs(rho - rho_fn(z)))))
        fin = np.isfinite(cl)
        assert fin.all(), "%s: refine lost contact" % stl_path
        e = cl - z if cl_rule == "low" else np.abs(cl - z)
        wc = max(wc, float(np.max(e)))
        n += len(pos)
    return n, wr, wc


def test_contour_vs_analytic_hemisphere():
    """Ball r=3 on hemisphere R=10: CL circle at tip height z has radius
    sqrt((R+r)^2 - (z+r)^2)."""
    with tempfile.TemporaryDirectory() as td:
        stl = hemisphere_plate_stl(os.path.join(td, "hemi.stl"))
        R, r = 10.0, 0.5 * BALL_DIA
        rho_fn = lambda z: math.sqrt((R + r) ** 2 - (z + r) ** 2)
        n, wr, wc = _contour_radii(stl, [2.0, 4.0, 6.0, 8.0], rho_fn)
        print("hemi contours: pts=%d radial_err<=%.4f cl_err<=%.4f"
              % (n, wr, wc))
        # width-converged bisection: |CL - Z| <= REFINE_W * |grad CL|
        assert wr <= 0.01 and wc <= 0.008


def test_contour_vs_analytic_cone():
    """Ball r on a 60-deg cone: contact at z_s = z + r(1-cos a), radius
    (h - z_s)/tan a + r sin a."""
    with tempfile.TemporaryDirectory() as td:
        stl = cone_plate_stl(os.path.join(td, "cone.stl"))
        h, r = 15.0, 0.5 * BALL_DIA
        a = math.radians(60.0)

        def rho_fn(z):
            return (h - z - r * (1.0 - math.cos(a))) / math.tan(a) \
                + r * math.sin(a)

        n, wr, wc = _contour_radii(stl, [2.0, 4.0, 6.0, 8.0], rho_fn)
        print("cone contours: pts=%d radial_err<=%.4f cl_err<=%.4f"
              % (n, wr, wc))
        # width-converged bisection: |CL - Z| <= REFINE_W * |grad CL|
        assert wr <= 0.01 and wc <= 0.008


def test_gap_split_and_verified_link():
    """A closed contour with two arcs pushed below CL: removal SPLITS it;
    links across the gaps must be verified clear (lift, never bridged at
    cutting depth), and every surviving segment interior passes the
    one-sided check."""
    with tempfile.TemporaryDirectory() as td:
        stl = hemisphere_plate_stl(os.path.join(td, "hemi.stl"))
        surf = model.load_surf(stl)
        cutter = make_cutter("ball", BALL_DIA, 0.0)
        z = 5.0
        rho = math.sqrt(13.0 ** 2 - (z + 3.0) ** 2)
        th = np.linspace(0.0, 2.0 * math.pi, 96, endpoint=False)
        P = np.stack([rho * np.cos(th), rho * np.sin(th)], axis=1)
        for (i0, i1) in ((24, 40), (64, 80)):
            P[i0:i1] *= (rho - 0.6) / rho  # below CL by ~0.8 mm
        cl = batch_drop(surf, cutter, [tuple(p) for p in P], threads=4)
        ok = np.where(np.isfinite(cl), cl - z <= CHORD_TOL, True)
        assert int(ok[24:40].sum()) == 0 and int(ok[64:80].sum()) == 0
        xs, ys, Zg, gxA, gyA = _cl_grid_full(surf)
        slopeA = np.degrees(np.arctan(np.hypot(gxA, gyA)))
        runs, n_removed = steep_runs_grid([(z, P, cl, ok, True)], slopeA,
                                          xs[0], ys[0], 0.1)
        print("gap-split: removed=%d runs=%d" % (n_removed, len(runs)))
        assert n_removed == 32 and len(runs) == 2
        # links across the gaps: must be LIFT (chord cuts dome interior)
        for (a, b) in ((runs[0][1][-1], runs[1][1][0]),
                      (runs[1][1][-1], runs[0][1][0])):
            plan = link_plan(surf, cutter,
                            [((float(a[0]), float(a[1]), z),
                              (float(b[0]), float(b[1]), z))], threads=4)[0]
            mode, lift_z, mx = plan
            assert mode in ("lift", "rapid") and lift_z >= mx + 0.99, \
                "gap link not lifted clear: %s" % (plan,)
        # segment net: after its splits, every surviving segment interior is
        # verified clear (no sample below CL)
        runs2, n_split = segment_net(surf, cutter, runs, ss=0.1, threads=4)
        xy = []
        for (_, R2) in runs2:
            for k in range(len(R2) - 1):
                m = max(1, int(math.ceil(math.hypot(
                    R2[k + 1, 0] - R2[k, 0], R2[k + 1, 1] - R2[k, 1]) / 0.1)))
                t = np.arange(1, m + 1) / (m + 1)
                xy.extend(zip(R2[k, 0] + (R2[k + 1, 0] - R2[k, 0]) * t,
                             R2[k, 1] + (R2[k + 1, 1] - R2[k, 1]) * t))
        cz = batch_drop(surf, cutter, xy, threads=4)
        assert float(np.nanmax(cz)) <= z + CHORD_TOL, \
            "segment_net left a segment below CL"
        print("gap-split: seg_net splits=%d -> runs=%d, all clear"
              % (n_split, len(runs2)))


# ---------------------------------------------------------------------------
# S3: flat-plate cut length + link kinds, two-boss verified rapid,
#    placeholder corner rest pass
# ---------------------------------------------------------------------------

def plate_stl(path, q=15.0, top=10.0, thick=2.0):
    """Flat plate [-q,q]^2, top face z=top, no features."""
    return write_stl(path, _box(-q, q, -q, q, -thick, top))


def hf_plate(X, Y, top=10.0):
    return np.full(X.shape, top)


def two_boss_stl(path, q=15.0, top=10.0, bx=2.5, cx=5.0, bh=20.0):
    """Plate top z=top with two square bosses ([-bx,bx]^2 around (+-cx, 0))
    up to z=bh; the inner faces leave a 2*bx-wide gap narrower than the
    6 mm ball, so row links must lift OVER a boss (S3 item 2)."""
    tris = _box(-q, q, -q, q, 0.0, top)
    tris += _box(cx - bx, cx + bx, -bx, bx, top, bh)
    tris += _box(-cx - bx, -cx + bx, -bx, bx, top, bh)
    return write_stl(path, tris)


def hf_two_boss(X, Y, top=10.0, bx=2.5, cx=5.0, bh=20.0):
    inb = np.abs(np.abs(X) - cx) < bx
    iny = np.abs(Y) < bx
    return np.where(inb & iny, bh, top)


def _rapids(moves):
    """G0 moves with XY travel: [(x0, y0, x1, y1, z), ...] (rapids that
    actually traverse; pure-Z rapids excluded)."""
    out, prev = [], None
    for mv in moves:
        cur = (mv.get("x"), mv.get("y"), mv.get("z"))
        if None in cur:
            continue
        if prev is not None and mv["g"] == 0:
            Lxy = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            if Lxy > 1.0:
                out.append((prev[0], prev[1], cur[0], cur[1], cur[2]))
        prev = cur
    return out


def rapid_max_cl(surf, rapids, step=0.25, threads=4, dia=None):
    """max drop-cutter CL along each rapid's XY path (sampled <= 0.25 mm)."""
    if not rapids:
        return []
    xy, spans = [], []
    for (x0, y0, x1, y1, _z) in rapids:
        m = max(2, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / step))) + 1
        s0 = len(xy)
        t = np.arange(m) / (m - 1)
        xy.extend(zip(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        spans.append((s0, len(xy)))
    cl = batch_drop(surf, make_cutter("ball", dia or BALL_DIA, 0.0), xy,
                   threads=threads)
    out = []
    for (rap, (s0, s1)) in zip(rapids, spans):
        c = cl[s0:s1]
        out.append((rap, float(np.nanmax(c)) if np.isfinite(c).any()
                   else float("-inf")))
    return out


def test_flat_plate_length_and_links():
    """S3 item 2: flat plate, no features. Cut length must be within
    1.2 x the ideal raster length (area/stepover + row transitions) and
    every link must be a rapid or a stepover move (no drags, no lifts -
    the plate links are verified-clear at cutting height)."""
    q, top, so = 15.0, 10.0, 0.3
    with tempfile.TemporaryDirectory() as td:
        stl = plate_stl(os.path.join(td, "plate.stl"))
        stats = run_case("flat-plate", stl, hf_plate,
                         (-q, q, -q, q), floor_z=top)
        ideal = (2 * q) * (2 * q) / so + (2 * q / so) * so  # + transitions
        assert stats["cut_len"] <= 1.2 * ideal, \
            "flat plate cut %.0f mm > 1.2 x ideal %.0f" % (stats["cut_len"],
                                                           1.2 * ideal)
        assert stats["cut_len"] >= 0.5 * ideal, \
            "flat plate cut %.0f mm < 0.5 x ideal (degenerate)" % \
            stats["cut_len"]
        n_links = (stats["n_rapid_links"] + stats["n_feed_links"]
                   + stats["n_lift_links"])
        assert n_links >= 10, "expected ~row-count links, got %d" % n_links
        # links must be rapids or stepover moves: no blocked (lift) links,
        # and the feed links average one stepover
        assert stats["n_lift_links"] == 0, \
            "flat plate has %d feed-lift links" % stats["n_lift_links"]
        mean_feed = stats["feed_link_len"] / max(1, stats["n_feed_links"])
        assert mean_feed <= so + 0.05, \
            "mean feed link %.3f mm > stepover + tol" % mean_feed
        assert stats["n_feed_links"] == n_links, \
            "flat-plate links not all verified stepover downs"


def test_two_boss_rapid_over_boss():
    """S3 item 2b: two bosses, gap narrower than the ball - a link must
    lift OVER a boss as a verified G0 rapid: z >= max CL along the path
    + margin, and at least one rapid clears the boss CL + margin."""
    q, top, bx, cx, bh = 15.0, 10.0, 2.5, 5.0, 20.0
    with tempfile.TemporaryDirectory() as td:
        stl = two_boss_stl(os.path.join(td, "2boss.stl"))
        stats = run_case("two-boss", stl, hf_two_boss,
                         (-q, q, -q, q), floor_z=top)
        assert stats["n_rapid_links"] >= 1, "no rapid links emitted"
        surf = model.load_surf(stl)
        moves, _ = finish(surf, stl_path=stl, tool=("ball", BALL_DIA, 0.0),
                          floor_z=top, threads=4)
        raps = rapid_max_cl(surf, _rapids(moves))
        for (x0, y0, x1, y1, z), mx in raps:
            assert z >= mx + RAPID_MARGIN - 1e-6, \
                "rapid at %.3f not clear: max CL along path %.3f + margin" \
                % (z, mx)
        over = [r for (r, mx) in raps if mx >= bh - 0.5]
        assert over, "no rapid lifted over a boss (max CL >= %.1f)" % (bh - 0.5)
        for (x0, y0, x1, y1, z) in over:
            assert z >= bh + RAPID_MARGIN - 1e-6, \
                "over-boss rapid z=%.3f < boss CL %.1f + margin" % (z, bh)
        print("two-boss rapids: %d total, %d over a boss (z>=%.1f)"
              % (len(raps), len(over), bh + RAPID_MARGIN))


def test_rest_pass_placeholder():
    """S3 item 3: corner rest pass with a PLACEHOLDER 3 mm ball on the
    slot-boss (slot 4 mm < 6 mm ball leaves >0.5 mm on the floor). The
    rest mask comes from the engine's own CL6-vs-CL3 drop-cutter map; the
    slot floor must get cut, the plate top must NOT, clcheck (ball 3)
    must be 0, zmap ball-3 gouges/rapid collisions 0, and the LNC post
    must refuse the placeholder tool."""
    q, hy, top, slot_half, slot_floor = 15.0, 10.0, 10.0, 2.0, 4.0
    with tempfile.TemporaryDirectory() as td:
        stl = slot_boss_stl(os.path.join(td, "slot.stl"))
        surf = model.load_surf(stl)
        # post-rough stock heightfield: block top + 0.381 axial leave
        X, Y, nx, ny = _grid((-q, q, -hy, hy))
        stock = np.full(X.shape, top + 0.381)
        np.save(os.path.join(td, "stock.npy"), stock)
        with open(os.path.join(td, "stock.json"), "w") as fh:
            json.dump({"x0": -q, "y0": -hy, "cell": CELL}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 3.0, 0.0),
                             floor_z=slot_floor, threads=4,
                             rest_from=os.path.join(td, "stock.npy"),
                             big_tool=("ball", 6.0, 0.0), min_rest=0.5)
        assert moves, "rest pass: no moves"
        assert stats.get("rest_pass") and stats.get("placeholder_tool")
        assert stats["n_rest_cells"] > 0, "empty rest mask"
        print("rest-pass: cells=%d runs steep/shallow=%d/%d cut=%.0fmm "
              "rapid_links=%d feed_links=%d" %
              (stats["n_rest_cells"], stats["n_steep_runs"],
               stats["n_shallow_runs"], stats["cut_len"],
               stats["n_rapid_links"], stats["n_feed_links"]))
        # slot floor reached by the 3 mm ball: some G1 near z=slot_floor
        zs = [mv["z"] for mv in moves if mv["g"] == 1
              and mv.get("z") is not None]
        assert min(zs) <= slot_floor + 0.35, \
            "rest pass never reached the slot floor (min z %.2f)" % min(zs)
        # plate top untouched: zmap with ball 3, leftover on the plate
        # (outside +-4 mm of the slot) must equal the roughing leave
        text = finish_to_gcode(moves, tool_comment="PLACEHOLDER ball D=3.000")
        assert "PLACEHOLDER" in text.splitlines()[4], "header lacks PLACEHOLDER"
        gmv = zmap.parse_gcode(text)
        part = hf_slot_boss(X, Y, top=top, slot_half=slot_half,
                            slot_floor=slot_floor)
        res = zmap.simulate(gmv, part, CELL, -q, -hy,
                            (-q, q, -hy, hy, 0.0, top + 0.381),
                            tool="ball", dia=3.0, stock_init=stock)
        assert res["gouges"]["count"] == 0, \
            "rest pass gouged: %d (max %.3f)" % (res["gouges"]["count"],
                                                 res["gouges"]["max_depth"])
        assert res["rapid_collisions"]["count"] == 0, \
            "rest pass rapid collision at line %s" % \
            res["rapid_collisions"]["first_line"]
        # plate top untouched in the far field (>= 2.5 mm from any wall -
        # near-wall cells are corner rest material and get cut to the part)
        plate = ((np.abs(X) > 4.0) & (np.abs(X) < q - 2.5)
                 & (np.abs(Y) < hy - 2.5))
        left = res["stock"] - part
        fin = np.isfinite(res["stock"]) & plate
        assert float(np.min(left[fin])) > 0.3, \
            "rest pass cut the plate top (min leftover %.3f)" % \
            float(np.min(left[fin]))
        slot = np.abs(X) <= 0.5  # strip the 3 mm ball can reach on the floor
        fins = np.isfinite(res["stock"]) & slot
        assert fins.any()
        assert float(np.max(left[fins])) < 0.1, \
            "rest pass left >0.1 mm on the reachable slot strip (max %.3f)" % \
            float(np.max(left[fins]))
        # exact one-sided CL check with the 3 mm ball: 0 below CL
        n_ck, n_bad, mx = clcheck_moves(surf, moves, dia=3.0)
        print("rest-pass clcheck(ball3): %d samples, below CL: %d (max %.4f)"
              % (n_ck, n_bad, mx))
        assert n_bad == 0, "rest-pass clcheck: %d below CL, max %.3f" % (
            n_bad, mx)
        # the LNC post must refuse the placeholder tool (not in the table)
        refused = False
        try:
            post_lnc.post_text(text, metric=True, tool_kind="ball",
                              dia_mm=3.0, corner_mm=1.5)
        except ValueError:
            refused = True
        assert refused, "LNC post accepted the PLACEHOLDER 3 mm ball"
        print("rest-pass: LNC post refused placeholder tool OK")


def test_rest_mask_units():
    """compute_rest_mask unit check on the slot-boss: cells over the slot
    (CL6 - CL3 > 0.5) selected, plate cells not; stock gate honoured."""
    with tempfile.TemporaryDirectory() as td:
        stl = slot_boss_stl(os.path.join(td, "slot.stl"))
        surf = model.load_surf(stl)
        xs = np.arange(-15.0, 15.0 + 0.05, 0.5)
        ys = np.arange(-10.0, 10.0 + 0.05, 0.5)
        m = compute_rest_mask(surf, xs, ys, ("ball", 6.0, 0.0),
                             ("ball", 3.0, 0.0), 0.5, threads=4)
        X, Y = np.meshgrid(xs, ys)
        # the 3 mm ball reaches the slot floor only where its centre has
        # wall clearance (|x| + 1.5 <= 2): CL6 - CL3 = 5.24 there
        in_slot = np.abs(X) < 0.4
        assert m[in_slot].all(), "slot-floor cells missing from rest mask"
        assert not m[np.abs(X) > 4.0].any(), \
            "plate cells in rest mask (CL6 - CL3 there is 0)"
        stock = np.full(X.shape, 4.2)  # barely above the slot floor
        m2 = compute_rest_mask(surf, xs, ys, ("ball", 6.0, 0.0),
                              ("ball", 3.0, 0.0), 0.5,
                              stock=(stock, -15.0, -10.0, 0.5), threads=4)
        assert not m2.any(), "stock gate failed: nothing to cut, mask empty"
        print("rest-mask units: slot=%d cells selected, stock gate OK"
              % int(m.sum()))


# ---------------------------------------------------------------------------
# S3b: rapids must clear the ROUGHING STOCK, not just the part
# ---------------------------------------------------------------------------

def test_stock_out_roundtrip():
    """S3b item 1 unit: save_stock_npy writes the StockField top surface as
    .npy (+ x0/y0/cell sidecar, NaN outside the tracked box), readable by
    finish.load_heightfield with identical geometry and values."""
    from engine.stock import StockField, save_stock_npy
    box = (-10.0, 10.0, -8.0, 8.0, 0.0, 12.0)
    sf = StockField(box, cell=0.5)
    sf.mill_path([(0.0, 0.0), (4.0, 0.0)], 5.0, 3.0)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "stock_final.npy")
        save_stock_npy(sf, p)
        A, x0, y0, cell = load_heightfield(p)
        assert A.shape == sf.top.shape and cell == sf.cell
        assert abs(x0 - sf.x0) < 1e-9 and abs(y0 - sf.y0) < 1e-9
        fin = np.isfinite(sf.top)
        assert np.array_equal(np.isfinite(A), fin), "NaN pattern mismatch"
        assert np.allclose(A[fin], sf.top[fin]), "stock values changed"
        assert float(np.nanmax(A)) == 12.0
    print("stock-out roundtrip: shape/values/sidecar OK")


def test_link_plan_stock_ridge():
    """S3b item 2 unit: link over a boss; an artificial stock ridge 2 mm
    above CL across the path. Without stock: rapid at CL + margin + allow.
    With the stock model: z_r >= ridge_top + margin (stock, not CL+allow,
    governs); feed-lift heights must clear the ridge the same way."""
    q, top, bx, cx, bh = 15.0, 10.0, 2.5, 5.0, 20.0
    hy, cell = 10.0, 0.5
    ridge_top = bh + 2.0
    with tempfile.TemporaryDirectory() as td:
        stl = two_boss_stl(os.path.join(td, "2boss.stl"))
        surf = model.load_surf(stl)
        cutter = make_cutter("ball", BALL_DIA, 0.0)
        links = [((cx, 0.0, bh), (0.0, 0.0, top))]
        mode, zr, mx = link_plan(surf, cutter, links, threads=4)[0]
        assert mode == "rapid", "boss link should be rapid, got %s" % mode
        assert abs(zr - (bh + RAPID_MARGIN + RAPID_STOCK_ALLOW)) < 1e-6, \
            "no-stock rapid %.3f != CL+margin+allow %.3f" % (
                zr, bh + RAPID_MARGIN + RAPID_STOCK_ALLOW)
        xs = -q + (np.arange(int(2 * q / cell)) + 0.5) * cell
        ys = -hy + (np.arange(int(2 * hy / cell)) + 0.5) * cell
        X, Y = np.meshgrid(xs, ys)
        stock = hf_two_boss(X, Y, top=top, bx=bx, cx=cx, bh=bh) + 0.381
        ridge = (np.abs(X - cx) <= bx + 1.0) & (np.abs(Y) <= bx + 1.0)
        stock = np.where(ridge, ridge_top, stock)
        k = int(math.ceil(0.5 * BALL_DIA / cell))
        st = (box_max(stock, k), -q, -hy, cell)
        mode2, zr2, _ = link_plan(surf, cutter, links, threads=4, stock=st)[0]
        assert mode2 == "rapid" and zr2 >= ridge_top + RAPID_MARGIN - 1e-6, \
            "rapid z=%.3f does not clear stock ridge %.1f + margin" % (
                zr2, ridge_top)
        mode3, lift3, _ = link_plan(surf, cutter, links, threads=4,
                                   use_rapids=False, stock=st)[0]
        assert mode3 == "lift" and lift3 >= ridge_top + RAPID_MARGIN - 1e-6, \
            "feed lift z=%.3f does not clear stock ridge %.1f + margin" % (
                lift3, ridge_top)
        print("link-plan stock ridge: no-stock %.3f | rapid %.3f | lift %.3f"
              " (ridge %.1f + margin)" % (zr, zr2, lift3, ridge_top))


def test_stock_from_ridge_rapids():
    """S3b item 3: two-boss part + artificial stock ridge 2 mm above the
    boss CL across the link paths; finish(stock_from=...) rapids must lift
    over the ridge (z >= ridge + margin) and zmap (stock_init = the ridge
    field) reports 0 rapid collisions and 0 gouges."""
    q, top, bx, cx, bh = 15.0, 10.0, 2.5, 5.0, 20.0
    hy = 10.0
    ridge_top = bh + 2.0
    with tempfile.TemporaryDirectory() as td:
        stl = two_boss_stl(os.path.join(td, "2boss.stl"))
        surf = model.load_surf(stl)
        Xc, Yc, nx, ny = _grid((-q, q, -hy, hy))
        stock = hf_two_boss(Xc, Yc, top=top, bx=bx, cx=cx, bh=bh) + 0.381
        ridge = (np.abs(Xc - cx) <= bx + 1.0) & (np.abs(Yc) <= bx + 1.0)
        stock = np.where(ridge, ridge_top, stock)
        np.save(os.path.join(td, "stock.npy"), stock)
        with open(os.path.join(td, "stock.json"), "w") as fh:
            json.dump({"x0": -q, "y0": -hy, "cell": CELL}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", BALL_DIA, 0.0),
                             floor_z=top, threads=4,
                             stock_from=os.path.join(td, "stock.npy"))
        assert moves and stats.get("stock_from"), "stock_from not recorded"
        assert stats["n_rapid_links"] >= 1, "no rapid links emitted"
        # footprint-max stock grid (same transform finish applies to links)
        k = int(math.ceil(0.5 * BALL_DIA / CELL))
        bm = box_max(stock, k)

        def stock_along(px, py):
            ii = np.clip(((px + q) / CELL).astype(int), 0, bm.shape[1] - 1)
            jj = np.clip(((py + hy) / CELL).astype(int), 0, bm.shape[0] - 1)
            v = bm[jj, ii]
            v = v[np.isfinite(v)]
            return float(v.max()) if v.size else float("-inf")

        crossed = 0
        for (x0, y0, x1, y1, z) in _rapids(moves):
            m = max(2, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / 0.25))) + 1
            t = np.arange(m) / (m - 1.0)
            px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            smax = stock_along(px, py)
            if smax >= ridge_top - 1e-9:
                crossed += 1
            if smax > -np.inf:
                assert z >= smax + RAPID_MARGIN - 1e-6, \
                    "rapid at %.3f not clear of stock %.3f along path + margin" \
                    % (z, smax)
        assert crossed >= 1, "no rapid crosses the stock ridge"
        text = finish_to_gcode(moves)
        gmv = zmap.parse_gcode(text)
        part = hf_two_boss(Xc, Yc, top=top, bx=bx, cx=cx, bh=bh)
        res = zmap.simulate(gmv, part, CELL, -q, -hy,
                            (-q, q, -hy, hy, 0.0, ridge_top),
                            tool="ball", dia=BALL_DIA, stock_init=stock)
        assert res["rapid_collisions"]["count"] == 0, \
            "stock-ridge rapid collisions at line %s" % \
            res["rapid_collisions"]["first_line"]
        assert res["gouges"]["count"] == 0, \
            "stock-ridge case gouged: %d (max %.3f)" % (
                res["gouges"]["count"], res["gouges"]["max_depth"])
        n_ck, n_bad, mx = clcheck_moves(surf, moves)
        assert n_bad == 0, "stock-ridge clcheck: %d below CL, max %.3f" % (
            n_bad, mx)
        print("stock-ridge: %d/%d rapids cross the ridge (all z>=%.1f), "
              "zmap rapid collisions 0, gouges 0, clcheck 0" % (
                  crossed, stats["n_rapid_links"], ridge_top + RAPID_MARGIN))


# ---------------------------------------------------------------------------
# S4: flute/shank-aware passes (James's tools, tools/x7_tools.json)
# ---------------------------------------------------------------------------

def deep_wall_stl(path, q=15.0, hy=10.0, top=22.0, slot_half=3.5):
    """Block with a straight slot (width 2*slot_half, floor z=0) along Y:
    ~22 mm deep vertical walls (Core Front class)."""
    return slot_boss_stl(path, half_x=q, half_y=hy, top=top,
                         slot_half=slot_half, slot_floor=0.0)


def hf_deep_wall(X, Y, top=22.0, slot_half=3.5):
    return np.where(np.abs(X) < slot_half, 0.0, top)


def test_shank_deep_wall_short_flute():
    """S4 item 3 (real data, S5 update): deep wall (22 mm) + T31 ball 5.958
    F=12 (measured flute from tools/x7_tools.json). Every CL point deeper
    than the flute next to a wall is dropped (the shank, dia = D, would
    touch), split + verified relink; removed points are reported per level
    and every removed level is deeper than the flute below the wall top;
    probe_clcheck stays 0 and zmap sees no gouges (points are only ever
    dropped, never moved down)."""
    q, hy, top = 15.0, 10.0, 22.0
    dia, flute = 5.958, 12.0
    with tempfile.TemporaryDirectory() as td:
        stl = deep_wall_stl(os.path.join(td, "wall.stl"), q, hy, top)
        surf = model.load_surf(stl)
        stats = run_case("deep-wall-T31", stl, hf_deep_wall,
                         (-q, q, -hy, hy), floor_z=0.0, dia=dia)
        assert stats["flute_mm"] == flute, "flute not read from table"
        assert stats["shank_dia_mm"] == dia, "shank not read from table"
        assert stats["n_shank_removed"] > 0, "no shank-blocked points dropped"
        zl = [z for z, n in stats["shank_removed_by_level"]]
        assert max(zl) <= top - flute + SHANK_TOL + 1e-9, \
            "removed points above the flute limit (max z %.2f)" % max(zl)
        # no emitted vertex violates the shank rule anymore
        moves, _ = finish(surf, stl_path=stl, tool=("ball", dia, 0.0),
                         floor_z=0.0, threads=4)
        pts = [(mv["x"], mv["y"], mv["z"]) for mv in moves
               if mv["g"] == 1 and mv.get("z") is not None]
        cyl = batch_drop(surf, make_cutter("flat", dia + 2 * SHANK_TOL),
                        [(p[0], p[1]) for p in pts], threads=4)
        zv = np.array([p[2] for p in pts])
        n_viol = int((np.isfinite(cyl)
                      & (cyl > zv + flute - SHANK_TOL)).sum())
        assert n_viol == 0, "%d emitted vertices still shank-blocked" % n_viol
        print("deep-wall T31 D=5.958 F=12: removed=%d (levels %.2f..%.2f, "
              "wall=%.0fmm2), 0 remaining violations"
              % (stats["n_shank_removed"], min(zl), max(zl),
                 stats["removed_wall_mm2"]))


def test_shank_deep_wall_long_flute():
    """S4 item 3 (real data, S5 update): same 22 mm wall with T20 ball
    9.525, measured flute 22.225 >= wall depth - nothing is dropped; the
    holder (stick-out 46.2, nose >= 46.2 > wall top 22) drops nothing
    either; clcheck (ball 9.525) 0."""
    q, hy, top = 15.0, 10.0, 22.0
    with tempfile.TemporaryDirectory() as td:
        stl = deep_wall_stl(os.path.join(td, "wall.stl"), q, hy, top)
        surf = model.load_surf(stl)
        stats = run_case("deep-wall-95", stl, hf_deep_wall,
                         (-q, q, -hy, hy), floor_z=0.0, dia=9.525)
        assert stats["flute_mm"] == 22.225, "flute not read from table"
        assert stats["n_shank_removed"] == 0, \
            "long flute dropped %d points" % stats["n_shank_removed"]
        assert stats.get("n_holder_removed", 0) == 0, \
            "holder dropped %d points (nose >= 46.2 > wall top 22)" % \
            stats["n_holder_removed"]
        print("deep-wall D=9.525 F=22.225: 0 points dropped (kept)")


def test_rest_pass_table_tool():
    """S4 item 2 (real data, S5 update): corner rest pass with --rest-tool
    ball:3.142 (T33, 1/8 in measured, IN tools/x7_tools.json): no
    PLACEHOLDER marker, flute 6.35 + shank 3.142 read from the table, rest
    cells reported clean vs shank-blocked, and clcheck (ball 3.142) 0."""
    q, hy, top, slot_half, slot_floor = 15.0, 10.0, 10.0, 2.0, 4.0
    with tempfile.TemporaryDirectory() as td:
        stl = slot_boss_stl(os.path.join(td, "slot.stl"))
        surf = model.load_surf(stl)
        X, Y, nx, ny = _grid((-q, q, -hy, hy))
        stock = np.full(X.shape, top + 0.381)
        np.save(os.path.join(td, "stock.npy"), stock)
        with open(os.path.join(td, "stock.json"), "w") as fh:
            json.dump({"x0": -q, "y0": -hy, "cell": CELL}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 3.142, 0.0),
                             floor_z=slot_floor, threads=4,
                             rest_from=os.path.join(td, "stock.npy"),
                             big_tool=("ball", 6.0, 0.0), min_rest=0.5)
        assert moves and stats.get("rest_pass")
        assert not stats["placeholder_tool"], \
            "ball:3.142 is in tools/x7_tools.json - not a placeholder"
        assert stats["flute_mm"] == 6.35 and stats["shank_dia_mm"] == 3.142
        assert stats["n_rest_cells"] > 0, "empty rest mask"
        assert (stats["n_rest_clean"] + stats["n_rest_shank_blocked"]
                == stats["n_rest_cells"])
        print("rest-pass ball:3.142: cells=%d clean=%d shank-blocked=%d"
              % (stats["n_rest_cells"], stats["n_rest_clean"],
                 stats["n_rest_shank_blocked"]))
        n_ck, n_bad, mx = clcheck_moves(surf, moves, dia=3.142)
        assert n_bad == 0, "rest-pass clcheck: %d below CL, max %.3f" % (
            n_bad, mx)



def test_shank_net_keeps_source_index():
    """A path split by the shank net keeps its source index, so per-row bookkeeping
    (row_of / run_i0 for serpentine ordering) stays aligned (Core Front 6 mm crash)."""
    import numpy as np
    from engine import finish as F
    paths = [[(0, 0, 1.0), (1, 0, 1.0), (2, 0, 1.0), (3, 0, 1.0), (4, 0, 1.0)],
             [(0, 1, 1.0), (1, 1, 1.0)]]
    orig = F.batch_drop
    F.batch_drop = lambda surf, cut, xy, threads=None: np.array(
        [1.0, 1.0, 50.0, 1.0, 1.0, 1.0, 1.0])
    try:
        out, bl, ar, src = F.shank_net(None, paths, 6.0, 15.0)
    finally:
        F.batch_drop = orig
    assert [len(p) for p in out] == [2, 2, 2] and src == [0, 0, 1], (out, src)

# ---------------------------------------------------------------------------
# S5: holder clearance (real stick-out + holder frustum stacks from the table)
# ---------------------------------------------------------------------------

def boss_slot_stl(path, q=15.0, hy=10.0, top=10.0, slot_half=3.5,
                  cx=9.0, R=3.0, bh=24.0, n=96):
    """Block with a slot (|x| < slot_half, floor z=0) along Y, plate top
    `top`, plus a tall cylinder boss (axis (cx, 0), radius R) up to z=bh.
    The boss face at x = cx - R = 6 mm is out of reach of the shank (r ~3)
    of a tool riding the slot, but well inside the BT30-ER20-60 holder
    envelope - only the HOLDER touches (task S5 item 4)."""
    tris = _box(-q, -slot_half, -hy, hy, 0.0, top)
    tris += _box(slot_half, q, -hy, hy, 0.0, top)
    tris.append(((-slot_half, -hy, 0.0), (slot_half, -hy, 0.0),
                 (slot_half, hy, 0.0), (0, 0, 1)))
    tris.append(((-slot_half, -hy, 0.0), (slot_half, hy, 0.0),
                 (-slot_half, hy, 0.0), (0, 0, 1)))

    def ring(k, z):
        th = 2.0 * math.pi * k / n
        return (cx + R * math.cos(th), R * math.sin(th), z)

    for k in range(n):
        a, b = ring(k, top), ring((k + 1) % n, top)
        a2, b2 = ring(k, bh), ring((k + 1) % n, bh)
        ref = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0,
               (top + bh) / 2.0)
        tris.append((a, b, b2, ref))
        tris.append((a, b2, a2, ref))
    for k in range(n):
        tris.append(((cx, 0.0, bh), ring(k, bh), ring((k + 1) % n, bh),
                     (0.0, 0.0, 1.0)))
    return write_stl(path, tris)


def hf_boss_slot(X, Y, top=10.0, slot_half=3.5, cx=9.0, R=3.0, bh=24.0):
    part = np.where(np.abs(X) < slot_half, 0.0, top)
    return np.where(np.hypot(X - cx, Y) <= R, bh, part)


def test_holder_drop_tall_boss():
    """S5 item 4: tall boss beside a deep pocket - the HOLDER (not the
    shank) touches. Ball 5.958 = T31 (flute 12, stick-out 18, holder
    BT30-ER20-60 read from the table): slot-floor points (tip z=0, nose
    z=18) see the 24 mm boss within the holder envelope -> dropped, split +
    verified relink. The slot-floor level (z=0) is dropped by the HOLDER
    ONLY: within shank radius the highest material is the 10 mm slot wall,
    below tip + flute = 12 (the S4 rule keeps it). The shank net only drops
    plate-top points next to the boss (24 > 10 + 12), at levels >= 10.
    Points with nose >= 28 > 24 (tip >= 10 away from the boss) are kept.
    No emitted vertex still violates the envelope, and zmap's INDEPENDENT
    holder check on the emitted program counts 0 hits."""
    q, hy, top, bh = 15.0, 10.0, 10.0, 24.0
    dia = 5.958
    stickout, hold_name = 18.0, "BT30-ER20-60"
    with tempfile.TemporaryDirectory() as td:
        stl = boss_slot_stl(os.path.join(td, "bslot.stl"), q, hy, top)
        surf = model.load_surf(stl)
        stats = run_case("boss-slot", stl, hf_boss_slot,
                         (-q, q, -hy, hy), floor_z=0.0, dia=dia,
                         extra_calls=2)  # holder nets (steep + shallow)
        assert stats["flute_mm"] == 12.0, "flute not read from table"
        assert stats["shank_dia_mm"] == 5.958, "shank not read from table"
        assert stats["stickout_mm"] == 18.0, "stick-out not read from table"
        assert stats["holder"] == hold_name
        assert stats["n_holder_removed"] > 0, "no holder-blocked points"
        zs_h = dict((z, n) for z, n in stats["holder_removed_by_level"])
        assert zs_h.get(0.0, 0) > 0, \
            "slot-floor level not holder-dropped: %s" % (zs_h,)
        zs_s = [z for z, n in stats["shank_removed_by_level"]]
        assert not zs_s or min(zs_s) >= top - SHANK_TOL, \
            "shank dropped slot-floor points (wall 10 < tip+flute 12): %s" \
            % (min(zs_s),)
        zh = [z for z, n in stats["holder_removed_by_level"]]
        assert max(zh) <= bh - stickout + SHANK_TOL + 1e-9, \
            "holder-dropped point above the nose limit (max z %.2f)" % max(zh)
        print("boss-slot: holder dropped %d (levels %.2f..%.2f, wall=%.0fmm2)"
              " shank dropped %d"
              % (stats["n_holder_removed"], min(zh), max(zh),
                 stats["holder_removed_wall_mm2"], stats["n_shank_removed"]))
        # no emitted vertex violates the conservative holder envelope
        moves, _ = finish(surf, stl_path=stl, tool=("ball", dia, 0.0),
                         floor_z=0.0, threads=4)
        pts = [(mv["x"], mv["y"], mv["z"]) for mv in moves
               if mv["g"] == 1 and mv.get("z") is not None]
        max_r = max(max(s[2], s[3]) for s in holder_segments(hold_name))
        cyl = batch_drop(surf, make_cutter("flat", 2.0 * (max_r + 1.0)),
                        [(p[0], p[1]) for p in pts], threads=4)
        zv = np.array([p[2] for p in pts])
        n_viol = int((np.isfinite(cyl) & (cyl > zv + stickout)).sum())
        assert n_viol == 0, "%d emitted vertices still holder-blocked" % n_viol
        # independent zmap holder check on the emitted program: 0 hits
        text = finish_to_gcode(moves)
        gmv = zmap.parse_gcode(text)
        X, Y, nx, ny = _grid((-q, q, -hy, hy))
        part = hf_boss_slot(X, Y, top=top)
        zsegs, zst, zname = zmap.resolve_holder(tool_number=31)
        assert (zname, zst) == (hold_name, stickout)
        res = zmap.simulate(gmv, part, CELL, -q, -hy,
                            (-q, q, -hy, hy, 0.0, bh), tool="ball", dia=dia,
                            stock_init=np.minimum(bh, part + 0.381),
                            holder=zsegs, stickout=zst)
        assert res["holder_hits"]["count"] == 0, \
            "zmap still counts %d holder hits (worst %s, %.3f mm)" % (
                res["holder_hits"]["count"], res["holder_hits"]["worst_xy"],
                res["holder_hits"]["max_intrusion"])
        print("boss-slot: zmap holder_hits 0 on the emitted program")


def stock_ridge_pocket_stl(path, q=40.0, hy=20.0, top=10.0,
                          pocket_half=6.0, floor_z=0.0):
    """Plate [-q,q]x[-hy,hy] top `top` with a full-X deep pocket
    (|y| < pocket_half, floor floor_z, vertical walls)."""
    tris = _box(-q, q, -hy, -pocket_half, floor_z, top)
    tris += _box(-q, q, pocket_half, hy, floor_z, top)
    tris += _box(-q, q, -pocket_half, pocket_half, floor_z - 5.0, floor_z)
    return write_stl(path, tris)


def hf_stock_ridge_pocket(X, Y, top=10.0, pocket_half=6.0, floor_z=0.0):
    return np.where(np.abs(Y) < pocket_half, floor_z, top)


def ridge_stock_npy(path, q=40.0, hy=20.0, cell=0.5, top=10.0,
                   pocket_half=6.0, rx=4.0, ry0=6.0, ry1=11.0, ridge_z=24.0):
    """Post-roughing stock heightfield (engine .npy + sidecar): part + axial
    leave everywhere, plus a leftover ridge (rx x [ry0,ry1]) standing at
    ridge_z above the plate top - stock roughing could not reach."""
    nx = int(round(2 * q / cell))
    ny = int(round(2 * hy / cell))
    cx = -q + (np.arange(nx) + 0.5) * cell
    cy = -hy + (np.arange(ny) + 0.5) * cell
    CX, CY = np.meshgrid(cx, cy)
    A = np.where(np.abs(CY) < pocket_half, 0.381, top + 0.381)
    A = np.where((np.abs(CX) <= rx) & (CY >= ry0) & (CY <= ry1),
                ridge_z, A)
    np.save(path, A)
    with open(path[:-4] + ".json", "w") as fh:
        json.dump({"x0": -q, "y0": -hy, "cell": cell}, fh)


def test_holder_stock_ridge_along_path():
    """Task HN: the engine holder net must be at least as conservative as
    zmap. Deep pocket (floor z=0, PART walls only 10 mm high) with a
    roughing STOCK ridge (z=24) along the pocket wall. Ball 5.958 = T31
    (stick-out 18, holder BT30-ER20-60): on the pocket floor the holder
    clears the PART (nose z=18 > wall top 10) - only the remaining STOCK
    violates: nose 18 < ridge 24 within the envelope radius 23 + 1 mm.
    The floor rows are long straight chords whose ENDPOINTS sit clear of
    the ridge while the row INTERIOR passes within the envelope: a
    vertex-only net keeps the row whole, but zmap samples along every
    cutting move and counts holder hits there. The along-outline net must
    drop the near-ridge samples (split, relink verified - links crossing
    the ridge zone escalate to rapids), so zmap counts 0 holder_hits on
    the emitted program; points are dropped, never lowered."""
    q, hy, top, bh = 40.0, 20.0, 10.0, 24.0
    dia = 5.958
    stickout, hold_name = 18.0, "BT30-ER20-60"
    with tempfile.TemporaryDirectory() as td:
        stl = stock_ridge_pocket_stl(os.path.join(td, "srp.stl"), q, hy, top)
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock_rough.npy")
        ridge_stock_npy(stockp, q, hy)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", dia, 0.0),
                             floor_z=0.0, threads=4, stock_from=stockp)
        assert stats.get("stock_from"), "stock_from not recorded"
        assert stats["holder"] == hold_name and stats["stickout_mm"] == 18.0
        zs_h = dict((z, n) for z, n in stats["holder_removed_by_level"])
        assert zs_h.get(0.0, 0) > 0, \
            "floor points beside the stock ridge not holder-dropped: %s" % \
            (zs_h,)
        zh = [z for z, n in stats["holder_removed_by_level"]]
        assert max(zh) <= bh - stickout + SHANK_TOL + 1e-9, \
            "holder-dropped point above the nose limit (max z %.2f)" % max(zh)
        print("stock-ridge: holder dropped %d (levels %.2f..%.2f, wall=%.0fmm2)"
              % (stats["n_holder_removed"], min(zh), max(zh),
                 stats["holder_removed_wall_mm2"]))
        # independent zmap judgement (stock_init = the same ridge model)
        text = finish_to_gcode(moves)
        gmv = zmap.parse_gcode(text)
        X, Y, nx, ny = _grid((-q, q, -hy, hy))
        part = hf_stock_ridge_pocket(X, Y, top=top)
        ridge = (np.abs(X) <= 4.0) & (Y >= 6.0) & (Y <= 11.0)
        stock_init = np.where(ridge, bh, np.minimum(bh, part + 0.381))
        zsegs, zst, zname = zmap.resolve_holder(tool_number=31)
        assert (zname, zst) == (hold_name, stickout)
        res = zmap.simulate(gmv, part, CELL, -q, -hy,
                            (-q, q, -hy, hy, 0.0, bh), tool="ball", dia=dia,
                            stock_init=stock_init, holder=zsegs, stickout=zst)
        assert res["holder_hits"]["count"] == 0, \
            "zmap still counts %d holder hits (worst %s, %.3f mm)" % (
                res["holder_hits"]["count"], res["holder_hits"]["worst_xy"],
                res["holder_hits"]["max_intrusion"])
        assert res["gouges"]["count"] == 0, \
            "%d gouges, max %.3f at %s" % (res["gouges"]["count"],
                                           res["gouges"]["max_depth"],
                                           res["gouges"]["worst_xy"])
        assert res["rapid_collisions"]["count"] == 0, \
            "rapid collisions at line %s" % res["rapid_collisions"]["first_line"]
        print("stock-ridge: zmap holder_hits 0, gouges 0, rapids clean")


def test_shank_t31_wall_13mm():
    """S5 item 4 (real flute): T31 (ball 5.958, flute 12) next to a
    vertical wall 13 mm deep -> points within shank radius of the wall with
    tip deeper than 13 - 12 = 1 mm are dropped (S4 rule unchanged); the
    holder (nose >= tip + 18 > wall top 13) drops nothing: n_holder_removed
    == 0, and no emitted vertex still breaks the shank rule."""
    q, hy, top = 15.0, 10.0, 13.0
    dia = 5.958
    with tempfile.TemporaryDirectory() as td:
        stl = deep_wall_stl(os.path.join(td, "wall.stl"), q, hy, top)
        surf = model.load_surf(stl)
        stats = run_case("wall13-T31", stl,
                        lambda X, Y: hf_deep_wall(X, Y, top=top),
                        (-q, q, -hy, hy), floor_z=0.0, dia=dia,
                        extra_calls=2)  # holder nets run but drop nothing
        assert stats["flute_mm"] == 12.0 and stats["shank_dia_mm"] == 5.958
        assert stats["stickout_mm"] == 18.0
        assert stats["n_shank_removed"] > 0, \
            "wall 13 mm deep > flute 12: nothing dropped"
        zl = [z for z, n in stats["shank_removed_by_level"]]
        assert max(zl) <= top - 12.0 + SHANK_TOL + 1e-9, \
            "removed points above the flute limit (max z %.2f)" % max(zl)
        assert stats["n_holder_removed"] == 0, \
            "holder dropped %d points though nose >= 18 > wall top 13" % \
            stats["n_holder_removed"]
        moves, _ = finish(surf, stl_path=stl, tool=("ball", dia, 0.0),
                         floor_z=0.0, threads=4)
        pts = [(mv["x"], mv["y"], mv["z"]) for mv in moves
               if mv["g"] == 1 and mv.get("z") is not None]
        cyl = batch_drop(surf, make_cutter("flat", dia + 2 * SHANK_TOL),
                        [(p[0], p[1]) for p in pts], threads=4)
        zv = np.array([p[2] for p in pts])
        n_viol = int((np.isfinite(cyl) & (cyl > zv + 12.0 - SHANK_TOL)).sum())
        assert n_viol == 0, "%d emitted vertices still shank-blocked" % n_viol
        print("wall13 T31: shank dropped=%d (levels %.2f..%.2f), holder 0, "
              "0 remaining violations" % (stats["n_shank_removed"], min(zl),
                                         max(zl)))


def test_ramp_vertices_never_below_verified_path():
    """FE5: every emitted ramp vertex z must be >= the verified path CL z at
    its own arc position (max(vertex z, z0 + s*tan)); a ramp vertex below
    the verified path would be an unverified, gouge-risk CL point."""
    from engine.finish import _ramp_entry
    n = 40
    xs = np.arange(n) * 0.7
    ys = np.sin(np.arange(n) * 0.55) * 3.0
    zs = 5.0 - 0.08 * xs + 0.4 * np.cos(np.arange(n) * 1.3)
    P = np.stack([xs, ys, zs], axis=1)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs),
                                                   np.diff(ys)))])
    tan = math.tan(math.radians(2.0))
    for depth in (0.3, 1.7, 60.0):        # full ramp and short-run cases
        u = min(depth / tan, float(s[-1]))
        rv = _ramp_entry(P, s, tan, u)
        assert rv, "empty ramp"
        z0 = float(P[0, 2])
        # last ramp vertex is the pass start itself
        assert math.dist(rv[-1], (float(P[0, 0]), float(P[0, 1]), z0)) \
            < 1e-9, rv[-1]
        for (x, y, z) in rv:
            # arc position of this point on the verified pass: own vertex
            # (exact XY match) or the interpolated vertex at s = u
            d = np.hypot(P[:, 0] - x, P[:, 1] - y)
            i = int(np.argmin(d))
            sp = float(s[i]) if d[i] < 1e-6 else u
            verified_z = float(np.interp(sp, s, P[:, 2]))
            assert z >= verified_z - 1e-9, \
                "ramp vertex z %.4f below verified path z %.4f at s %.2f" \
                % (z, verified_z, sp)
            assert z >= min(z0 + sp * tan, verified_z) - 1e-9


def test_fe5e_ramp_top_clear_of_ridge():
    """FE5e: a shallow entry (live depth 0.3 at P0) whose FE5 ramp top
    (s = d/tan ~ 8.6 mm along) lands UNDER a standing ridge (stock 2.0 mm
    above the top - the line-52593 case). _fe5_pick_ramp must return the
    SMALLEST longer L whose ramp top is clear (live disk_depth <= 0.25,
    which also clears the link's vertical descent column onto rv[0]: depth
    only grows downward), and (None, False) - reported unresolved - when no
    L on the run clears. Fails on e40f664's code: there L = d/tan only and
    the top stays buried (and the helper does not exist)."""
    from engine.finish import _fe5_pick_ramp, _ramp_entry, RAMP_TRIGGER
    from engine.entry_depth import LiveStock
    cell, x0, y0 = 0.5, -15.0, -5.0
    xs = x0 + (np.arange(100) + 0.5) * cell   # to x = 34.75
    ys = y0 + (np.arange(20) + 0.5) * cell
    X, Y = np.meshgrid(xs, ys)
    A = np.full(X.shape, 10.0)
    A[(X >= -4.0) & (X <= 2.0) & (np.abs(Y) <= 1.5)] = 12.0
    tan = math.tan(math.radians(2.0))
    n = 9                                     # x -10..30, 5 mm chords, flat z
    P = np.stack([-10.0 + np.arange(n) * 5.0, np.zeros(n),
                  np.full(n, 9.7)], axis=1)
    s = np.arange(n) * 5.0
    live = LiveStock(A, x0, y0, cell, 3.0)
    d = live.disk_depth(P[0, 0], P[0, 1], 9.7)
    assert RAMP_TRIGGER < d <= 0.5, "P0 must be shallow, got %.3f" % d
    L0 = d / tan
    # today's top (s = L0) is buried under the ridge: the FE5d defect
    ox = float(np.interp(L0, s, P[:, 0]))
    oz = max(float(np.interp(L0, s, P[:, 2])), 9.7 + L0 * tan)
    assert live.disk_depth(ox, 0.0, oz) > RAMP_TRIGGER, \
        "test shape must bury the FE5 top"
    L, flip = _fe5_pick_ramp(live, P, s, tan)
    assert L is not None and not flip and L0 < L <= float(s[-1]), (L, flip)
    top = _ramp_entry(P, s, tan, L)[0]
    assert live.disk_depth(top[0], top[1], top[2]) <= RAMP_TRIGGER, \
        "FE5e ramp top/descent column not clear: %s" % (top,)
    # ridge over the whole run (+ ball margin): no L clears -> unresolved
    A2 = np.full(X.shape, 10.0)
    A2[X >= -13.5] = 12.0
    live2 = LiveStock(A2, x0, y0, cell, 3.0)
    L2, flip2 = _fe5_pick_ramp(live2, P, s, tan)
    assert L2 is None and not flip2, (L2, flip2)
    print("fe5e ridge: d=%.3f L0=%.1f -> L=%.1f clear; all-ridge unresolved"
          % (d, L0, L))


def test_fe5t_public_ramp_top_clear_of_ridge():
    """FE5e-t: BEHAVIOURAL test through the PUBLIC finish() path. Small
    synthetic flat block (floor_z 6.0) with --stock-from live stock: a
    shallow entry shelf (leave 0.3 -> live depth ~0.3 at the first row's
    P0, over the RAMP_TRIGGER) whose FE5 ramp sized from P0 only
    (L = d/tan ~ 8.6 mm) lands its TOP (first ramp vertex) UNDER the
    standing leftover ridge (stock 7.0 -> ~0.7 deep > 0.25) - the
    line-52593 defect at program level. e40f664 emits exactly that buried
    top and has no fe5_top_unresolved stat; FE5e (44e0a61) must pick the
    SMALLEST longer L whose top is clear (or enter from the other end, or
    report the entry). Assert on the EMITTED moves: replay the estimator's
    LiveStock in emit order and require every entry landing strictly above
    the floor - the bottom of a vertical descent (plunge onto a ramp top)
    or a horizontal arrival at ramp height - to have live depth <= 0.25 or
    appear in stats fe5_top_unresolved. Ramp chord vertices below their top
    are sloped moves and stay excluded (allowed, FE5e rule 4). Must FAIL
    BY ASSERTION on e40f664's engine and PASS on 44e0a61."""
    from engine.finish import finish, RAMP_TRIGGER
    from engine.entry_depth import LiveStock, load_heightfield
    cell = 0.5
    bx0, bx1, by0, by1 = -15.0, 15.0, -12.0, 12.0
    floor_z, base, shelf, ridge = 6.0, 6.2, 6.3, 7.0
    with tempfile.TemporaryDirectory() as td:
        stl = write_stl(os.path.join(td, "fe5t_block.stl"),
                        _box(bx0, bx1, by0, by1, 0.0, floor_z))
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock.npy")
        # grid extends 4 mm past the block: a disk centered exactly on the
        # block edge must read finite stock (an off-grid window is inf and
        # would flag safe-height traversals as buried)
        gx0, gx1, gy0, gy1 = bx0 - 4.0, bx1 + 4.0, by0 - 4.0, by1 + 4.0
        nx = int(round((gx1 - gx0) / cell))
        ny = int(round((gy1 - gy0) / cell))
        CX, CY = np.meshgrid(gx0 + (np.arange(nx) + 0.5) * cell,
                              gy0 + (np.arange(ny) + 0.5) * cell)
        A = np.full(CX.shape, base)
        A[CX <= -9.0] = shelf                  # shallow entry: d(P0) ~ 0.3
        A[(CX >= -8.0) & (CX <= -4.0)] = ridge  # standing leftover ridge
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 6.0, 0.0),
                              stepover=1.5, floor_z=floor_z, threads=4,
                              stock_from=stockp, ramp_angle_deg=2.0)
        assert moves and stats.get("stock_from"), "stock_from not recorded"
        n_ramp = stats.get("n_entries_ramped", 0) + \
            stats.get("n_entries_short_run", 0)
        assert n_ramp >= 1, "no ramped entry - the ridge scenario is gone"
        unresolved = [tuple(r[:3]) for r in
                     stats.get("fe5_top_unresolved", [])]
        A0, sx0, sy0, c0 = load_heightfield(stockp)
        live = LiveStock(A0, sx0, sy0, c0, 3.0)

        def listed(x, y):
            return any(math.hypot(x - ux, y - uy) <= 1.5
                       for ux, uy, _ in unresolved)

        buried = []
        prev = None
        for m in moves:
            x, y, z = m["x"], m["y"], m["z"]
            if prev is not None:
                px, py, pz = prev
                if m["g"] == 1:
                    if z > floor_z + 0.05:
                        vert = abs(x - px) <= 1e-9 and abs(y - py) <= 1e-9
                        horiz = abs(z - pz) <= 1e-9 and (abs(x - px) > 1e-9
                                                        or abs(y - py) > 1e-9)
                        if (vert and z < pz - 1e-9) or horiz:
                            dd = live.disk_depth(x, y, z)
                            if dd > RAMP_TRIGGER + 1e-9 and not listed(x, y):
                                buried.append((round(x, 2), round(y, 2),
                                             round(z, 3), round(dd, 3)))
                    live.stamp_chord(prev, (x, y, z))
            prev = (x, y, z)
        assert not buried, \
            "FE5e-t: %d buried ramp top/entry landing (max depth %.3f): %s" \
            % (len(buried), max(b[3] for b in buried), buried[:4])
        print("fe5t public: %d entries ramped, %d unresolved, tops clear "
              "(chord max depth %.3f)"
              % (n_ramp, len(unresolved),
                 stats.get("fe5_chord_max_depth_max", float("nan"))))


def floor_dip_stl(path, half_x=15.0, half_y=10.0, top=10.0, slot_half=6.0,
                  deep_z=2.0, shelf_z=7.0, step_y=4.0):
    """Block with a slot along Y (walls at x=+-slot_half, mouth at z=top):
    floor at deep_z for |y| < step_y (BELOW the requested floor_z) and at
    shelf_z > floor_z outside - the FL1 dip: passes must split at the dip,
    never feed below the floor and never be dropped wholesale."""
    tris = []
    tris += _box(-half_x, -slot_half, -half_y, half_y, 0.0, top)
    tris += _box(slot_half, half_x, -half_y, half_y, 0.0, top)
    tris += _box(-slot_half, slot_half, step_y, half_y, 0.0, shelf_z)
    tris += _box(-slot_half, slot_half, -half_y, -step_y, 0.0, shelf_z)
    tris += _box(-slot_half, slot_half, -step_y, step_y, 0.0, deep_z)
    return write_stl(path, tris)


def test_fe5fc_degenerate_pass_never_plunged():
    """FE5fc (supervisor): a ONE-POINT pass and a ZERO-LENGTH pass whose live
    depth exceeds the ball floor 0.5 must be SKIPPED and reported, never
    linked-to and plunged (the T33 chain's 1.06 mm straight plunge at
    (-23.64, 1.68)). The two passes are injected into finish()'s own steep
    pass list (floor_net wrapper, steep call) over the hill scene's +2.0 mm
    buried stock, away from every real pass. Asserts: fe5_skipped_n grows by
    exactly 2 vs the same run without injection, each point is in a skip
    cluster with max depth > 0.5, and no move reaches either injected XY at
    or below its z. Must FAIL BY ASSERTION with the old plunge path (1f499f5:
    degenerate passes bypass every FE5e/FE5f check)."""
    from engine import finish as _fmod
    from engine.finish import finish
    cell = 0.5
    INJ = [[(-11.13, 2.37, 10.0)], [(11.27, -2.41, 10.0), (11.27, -2.41, 10.0)]]

    def surfz(x):
        if x <= -8 or x >= 8:
            return 10.0
        if x < -2:
            return 10.0 + 3.0 * (x + 8) / 6.0
        if x > 2:
            return 13.0 - 3.0 * (x - 2) / 6.0
        return 13.0

    with tempfile.TemporaryDirectory() as td:
        prof = [(-14, 0), (14, 0), (14, 10), (8, 10), (2, 13), (-2, 13),
                (-8, 10), (-14, 10)]
        stl = _prism_stl(os.path.join(td, "hill.stl"), prof, -6.0, 6.0)
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock.npy")
        gx0, gy0 = -20.0, -10.0
        CX, _CY = np.meshgrid(gx0 + (np.arange(80) + 0.5) * cell,
                              gy0 + (np.arange(40) + 0.5) * cell)
        A = np.vectorize(lambda x: surfz(x) + (2.0 if abs(x) >= 8 else 0.3))(CX)
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        kw = dict(stl_path=stl, tool=("ball", 6.0, 0.0), stepover=1.5,
                  floor_z=5.0, threads=4, stock_from=stockp,
                  ramp_angle_deg=2.0)
        _m0, st0 = finish(surf, **kw)
        orig = _fmod.floor_net
        calls = []

        def inject(paths, src, *a, **k):
            out = orig(paths, src, *a, **k)
            calls.append(1)
            if len(calls) == 1:            # the steep call (first in finish)
                out = (list(out[0]) + [list(p) for p in INJ],
                       list(out[1]) + [0] * len(INJ), out[2])
            return out

        _fmod.floor_net = inject
        try:
            moves, st = finish(surf, **kw)
        finally:
            _fmod.floor_net = orig
        assert len(calls) >= 1, "floor_net wrapper never called"
        dn = st.get("fe5_skipped_n", 0) - st0.get("fe5_skipped_n", 0)
        assert dn == 2, "degenerate deep passes not skipped: skipped %d -> " \
            "%d (expected +2)" % (st0.get("fe5_skipped_n", 0),
                                  st.get("fe5_skipped_n", 0))
        cls = st.get("fe5_skipped_clusters") or []
        for p in INJ:
            x, y, z = p[0]
            near = [c for c in cls if c["bbox"][0] - 1e-3 <= x <= c["bbox"][1]
                    + 1e-3 and c["bbox"][2] - 1e-3 <= y <= c["bbox"][3] + 1e-3]
            assert near and any((c["max_depth_mm"] or 0) > 0.5 for c in near), \
                "injected (%.1f, %.1f) not reported deeper than 0.5: %s" % (
                    x, y, near)
            hit = [m for m in moves if abs(m["x"] - x) < 1e-3
                   and abs(m["y"] - y) < 1e-3 and m["z"] <= z + 1e-6]
            assert not hit, "injected pass at (%.1f, %.1f) was emitted " \
                "(plunged to z %.3f)" % (x, y, hit[0]["z"])
    print("PASS fe5fc degenerate passes: one-point + zero-length deep passes "
          "skipped and clustered (+%d), none emitted" % dn)


def test_floor_dip_split_finish_and_rest():
    """FL1: part surface dips below floor_z (deep slot floor z=2 <
    floor_z=5; shelf z=7 stays above). In BOTH the finish and the rest
    pass no feed move may run below the floor, points above the floor must
    still be cut (pass split at the dip, not dropped wholesale), and
    n_floor_dropped > 0. Fails on main's code: floor_z was only the steep
    waterline bottom, so shallow rows crossed the dip at z=2."""
    floor_z = 5.0
    with tempfile.TemporaryDirectory() as td:
        stl = floor_dip_stl(os.path.join(td, "dip.stl"))
        surf = model.load_surf(stl)
        X, Y, nx, ny = _grid((-15.0, 15.0, -10.0, 10.0))
        stock = np.full(X.shape, 10.381)
        np.save(os.path.join(td, "stock.npy"), stock)
        with open(os.path.join(td, "stock.json"), "w") as fh:
            json.dump({"x0": -15.0, "y0": -10.0, "cell": CELL}, fh)
        cases = (("finish", dict(tool=("ball", 6.0, 0.0))),
                 ("rest", dict(tool=("ball", 3.0, 0.0),
                              rest_from=os.path.join(td, "stock.npy"),
                              big_tool=("ball", 6.0, 0.0), min_rest=0.5)))
        for name, kw in cases:
            moves, stats = finish(surf, stl_path=stl, floor_z=floor_z,
                                  threads=4, **kw)
            # inside the part bbox (outside it the raster pads half a
            # stepover: stock-edge air passes, not governed by floor_z)
            feed = [(mv["x"], mv["y"], mv["z"]) for mv in moves
                    if mv["g"] == 1 and mv.get("z") is not None
                    and abs(mv["x"]) <= 15.0 and abs(mv["y"]) <= 10.0]
            assert feed, "%s: no feed moves" % name
            below = [t for t in feed if t[2] < floor_z - 1e-6]
            assert not below, \
                "%s: %d feed moves below floor_z (min %.3f)" % (
                    name, len(below), min(t[2] for t in below))
            assert stats.get("n_floor_dropped", 0) > 0, \
                "%s: n_floor_dropped=0 (dip never reached / no split)" % name
            # split, not wholesale: the shelf above the floor is still cut
            kept = [t for t in feed if abs(t[0]) < 5.0 and abs(t[1]) > 4.5
                    and abs(t[2] - 7.0) < 0.25]
            assert kept, "%s: nothing kept on the shelf above the dip" % name
            print("floor-dip %s: feed=%d minz=%.3f dropped=%d kept_shelf=%d"
                  % (name, len(feed), min(t[2] for t in feed),
                     stats["n_floor_dropped"], len(kept)))


def two_step_stl(path, half_x=6.0, half_y=4.0, top=10.0, low_z=3.0):
    """Block with a step down along Y: tall slab y in [-half_y, 0] up to
    top, low slab y in [0, half_y] up to low_z (below the requested
    floor_z) - the FL1b shape: the raster pad rows just past y=half_y roll
    off the LOW step edge at CL ~low_z, between the part bbox and the
    stock box where stock stands."""
    tris = []
    tris += _box(-half_x, half_x, -half_y, 0.0, 0.0, top)
    tris += _box(-half_x, half_x, 0.0, half_y, 0.0, low_z)
    return write_stl(path, tris)


def test_floor_pad_rows_inside_stock_box():
    """FL1b: part bbox (+-6 x +-4) smaller than the stock box (+-12 x +-8).
    The raster's pad row at y=half_y+0.1 rides the low step edge (z~3)
    BELOW floor_z=5 - inside the stock box, so it cuts stock the floor
    forbids: it must be DROPPED (FL1's bbox exemption is tightened to
    outside stock_box + tool radius). Fails on main's code: FL1 exempted
    every vertex outside the part bbox, so this pad row survived as feed
    moves below floor_z inside the stock box."""
    floor_z = 5.0
    q, hy, top, low = 6.0, 4.0, 10.0, 3.0
    sq, shy = 12.0, 8.0  # stock box: strictly bigger than the part bbox
    with tempfile.TemporaryDirectory() as td:
        stl = two_step_stl(os.path.join(td, "step.stl"), q, hy, top, low)
        surf = model.load_surf(stl)
        X, Y, nx, ny = _grid((-sq, sq, -shy, shy))
        stock = np.full(X.shape, top + 0.381)
        np.save(os.path.join(td, "stock.npy"), stock)
        with open(os.path.join(td, "stock.json"), "w") as fh:
            json.dump({"x0": -sq, "y0": -shy, "cell": CELL}, fh)
        cases = (("finish", dict(tool=("ball", 6.0, 0.0),
                                  stock_from=os.path.join(td, "stock.npy"))),
                 ("rest", dict(tool=("ball", 3.0, 0.0),
                               rest_from=os.path.join(td, "stock.npy"),
                               big_tool=("ball", 6.0, 0.0), min_rest=0.5)))
        for name, kw in cases:
            moves, stats = finish(surf, stl_path=stl, floor_z=floor_z,
                                  threads=4, **kw)
            feed = [(mv["x"], mv["y"], mv["z"]) for mv in moves
                    if mv["g"] == 1 and mv.get("z") is not None]
            assert feed, "%s: no feed moves" % name
            inbox = [t for t in feed if abs(t[0]) <= sq - 0.5
                     and abs(t[1]) <= shy - 0.5]
            below = [t for t in inbox if t[2] < floor_z - 1e-6]
            assert not below, \
                "%s: %d feed moves below floor_z inside the stock box " \
                "(min %.3f at y=%.2f)" % (name, len(below),
                                           min(t[2] for t in below),
                                           max(abs(t[1]) for t in below))
            assert stats.get("n_floor_dropped", 0) > 0, \
                "%s: n_floor_dropped=0 (pad rows never reached the floor)" \
                % name
            kept = [t for t in feed if t[2] >= floor_z]
            assert kept, "%s: nothing kept above the floor (wholesale drop)" \
                % name
            print("floor-pad %s: feed=%d inbox=%d dropped=%d kept_above=%d"
                  % (name, len(feed), len(inbox), stats["n_floor_dropped"],
                     len(kept)))


def bored_cyl_stl(path, ro=8.0, ri=4.8, h=14.0, n=96):
    """FE5f: vertical cylinder (radius ro, z 0..h) with a THROUGH bore
    (radius ri): the bore wall is steep and, with stock filled in, every
    entry into it plunges - the through-bore trap (James drills those)."""
    ang = np.linspace(0.0, 2.0 * math.pi, n + 1)[:-1]
    xo, yo = ro * np.cos(ang), ro * np.sin(ang)
    xi, yi = ri * np.cos(ang), ri * np.sin(ang)
    tris = []
    for i in range(n):
        j = (i + 1) % n
        mo = (math.cos(ang[i] + ang[j] - math.pi),
              math.sin(ang[i] + ang[j] - math.pi), 0.0)   # outer +radial
        mi = (-mo[0], -mo[1], 0.0)                        # bore wall -radial
        up = (0.0, 0.0, 1.0)
        dn = (0.0, 0.0, -1.0)
        tris += [((xo[i], yo[i], 0.0), (xo[j], yo[j], 0.0),
                  (xo[j], yo[j], h), mo),
                 ((xo[i], yo[i], 0.0), (xo[j], yo[j], h),
                  (xo[i], yo[i], h), mo),
                 ((xi[i], yi[i], 0.0), (xi[i], yi[i], h),
                  (xi[j], yi[j], h), mi),
                 ((xi[i], yi[i], 0.0), (xi[j], yi[j], h),
                  (xi[j], yi[j], 0.0), mi),
                 ((xo[i], yo[i], h), (xo[j], yo[j], h),
                  (xi[j], yi[j], h), up),
                 ((xo[i], yo[i], h), (xi[j], yi[j], h),
                  (xi[i], yi[i], h), up),
                 ((xo[i], yo[i], 0.0), (xi[i], yi[i], 0.0),
                  (xi[j], yi[j], 0.0), dn),
                 ((xo[i], yo[i], 0.0), (xi[j], yi[j], 0.0),
                  (xo[j], yo[j], 0.0), dn)]
    return write_stl(path, tris)


def plain_cyl_stl(path, ro=18.0, h=20.0, n=96):
    """FE5f-b: plain vertical cylinder (radius ro, z 0..h) - the dome/boss
    surface. The bores are NOT in the part: they stand as tall stock columns
    (to be drilled), so a raster row crossing them has BOTH ends buried while
    the middle is clear - the whole-pass-drop trap."""
    ang = np.linspace(0.0, 2.0 * math.pi, n + 1)[:-1]
    xo, yo = ro * np.cos(ang), ro * np.sin(ang)
    tris = []
    for i in range(n):
        j = (i + 1) % n
        mo = (math.cos(ang[i] + ang[j] - math.pi),
              math.sin(ang[i] + ang[j] - math.pi), 0.0)
        tris += [((xo[i], yo[i], 0.0), (xo[j], yo[j], 0.0),
                  (xo[j], yo[j], h), mo),
                 ((xo[i], yo[i], 0.0), (xo[j], yo[j], h),
                  (xo[i], yo[i], h), mo),
                 ((xo[i], yo[i], h), (xo[j], yo[j], h), (0.0, 0.0, h),
                  (0.0, 0.0, 1.0)),
                 ((xo[i], yo[i], 0.0), (0.0, 0.0, 0.0),
                  (xo[j], yo[j], 0.0), (0.0, 0.0, -1.0))]
    return write_stl(path, tris)


def test_fe5f_skip_bore_entries():
    """FE5f: a boss with a 10 mm-ish THROUGH bore full of stock (stock top
    above the boss top; the 9.525 ball has ~0.038 mm radial room per side).
    No ramp top on a bore-wall entry can be clear, and neither end is -
    FE5e left those unramped (ZB violations). FE5f must SKIP them: replay
    the estimator's LiveStock in emit order (as test_fe5t does) and require
    every ENTRY - the bottom of a vertical G1 descent (link plunge onto the
    pass / ramp top) - to land at live depth <= the ball floor 0.5 mm
    (mid-pass CL descents along verified paths are FE5e traversal behaviour,
    out of scope here), AND the skip report to list a cluster centred within
    1 mm of the bore axis. Must FAIL BY ASSERTION on e773afa (entries
    plunged up to 5.6 mm deep; no fe5_skipped_* stats at all)."""
    from engine import finish as _fmod
    from engine.finish import finish
    ZB_FLOOR_BALL = getattr(_fmod, "ZB_FLOOR_BALL", 0.5)
    from engine.entry_depth import LiveStock, load_heightfield
    cell, top, boss_r, bore_r = 0.5, 14.0, 8.0, 4.8
    stock_bore = top + 2.0            # bore FULL of stock, top above boss
    with tempfile.TemporaryDirectory() as td:
        stl = bored_cyl_stl(os.path.join(td, "bore.stl"), ro=boss_r,
                            ri=bore_r, h=top)
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock.npy")
        gx0, gx1, gy0, gy1 = -16.0, 16.0, -16.0, 16.0
        nx = int(round((gx1 - gx0) / cell))
        ny = int(round((gy1 - gy0) / cell))
        CX, CY = np.meshgrid(gx0 + (np.arange(nx) + 0.5) * cell,
                             gy0 + (np.arange(ny) + 0.5) * cell)
        R = np.hypot(CX, CY)
        A = np.full(CX.shape, top + 0.3)   # normal 0.3 finish allowance
        A[R <= bore_r] = stock_bore        # the bore stands full of stock
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 9.525, 0.0),
                              stepover=1.5, floor_z=6.0, threads=4,
                              stock_from=stockp, ramp_angle_deg=2.0)
        assert moves and stats.get("stock_from"), "stock_from not recorded"
        # the trap must be real: something tries to enter the bore
        A0, sx0, sy0, c0 = load_heightfield(stockp)
        live = LiveStock(A0, sx0, sy0, c0, 0.5 * 9.525)
        deep = []
        prev = None
        for m in moves:
            x, y, z = m["x"], m["y"], m["z"]
            if prev is not None:
                px, py, pz = prev
                if m["g"] == 1 and z < pz - 1e-9 \
                        and abs(x - px) <= 1e-9 and abs(y - py) <= 1e-9:
                    dd = live.disk_depth(x, y, z)
                    if math.isfinite(dd) and dd > ZB_FLOOR_BALL:
                        deep.append((round(x, 2), round(y, 2),
                                     round(z, 3), round(dd, 3)))
                live.stamp_chord(prev, (x, y, z))
            prev = (x, y, z)
        assert not deep, \
            "FE5f: %d bore entries plunged > %.1f mm into live stock " \
            "(max %.3f): %s" % (len(deep), ZB_FLOOR_BALL,
                                 max(e[3] for e in deep), deep[:4])
        clusters = stats.get("fe5_skipped_clusters", [])
        assert stats.get("fe5_skipped_n", 0) >= 1, "nothing was skipped"
        assert clusters, "no skip clusters reported"
        d0 = min(math.hypot(c["center"][0], c["center"][1]) for c in clusters)
        assert d0 <= 1.0, \
            "no skip cluster centred on the bore axis: %s" % (clusters,)
        print("fe5f skip-bore: skipped %d passes in %d cluster(s) at %s "
              "(max live depth %.2f mm)"
              % (stats["fe5_skipped_n"], len(clusters),
                 clusters[0]["center"], clusters[0]["max_depth_mm"]))


def _g1_samples(moves, step=0.25):
    """XY samples every <= step mm along every emitted G1 segment (coverage
    checks must not read sparse move ENDPOINTS as gaps)."""
    out = []
    prev = None
    for m in moves:
        cur = (m["x"], m["y"])
        if prev is not None and m["g"] == 1:
            n = max(1, int(math.ceil(math.dist(prev, cur) / step)))
            out.extend((prev[0] + (cur[0] - prev[0]) * t / n,
                        prev[1] + (cur[1] - prev[1]) * t / n)
                       for t in range(1, n + 1))
        prev = cur
    return np.asarray(out, dtype=float)


def test_fe5fb_real_bore_surface_kept():
    """FE5f-b on the REAL bore geometry (bored_cyl_stl, boss r 18 with one
    4.8 mm through-bore full of stock, 0.3 finish allowance elsewhere): the
    boss surface beyond bore + tool + 0.5 mm stays finished (emitted cut
    points within 1 mm of every such cell) and no skip vertex lies beyond
    bore + tool + 1 mm of the bore axis. Coordinator: must fail on 1f499f5
    (whole-pass drop) by assertion where that geometry exposes it."""
    from engine.finish import finish
    cell, top, ro, bore_r = 0.5, 14.0, 18.0, 4.8
    with tempfile.TemporaryDirectory() as td:
        stl = bored_cyl_stl(os.path.join(td, "bore.stl"), ro=ro, ri=bore_r,
                            h=top)
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock.npy")
        gx0, gx1, gy0, gy1 = -22.0, 22.0, -22.0, 22.0
        nx = int(round((gx1 - gx0) / cell))
        ny = int(round((gy1 - gy0) / cell))
        CX, CY = np.meshgrid(gx0 + (np.arange(nx) + 0.5) * cell,
                             gy0 + (np.arange(ny) + 0.5) * cell)
        A = np.full(CX.shape, top + 0.3)
        A[np.hypot(CX, CY) <= bore_r] = top + 2.0   # bore full of stock
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 9.525, 0.0),
                              stepover=1.5, floor_z=6.0, threads=4,
                              stock_from=stockp, ramp_angle_deg=2.0)
        assert moves, "no moves"
        pts = _g1_samples(moves)
        keep_r = bore_r + 0.5 * 9.525 + 0.5
        miss = []
        for cy in np.arange(-ro + 1.0, ro, 0.5):
            for cx in np.arange(-ro + 1.0, ro, 0.5):
                r = math.hypot(cx, cy)
                if r <= keep_r or r > ro - 1.0:
                    continue
                dd = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).min()
                if dd > 1.0:
                    miss.append((round(cx, 2), round(cy, 2), round(dd, 2)))
        assert not miss, "real bore: %d boss cells beyond bore+tool+0.5 " \
            "uncovered: %s" % (len(miss), miss[:4])
        far = [p for p in (stats.get("fe5_skip_pts") or [])
               if math.hypot(p[0], p[1]) > bore_r + 0.5 * 9.525 + 1.0]
        assert not far, "real bore: %d skip vertices beyond bore+tool+1: %s" \
            % (len(far), far[:4])
        print("fe5fb real bore: surface beyond the bore covered, skips %d"
              % stats.get("fe5_skipped_n", 0))


def test_fe5fb_fragment_trim_keeps_surface():
    """FE5f/FE5f-b: boss (plain cyl r 18, h 20) with two through-bores'
    worth of standing stock: columns r 4.8 at (+-12.5, 0) filled to h + 2
    above the 0.3-mm finish allowance (the 9.525 ball has ~0.038 mm radial
    room per side; James drills those). A shallow row crossing a column has
    its entry buried (disk sees the 2-mm-tall column) and no ramp top on
    that run clears, and neither end does - FE5f must SKIP the entry (never
    plunge: replay the estimator's LiveStock in emit order, as test_fe5t
    does, and require every ENTRY - the bottom of a vertical G1 descent -
    to land at live depth <= the ball floor 0.5 mm) and report it clustered
    on the column axes. FE5f-b: only the ILLEGAL FRAGMENT may be dropped -
    every finish-relevant cell of the boss surface beyond bore radius + tool
    radius + 0.5 mm must still be finished: no skipped vertex there (raw
    fe5_skip_pts, and the report must expose them whenever passes were
    dropped), and emitted cut points within one stepover of every such
    cell. Must FAIL BY ASSERTION on 1f499f5 (whole-pass drop: rows crossing
    a column lose their whole stripe across the boss - cells beyond both
    columns unfinished - and raw skip vertices reach past bore + tool +
    0.5 mm)."""
    from engine import finish as _fmod
    from engine.finish import finish
    ZB_FLOOR_BALL = getattr(_fmod, "ZB_FLOOR_BALL", 0.5)
    from engine.entry_depth import LiveStock, load_heightfield
    cell, h, ro, bore_r, axis = 0.5, 20.0, 18.0, 4.8, 12.5
    col_top = h + 2.0               # columns stand 2 mm above the allowance
    with tempfile.TemporaryDirectory() as td:
        stl = plain_cyl_stl(os.path.join(td, "boss.stl"), ro=ro, h=h)
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock.npy")
        gx0, gx1, gy0, gy1 = -22.0, 22.0, -22.0, 22.0
        nx = int(round((gx1 - gx0) / cell))
        ny = int(round((gy1 - gy0) / cell))
        CX, CY = np.meshgrid(gx0 + (np.arange(nx) + 0.5) * cell,
                             gy0 + (np.arange(ny) + 0.5) * cell)
        RA = np.hypot(CX - axis, CY)     # distance to either bore column
        RB = np.hypot(CX + axis, CY)
        A = np.full(CX.shape, h + 0.3)   # normal 0.3 finish allowance
        A[np.minimum(RA, RB) <= bore_r] = col_top
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 9.525, 0.0),
                              stepover=1.5, floor_z=12.0, threads=4,
                              stock_from=stockp, ramp_angle_deg=2.0)
        assert moves and stats.get("stock_from"), "stock_from not recorded"
        # the trap must be real: something tries to enter a column
        A0, sx0, sy0, c0 = load_heightfield(stockp)
        live = LiveStock(A0, sx0, sy0, c0, 0.5 * 9.525)
        deep = []
        prev = None
        cut_pts = []                   # emitted feed (G1) cut points
        for m in moves:
            x, y, z = m["x"], m["y"], m["z"]
            if m["g"] == 1:
                cut_pts.append((x, y))
            if prev is not None:
                px, py, pz = prev
                if m["g"] == 1 and z < pz - 1e-9 \
                        and abs(x - px) <= 1e-9 and abs(y - py) <= 1e-9:
                    dd = live.disk_depth(x, y, z)
                    if math.isfinite(dd) and dd > ZB_FLOOR_BALL:
                        deep.append((round(x, 2), round(y, 2),
                                     round(z, 3), round(dd, 3)))
                live.stamp_chord(prev, (x, y, z))
            prev = (x, y, z)
        assert not deep, \
            "FE5f: %d bore entries plunged > %.1f mm into live stock " \
            "(max %.3f): %s" % (len(deep), ZB_FLOOR_BALL,
                                 max(e[3] for e in deep), deep[:4])
        clusters = stats.get("fe5_skipped_clusters", [])
        n_skip = stats.get("fe5_skipped_n", 0)
        assert n_skip >= 1, "nothing was skipped"
        assert clusters, "no skip clusters reported"
        # FE5f-b 1: the boss surface beyond bore + tool + 0.5 mm from both
        # columns is still finished - emitted cut points within one stepover
        # of every such cell
        tol = 1.0   # rows are stepover=1.5 apart; worst in-band gap 0.75
        pts = _g1_samples(moves)
        miss = []
        yy = np.arange(-ro + 1.0, ro, 0.5)
        xx = np.arange(-ro + 1.0, ro, 0.5)
        for cy in yy:
            inside = xx[xx ** 2 + cy ** 2 <= (ro - 1.0) ** 2]
            for cx in inside:
                if min(math.hypot(cx - axis, cy), math.hypot(cx + axis, cy)) \
                        <= bore_r + 0.5 * 9.525 + 0.5:
                    continue          # may be left with the bores
                dd = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).min()
                if dd > tol:
                    miss.append((round(cx, 2), round(cy, 2), round(dd, 2)))
        assert not miss, \
            "FE5f-b: %d finish-relevant cells beyond bore+tool+0.5 mm are " \
            "uncovered (nearest cut point > %.1f mm; whole stripes lost): %s" \
            % (len(miss), tol, miss[:4])
        # FE5f-b 2: only the fragment near a column may be skipped - every
        # recorded skip vertex within bore + tool + 1 mm of a column axis
        skip_pts = stats.get("fe5_skip_pts")
        assert skip_pts is not None, \
            "FE5f-b: %d passes skipped but raw skip vertices not reported" \
            % n_skip
        far = [(x, y, dep) for x, y, dep in skip_pts
               if min(math.hypot(x - axis, y), math.hypot(x + axis, y))
               > bore_r + 0.5 * 9.525 + 1.0]
        assert not far, \
            "FE5f-b: %d skipped vertices beyond bore+tool+1 mm off the " \
            "column axes (unfinished outside the bores): %s" % (len(far),
                                                                far[:4])
        print("fe5f skip-bore: skipped %d passes/fragments in %d cluster(s) "
              "at %s (max live depth %.2f mm); surface beyond the bores "
              "fully covered" % (n_skip, len(clusters), clusters[0]["center"],
                                clusters[0]["max_depth_mm"]))


def _prism_stl(path, prof, y0, y1):
    """FE5fc: extrude an XZ profile polygon along Y (both windings, so the
    drop-cutter sees every face)."""
    n = len(prof)
    tris = []
    for i in range(n):
        j = (i + 1) % n
        x0, z0 = prof[i]
        x1, z1 = prof[j]
        ref = (z1 - z0, 0.0, -(x1 - x0))
        tris.append(((x0, y0, z0), (x1, y1, z1), (x1, y0, z1), ref))
        tris.append(((x0, y0, z0), (x0, y1, z0), (x1, y1, z1), ref))
    for yy, sgn in ((y0, -1.0), (y1, 1.0)):
        for i in range(1, n - 1):
            tris.append(((prof[0][0], yy, prof[0][1]),
                        (prof[i][0], yy, prof[i][1]),
                        (prof[i + 1][0], yy, prof[i + 1][1]), (0, sgn, 0)))
    return write_stl(path, tris)


def test_fe5fc_buried_ends_keep_middle():
    """FE5fc: a long raster pass whose FIRST part is buried > 0.5 mm with no
    legal ramp at either end - deep stock (+2.0) at both ends of a hill
    prism, only +0.3 over the hill - must lose only the illegal fragment.
    The whole-pass sizing (both ends, FE5e) fails: every vertex sits 0.3
    under the allowance and the 2 deg ramp from the buried end cannot beat
    the hill. But a suffix based ON THE HILL clears within ~1.5 mm, so
    FE5f-b's fragment trim keeps the middle: assert every hill cell in
    |x| <= 4, |y| <= 5 is cut (G1 samples within 1 mm); no vertical G1
    descent may land deeper than the ball floor 0.5 mm (replay as in
    test_fe5f); passes were skipped and clustered; and every recorded raw
    skip vertex has a FINITE live depth (FE5fc: off-grid vertices are not
    recorded, no invented depth). Must FAIL BY ASSERTION on 1f499f5
    (whole-pass drop: hill cells uncovered, no fe5_skip_pts stat)."""
    from engine import finish as _fmod
    from engine.finish import finish
    ZB_FLOOR_BALL = getattr(_fmod, "ZB_FLOOR_BALL", 0.5)
    from engine.entry_depth import LiveStock, load_heightfield
    cell = 0.5

    def surfz(x):
        if x <= -8 or x >= 8:
            return 10.0
        if x < -2:
            return 10.0 + 3.0 * (x + 8) / 6.0
        if x > 2:
            return 13.0 - 3.0 * (x - 2) / 6.0
        return 13.0

    with tempfile.TemporaryDirectory() as td:
        prof = [(-14, 0), (14, 0), (14, 10), (8, 10), (2, 13), (-2, 13),
                (-8, 10), (-14, 10)]
        stl = _prism_stl(os.path.join(td, "hill.stl"), prof, -6.0, 6.0)
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock.npy")
        gx0, gx1, gy0, gy1 = -20.0, 20.0, -10.0, 10.0
        nx = int(round((gx1 - gx0) / cell))
        ny = int(round((gy1 - gy0) / cell))
        CX, CY = np.meshgrid(gx0 + (np.arange(nx) + 0.5) * cell,
                             gy0 + (np.arange(ny) + 0.5) * cell)
        A = np.empty(CX.shape)
        for j in range(ny):
            for i in range(nx):
                x = CX[j, i]
                A[j, i] = surfz(x) + (2.0 if x <= -8 or x >= 8 else 0.3)
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 6.0, 0.0),
                             stepover=1.5, floor_z=5.0, threads=4,
                             stock_from=stockp, ramp_angle_deg=2.0)
        assert moves and stats.get("stock_from"), "stock_from not recorded"
        # the middle of the hill must still be cut (fails on 1f499f5:
        # every crossing pass is dropped whole)
        pts = _g1_samples(moves)
        assert len(pts), "no G1 cut points at all"
        miss = []
        for cy in np.arange(-5.0, 5.1, 1.0):
            for cx in np.arange(-2.0, 4.1, 1.0):
                dd = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).min()
                if dd > 1.0:
                    miss.append((round(cx, 1), round(cy, 1), round(float(dd),
                                                              2)))
        assert not miss, \
            "FE5fc: %d hill cells uncovered (whole passes dropped): %s" \
            % (len(miss), miss[:4])
        # no entry may plunge deeper than the ball floor (replay, test_fe5f
        # convention: mid-pass descents along verified paths are traversal)
        live = LiveStock(*load_heightfield(stockp), 3.0)
        deep = []
        prev = None
        for m in moves:
            x, y, z = m["x"], m["y"], m["z"]
            if prev is not None:
                px, py, pz = prev
                if m["g"] == 1 and z < pz - 1e-9 \
                        and abs(x - px) <= 1e-9 and abs(y - py) <= 1e-9:
                    dd = live.disk_depth(x, y, z)
                    if math.isfinite(dd) and dd > ZB_FLOOR_BALL:
                        deep.append((round(x, 2), round(y, 2), round(z, 3),
                                   round(dd, 3)))
                live.stamp_chord(prev, (x, y, z))
            prev = (x, y, z)
        assert not deep, \
            "FE5fc: %d entries plunged > %.1f mm into live stock (max " \
            "%.3f): %s" % (len(deep), ZB_FLOOR_BALL,
                           max(e[3] for e in deep), deep[:4])
        n_skip = stats.get("fe5_skipped_n", 0)
        assert n_skip >= 1, "nothing was skipped"
        assert stats.get("fe5_skipped_clusters"), "no skip clusters reported"
        skip_pts = stats.get("fe5_skip_pts")
        assert skip_pts is not None, \
            "FE5fc: %d passes skipped but raw skip vertices not reported" \
            % n_skip
        bad = [p for p in skip_pts if not math.isfinite(p[2])]
        assert not bad, \
            "FE5fc: %d skip vertices with non-finite (invented) depth: %s" \
            % (len(bad), bad[:4])
        print("fe5fc buried-ends: skipped %d, hill kept (%.0f mm cut, "
              "%d finite skip vertices)" % (n_skip, stats.get("cut_len", 0.0),
                                           len(skip_pts)))


def test_fe5g_no_lifted_vertex_in_constant_z_pass():
    """FE5g (red test): a constant-Z finish pass must not carry an interior
    vertex lifted above BOTH of its neighbours by more than the ball axial
    floor (0.5 mm) unless the pass is split there (a G0 next to it). Such a
    vertex (an inserted point whose CL comes from the drop-cutter where the
    ball rides a wall top edge) makes the pass climb and drop back steeply;
    on the test block the drop drove the T20 ball 0.815 mm into live stock
    (ZB, connector E2E test_tb_rest_chain_checks_stock_bottom). Scene: a
    20 x 20 mm boss 14 mm tall on a plate, stock 0.3 over the part,
    stock_from. FAILS on fe5-trial 74582f3: 98 lifted vertices around the
    boss corners, max lift 4.607 mm."""
    from engine.finish import finish
    cell = 0.5
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "boss.stl")
        write_stl(stl, _box(-25, 25, -25, 25, -2, 0)
                  + _box(-10, 10, -10, 10, 0, 14.0))
        surf = model.load_surf(stl)
        gx0, gy0, nx, ny = -25.0, -25.0, 100, 100
        CX, CY = np.meshgrid(gx0 + (np.arange(nx) + 0.5) * cell,
                             gy0 + (np.arange(ny) + 0.5) * cell)
        boss = (np.abs(CX) <= 10) & (np.abs(CY) <= 10)
        stockp = os.path.join(td, "stock.npy")
        np.save(stockp, np.where(boss, 14.3, 0.3))
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 9.525, 0.0),
                              stepover=1.5, floor_z=1.0, threads=4,
                              stock_from=stockp, ramp_angle_deg=2.0)
    P = [(m["x"], m["y"], m["z"], m["g"]) for m in moves]
    lifted = [(round(b[0], 3), round(b[1], 3), round(a[2], 3),
               round(b[2] - a[2], 3))
              for a, b, c in zip(P[:-2], P[1:-1], P[2:])
              if a[3] == b[3] == c[3] == 1 and abs(a[2] - c[2]) < 1e-6
              and b[2] > a[2] + 0.5]
    print("fe5g lifted vertices in constant-Z passes: %d (max lift %.3f)"
          % (len(lifted), max([e[3] for e in lifted] or [0.0])))
    assert not lifted, \
        "FE5g: %d constant-Z pass vertices lifted > 0.5 mm above both " \
        "neighbours (max %.3f): %s" % (len(lifted), max(e[3] for e in lifted),
                                       lifted[:4])


def test_fe5g_scene_vertices_never_below_cl():
    """FE5g: gouge gate on the red-test scene (20 x 20 boss 14 tall, stock
    from): every emitted G1 vertex must sit AT OR ABOVE its own drop-cutter
    CL (ball 9.525). A root fix that simply forced inserted vertices to the
    pass Z without the CL check would cut into the part at the wall-top
    edges and fail here by a measured value."""
    import math
    from engine.finish import finish, make_cutter, batch_drop
    cell = 0.5
    with tempfile.TemporaryDirectory() as td:
        stl = os.path.join(td, "boss.stl")
        write_stl(stl, _box(-25, 25, -25, 25, -2, 0)
                  + _box(-10, 10, -10, 10, 0, 14.0))
        surf = model.load_surf(stl)
        gx0, gy0, nx, ny = -25.0, -25.0, 100, 100
        CX, CY = np.meshgrid(gx0 + (np.arange(nx) + 0.5) * cell,
                             gy0 + (np.arange(ny) + 0.5) * cell)
        boss = (np.abs(CX) <= 10) & (np.abs(CY) <= 10)
        stockp = os.path.join(td, "stock.npy")
        np.save(stockp, np.where(boss, 14.3, 0.3))
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 9.525, 0.0),
                              stepover=1.5, floor_z=1.0, threads=4,
                              stock_from=stockp, ramp_angle_deg=2.0)
        cutter = make_cutter("ball", 9.525, 0.0)
        pts = [(m["x"], m["y"]) for m in moves if m["g"] == 1]
        cl = batch_drop(surf, cutter, pts, threads=4)
        bad = []
        for m, c in zip([m for m in moves if m["g"] == 1], cl):
            if math.isfinite(c) and m["z"] < c - 0.004:   # NET_TOL margin
                bad.append((round(m["x"], 3), round(m["y"], 3),
                            round(m["z"], 3), round(float(c), 3)))
        print("fe5g gouge gate: %d G1 vertices, %d below CL by >0.004 mm"
              % (len(pts), len(bad)))
        assert not bad, \
            "FE5g: %d emitted vertices below their drop-cutter CL " \
            "(max %.3f): %s" % (len(bad),
                                max(p[3] - p[2] for p in bad), bad[:4])


def test_fe5g_net_ramps_and_trims_inpass_drop():
    """FE5g safety net unit test on _fe5g_inpass: a near-vertical descent
    mid-pass is ramped along the pass's own following vertices (XY fixed, Z
    only rises, resulting slopes <= the ramp angle); a descent into the LAST
    vertex has no followers and is trimmed (head kept, vertices reported).
    Disabling the net (no-op _fe5g_inpass) fails this test."""
    from engine.finish import _fe5g_inpass
    from engine.entry_depth import LiveStock

    A = np.full((40, 40), 10.0)          # flat stock at Z10, cell 0.5
    live = LiveStock(A, -10.0, -10.0, 0.5, 0.5 * 9.525)
    tan = math.tan(math.radians(2.0))
    # mid-pass drop: 20 mm of flat at Z8, near-vertical drop to Z5 at x=5,
    # then 20 mm more at Z5 (followers exist to ramp over)
    P = [(x, 0.0, 8.0) for x in np.arange(-5.0, 5.0, 0.5)]
    P += [(5.0, 0.0, 5.0)]
    P += [(x, 0.0, 5.0) for x in np.arange(5.5, 15.0, 0.5)]
    out, n_ramp, trimmed = _fe5g_inpass(live, P, tan)
    assert n_ramp >= 1 and not trimmed, \
        "mid-pass drop not ramped: n_ramp=%d trimmed=%s" % (n_ramp, trimmed)
    for (x, y, z), (xo, yo, zo) in zip(out, P):
        assert (x, y) == (xo, yo) and z >= zo - 1e-9, "point moved/lowered"
    for a, b in zip(out, out[1:]):
        dz = a[2] - b[2]
        h = math.hypot(b[0] - a[0], b[1] - a[1])
        assert dz <= 1e-9 or math.degrees(math.atan2(dz, h)) <= 2.0 + 1e-6, \
            "ramped pass still descends at %.1f deg" % \
            math.degrees(math.atan2(dz, h))
    # tail drop: descent into the LAST vertex -> trim, head kept
    Q = [(x, 0.0, 8.0) for x in np.arange(-5.0, 5.0, 0.5)]
    Q += [(5.0, 0.0, 5.0)]
    out2, n_ramp2, trimmed2 = _fe5g_inpass(live, Q, tan)
    assert n_ramp2 == 0 and len(trimmed2) == 1 and len(out2) == len(Q) - 1, \
        "tail drop not trimmed: n_ramp=%d trimmed=%s len=%d/%d" % \
        (n_ramp2, trimmed2, len(out2), len(Q))
    assert trimmed2[0]["x"] == 5.0 and trimmed2[0]["depth"] > 0.5, \
        "trimmed vertex not reported with depth: %s" % trimmed2
    print("fe5g net: mid-pass drop ramped (slopes <= 2 deg), tail drop "
          "trimmed and reported")


def test_fe5h_entry_estimate_not_below_true_depth():
    """FE5h (supervisor): the live-stock entry estimate must never UNDER-read
    the judge-model true live depth at an emitted entry. Scene: flat pocket
    floor 28.2 (live stock 28.4) whose FIRST row starts at the pocket corner
    (-8,-12); a post-roughing leftover ridge (coarse stock 29.55, cells
    x<=-11.75, y<=-12.25 - the raw zone just OUTSIDE the pocket corner) sits
    so its coarse-cell edge is 3.45 mm from the start: the 0.5 mm lattice and
    the plain 0.5->0.1 overlap resample both hide it (contribution < 0, the
    estimator reads 0.1985 -> straight plunge), yet the true 0.1 mm judge
    stock keeps the rim sliver an optimistic coarse stamp leaves standing
    past the footprint (the RT2 corner: the coarse kernel clears ~c/sqrt(2)+c
    - exactly the TB chain's 1.1303 mm plunge mechanism). TRUTH is built
    independently of the engine: dilate the coarse array by 2 source cells
    (1.0 mm Chebyshev box-max, data-preserving) and overlap-resample to 0.1
    mm, then stamp the emitted G1 prefix with the judge's own zmap.simulate
    and read the exact ball formula. Assert at every emitted vertical entry
    (plunge): true depth <= the ZB floor 0.5, and at every entry (plunge or
    ramp vertex) below the floor: engine estimate >= true depth - 1e-6.
    Must FAIL on the plain resample (est 0.1985 vs truth 0.6085 at the
    plunge (-8,-12)) and PASS once resample_fine/LiveStock pool the source
    with margin=2*cell (the entry is then read ~0.61 and ramped)."""
    from engine.finish import finish
    from engine.entry_depth import LiveStock
    R = 9.525 / 2.0
    cell = 0.5
    gx0, gy0, gx1, gy1 = -13.0, -17.0, 13.0, 17.0
    floor_z = 28.2
    with tempfile.TemporaryDirectory() as td:
        stl = write_stl(os.path.join(td, "fe5h_pocket.stl"),
                        _box(-8.0, 8.0, -12.0, 12.0, 0.0, floor_z))
        surf = model.load_surf(stl)
        stockp = os.path.join(td, "stock.npy")
        CX, CY = np.meshgrid(gx0 + (np.arange(52) + 0.5) * cell,
                             gy0 + (np.arange(68) + 0.5) * cell)
        A = np.full(CX.shape, 28.4)
        A[(CX <= -11.75) & (CY >= -13.0) & (CY <= -12.25)] = 29.55
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, _stats = finish(surf, stl_path=stl, tool=("ball", 9.525, 0.0),
                               stepover=3.0, floor_z=floor_z, threads=4,
                               stock_from=stockp, ramp_angle_deg=2.0)
    # truth stock: dilate the coarse array 2 cells (the sliver the judge's
    # fine rough stamp keeps past the optimistic coarse footprint), then the
    # same conservative overlap resample the estimator uses
    D = np.where(np.isfinite(A), A, -np.inf)
    for _ in range(2):
        pad = np.full((D.shape[0] + 2, D.shape[1] + 2), -np.inf)
        pad[1:-1, 1:-1] = D
        o = pad[1:-1, 1:-1].copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                o = np.maximum(o, pad[1 + dy:D.shape[0] + 1 + dy,
                                      1 + dx:D.shape[1] + 1 + dx])
        D = np.where(np.isfinite(D), o, -np.inf)
    nxf = int(round((gx1 - gx0) / 0.1))
    nyf = int(round((gy1 - gy0) / 0.1))
    cx = gx0 + (np.arange(nxf) + 0.5) * 0.1
    cy = gy0 + (np.arange(nyf) + 0.5) * 0.1
    ix = np.clip(np.floor((cx - 0.05 - gx0) / cell).astype(int),
                 0, D.shape[1] - 1)
    iy = np.clip(np.floor((cy - 0.05 - gy0) / cell).astype(int),
                 0, D.shape[0] - 1)
    kx = ((cx + 0.05 - gx0) / cell > ix) & (ix + 1 < D.shape[1])
    ky = ((cy + 0.05 - gy0) / cell > iy) & (iy + 1 < D.shape[0])
    b00 = D[np.ix_(iy, ix)]
    b10 = np.where(kx[None, :],
                   D[np.ix_(iy, np.minimum(ix + 1, D.shape[1] - 1))],
                   -np.inf)
    b01 = np.where(ky[:, None],
                   D[np.ix_(np.minimum(iy + 1, D.shape[0] - 1), ix)],
                   -np.inf)
    b11 = np.where(kx[None, :] & ky[:, None],
                   D[np.ix_(np.minimum(iy + 1, D.shape[0] - 1),
                            np.minimum(ix + 1, D.shape[1] - 1))],
                   -np.inf)
    F = np.maximum(np.maximum(b00, b10), np.maximum(b01, b11))
    part = np.where(np.isfinite(F), F, -1e9)

    def truth_depth(gmv, x, y, z):
        if gmv:
            st = zmap.simulate(gmv, part, 0.1, gx0, gy0,
                               stock_box=(gx0, gx1, gy0, gy1, 0.0, 31.5),
                               tool="ball", dia=9.525,
                               stock_init=F.copy())["stock"]
        else:
            st = F
        ci = int(math.floor((x - gx0) / 0.1))
        cj = int(math.floor((y - gy0) / 0.1))
        kR = int(math.ceil(R / 0.1))
        i0, i1 = max(0, ci - kR - 1), min(st.shape[1], ci + kR + 2)
        j0, j1 = max(0, cj - kR - 1), min(st.shape[0], cj + kR + 2)
        DX, DY = np.meshgrid(gx0 + (np.arange(i0, i1) + 0.5) * 0.1 - x,
                             gy0 + (np.arange(j0, j1) + 0.5) * 0.1 - y)
        d2 = DX * DX + DY * DY
        w = st[j0:j1, i0:i1]
        m = (d2 <= R * R + 1e-9) & np.isfinite(w)
        assert m.any(), "no stock data at the entry"
        v = w[m] - (R - np.sqrt(np.maximum(R * R - d2[m], 0.0)))
        return float(np.max(v)) - z

    try:
        live = LiveStock(A, gx0, gy0, cell, R, margin=2.0 * cell)
    except TypeError:                       # pre-fix estimator
        live = LiveStock(A, gx0, gy0, cell, R)
    gmv = []
    entries = []                            # (x, y, z, est, is_plunge)
    prev = None
    for m in moves:
        x, y, z = m["x"], m["y"], m["z"]
        if prev is not None:
            px, py, pz = prev
            if m["g"] == 1 and z < floor_z + 0.05:
                vert = abs(x - px) <= 1e-9 and abs(y - py) <= 1e-9
                if (vert and z < pz - 1e-9) or \
                        (abs(z - pz) > 1e-9 and not vert):
                    entries.append((x, y, z, live.disk_depth(x, y, z),
                                    vert and z < pz - 1e-9, len(gmv)))
        gmv.append({"line": len(gmv) + 1,
                    "motion": "G0" if m["g"] == 0 else "G1",
                    "x": x, "y": y, "z": z})
        if prev is not None and m["g"] == 1:
            live.stamp_chord(prev, (x, y, z))
        prev = (x, y, z)
    assert entries, "no entries emitted - the scene no longer exercises FE5"
    deep = []
    under = []
    for (x, y, z, est, is_plunge, npre) in entries:
        tr = truth_depth(gmv[:npre], x, y, z)
        rep = "(%.3f,%.3f) z=%.3f est=%.4f truth=%.4f" % (x, y, z, est, tr)
        if is_plunge and tr > 0.5 + 1e-9:
            deep.append(rep)
        if est < tr - 1e-6:
            under.append(rep)
    print("fe5h: %d entries; deep %s; under-read %s"
          % (len(entries), deep[:3], under[:3]))
    assert not deep, "FE5h: vertical entries below the 0.5 floor: %s" % deep
    assert not under, "FE5h: estimate under-reads truth: %s" % under


# ---------------------------------------------------------------------------
# RR-STOCK: the stock handed downstream is a replay of the EMITTED program,
# never lower than what it removes.
# ---------------------------------------------------------------------------

RR_TOL = 0.1  # mm, brief's TOL


def _handoff_read(A, x0, y0, cell, Xc, Yc, w):
    """Read a handed-down stock grid at the judge's cells: the max of every
    source cell overlapping the judge cell [c-w/2, c+w/2] (exactly the
    conservative resample_fine read the finish performs); non-finite source
    cells are no-data (-inf)."""
    Af = np.where(np.isfinite(A), A, -np.inf)
    ny_, nx_ = Af.shape
    i_lo = np.floor((Xc - w / 2.0 - x0) / cell).astype(np.int64)
    i_hi = np.floor((Xc + w / 2.0 - x0 - 1e-9) / cell).astype(np.int64)
    j_lo = np.floor((Yc - w / 2.0 - y0) / cell).astype(np.int64)
    j_hi = np.floor((Yc + w / 2.0 - y0 - 1e-9) / cell).astype(np.int64)
    out = np.full(Xc.shape, -np.inf)
    for dj in range(int((j_hi - j_lo).max()) + 1):
        for di in range(int((i_hi - i_lo).max()) + 1):
            ii, jj = i_lo + di, j_lo + dj
            ok = ((ii >= 0) & (ii < nx_) & (jj >= 0) & (jj < ny_)
                  & (ii <= i_hi) & (jj <= j_hi))
            v = Af[np.clip(jj, 0, ny_ - 1), np.clip(ii, 0, nx_ - 1)]
            out = np.maximum(out, np.where(ok, v, -np.inf))
    return out


def test_rrstock_rough_handoff_not_below_judge():
    """RR-STOCK red (a): rough the test block (manifest-pinned fixtures)
    through engine.cli with --stock-out, then judge the SAME emitted rough
    program with verify.zmap (0.1 mm part grid, full stock box). At every
    judge cell with standing stock (above the part) the engine handoff, read
    with the conservative overlap-max, must be >= judge - TOL (TOL=0.1):
    the handoff is a replay of the emitted program, never lower than what
    it removes. The coarse 0.5 mm planning stock over-clears thin slivers
    beside cuts and FAILS this (TB chain: 1190 cells, max 15.019 mm)."""
    import subprocess
    tb_stl = os.path.join(ROOT, "out", "test_block.stl")
    tb_hf05 = os.path.join(ROOT, "out", "test_block_hf_0.5.npy")
    tb_hf01 = os.path.join(ROOT, "out", "test_block_hf_0.1.npy")
    for p in (tb_stl, tb_hf05, tb_hf01):
        assert os.path.exists(p), "missing fixture %s" % p
    stock_box = (-50.0, 50.0, -40.0, 40.0, 0.0, 38.0)
    dia = 12.686
    with tempfile.TemporaryDirectory() as td:
        ngc = os.path.join(td, "rough.ngc")
        eng_stock = os.path.join(td, "stock_after_rough_engine.npy")
        cmd = [sys.executable, "-m", "engine.cli", "rough",
               "--step", os.path.join(ROOT, "samples", "test_block.step"),
               "--stock", *[("%.4f" % v) for v in stock_box],
               "--tool", "flat:%.4f" % dia,
               "--out", ngc, "--floor", "20.0",
               "--final-zmin", "20.381", "--leave", "0.381",
               "--stepdown", "19.05", "--optimal-load-mm", "2.03",
               "--hf", tb_hf05, "--min-rest", "0.5",
               "--stock-out", eng_stock]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           env=dict(os.environ, ENGINE_WORKERS="4"))
        assert r.returncode == 0, "cli rough failed rc=%d: %s" % (
            r.returncode, r.stderr[-800:])
        assert os.path.exists(eng_stock), "no engine handoff stock written"
        # judge: zmap replay of the SAME emitted rough program, 0.1 mm grid
        part = np.load(tb_hf01)
        with open(tb_hf01[:-4] + ".json") as fh:
            meta = json.load(fh)
        jx0, jy0, jc = float(meta["x0"]), float(meta["y0"]), float(meta["cell"])
        with open(ngc) as fh:
            gmv = zmap.parse_gcode(fh.read())
        res = zmap.simulate(gmv, part, jc, jx0, jy0, stock_box,
                            tool="flat", dia=dia)
        judge = res["stock"]
        E = np.load(eng_stock)
        with open(eng_stock[:-4] + ".json") as fh:
            emeta = json.load(fh)
        ex0, ey0, ec = (float(emeta["x0"]), float(emeta["y0"]),
                        float(emeta["cell"]))
        xs = jx0 + (np.arange(judge.shape[1]) + 0.5) * jc
        ys = jy0 + (np.arange(judge.shape[0]) + 0.5) * jc
        Xc, Yc = np.meshgrid(xs, ys)
        eng = _handoff_read(E, ex0, ey0, ec, Xc, Yc, jc)
        standing = np.isfinite(judge) & (judge > part + 0.01)
        deficit = np.where(standing, judge - eng, -np.inf)
        viol = standing & (deficit > RR_TOL)
        n_v = int(viol.sum())
        n_half = int((deficit > 0.5).sum())
        worst = float(np.max(deficit)) if standing.any() else 0.0
        print("rrstock(a): standing=%d cells, violations(>%.2f)=%d "
              "(%.1f mm2), cells >0.5mm low=%d, max deficit %.3f mm"
              % (int(standing.sum()), RR_TOL, n_v, n_v * jc * jc,
                 n_half, worst))
        assert n_v == 0, (
            "engine handoff is BELOW the judge replay at %d standing cells "
            "(max %.3f mm) - the handoff must replay the emitted program"
            % (n_v, worst))
        # two-sided (coordinator): also never above what the program left.
        # Compared CELL FOR CELL (centre read): the conservative overlap-max
        # above can pick up an uncut neighbour beside a wall and read up to a
        # full wall height over (measured 13.3 mm), which says nothing about
        # the replay; centre to centre the replay must match both ways.
        Ef = np.where(np.isfinite(E), E, -np.inf)
        ic = np.clip(np.floor((Xc - ex0) / ec).astype(np.int64), 0, Ef.shape[1] - 1)
        jc_ = np.clip(np.floor((Yc - ey0) / ec).astype(np.int64), 0, Ef.shape[0] - 1)
        eng_c = Ef[jc_, ic]
        fin = np.isfinite(judge) & np.isfinite(eng_c)
        over = float(np.max(np.where(fin, eng_c - judge, -np.inf)))
        under = float(np.max(np.where(fin, judge - eng_c, -np.inf)))
        print("rrstock(a) two-sided: max over %.3f mm, max under %.3f mm "
              "(TOL %.2f)" % (over, under, RR_TOL))
        assert over <= RR_TOL and under <= RR_TOL, (
            "engine handoff differs from the judge replay cell for cell: "
            "over %.3f, under %.3f mm" % (over, under))


def test_rrstock_finish_handoff_matches_judge():
    """RR-STOCK red (b): engine.cli finish --stock-out replays its OWN
    emitted moves with its ball into the engine's 0.1 mm stock; on a small
    two-boss scene that replay and zmap's --stock-out of the same finish
    program must agree: |engine - judge| <= TOL (0.1) at every cell with
    standing stock (above the part)."""
    import subprocess
    q, hy, top, bx, cx, bh = 15.0, 10.0, 10.0, 2.5, 5.0, 20.0
    gx0, gy0 = -18.0, -13.0                    # part grid beyond the stock
    gnx, gny = int(2 * 18.0 / CELL), int(2 * 13.0 / CELL)
    xs = gx0 + (np.arange(gnx) + 0.5) * CELL
    ys = gy0 + (np.arange(gny) + 0.5) * CELL
    Xc, Yc = np.meshgrid(xs, ys)
    part = hf_two_boss(Xc, Yc, top=top, bx=bx, cx=cx, bh=bh)
    stock_box = (-q, q, -hy, hy, 0.0, bh)
    stock0 = np.where((np.abs(Xc) <= q) & (np.abs(Yc) <= hy),
                      np.minimum(bh, part + 0.381), -np.inf)
    with tempfile.TemporaryDirectory() as td:
        stl = two_boss_stl(os.path.join(td, "2boss.stl"), q=q, top=top,
                           bx=bx, cx=cx, bh=bh)
        init_p = os.path.join(td, "stock_init.npy")
        np.save(init_p, stock0)
        with open(init_p[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": CELL}, fh)
        ngc = os.path.join(td, "finish.ngc")
        eng_stock = os.path.join(td, "stock_after_finish_engine.npy")
        cmd = [sys.executable, "-m", "engine.cli", "finish",
               "--stl", stl, "--tool", "ball:%.4f" % BALL_DIA,
               "--out", ngc, "--floor", "0.0",
               "--stock-from", init_p, "--stock-out", eng_stock]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           env=dict(os.environ, ENGINE_WORKERS="4"))
        assert r.returncode == 0, "cli finish failed rc=%d: %s" % (
            r.returncode, r.stderr[-800:])
        assert os.path.exists(eng_stock), "no engine after-finish stock"
        with open(ngc) as fh:
            gmv = zmap.parse_gcode(fh.read())
        res = zmap.simulate(gmv, part, CELL, gx0, gy0, stock_box,
                            tool="ball", dia=BALL_DIA, stock_init=stock0)
        judge = res["stock"]
        E = np.load(eng_stock)
        with open(eng_stock[:-4] + ".json") as fh:
            emeta = json.load(fh)
        assert abs(float(emeta["x0"]) - gx0) < 1e-9 \
            and abs(float(emeta["y0"]) - gy0) < 1e-9 \
            and abs(float(emeta["cell"]) - CELL) < 1e-9, \
            "engine replay grid %s != judge grid" % emeta
        assert E.shape == judge.shape, "grid shape mismatch"
        standing = np.isfinite(judge) & (judge > part + 0.01)
        diff = np.where(np.isfinite(E) & np.isfinite(judge),
                        np.abs(E - judge), np.inf)
        bad = standing & (diff > RR_TOL)
        n_b = int(bad.sum())
        worst = float(np.max(np.where(standing, diff, -np.inf))) \
            if standing.any() else 0.0
        print("rrstock(b): standing=%d cells, |engine-judge|>%.2f at %d "
              "cells, max diff %.4f mm"
              % (int(standing.sum()), RR_TOL, n_b, worst))
        assert n_b == 0, (
            "engine after-finish replay differs from the judge by > %.2f "
            "mm at %d standing cells (max %.4f)" % (RR_TOL, n_b, worst))
        # every cell (coordinator): an unchanged input stock would read far
        # above the judge exactly where the program cut to the part, which
        # the standing-only check above excludes
        fin = np.isfinite(judge) & np.isfinite(E)
        over = float(np.max(np.where(fin, E - judge, -np.inf)))
        under = float(np.max(np.where(fin, judge - E, -np.inf)))
        print("rrstock(b) every cell: max over %.4f mm, max under %.4f mm"
              % (over, under))
        assert over <= RR_TOL and under <= RR_TOL, (
            "engine after-finish replay differs from the judge: over %.4f, "
            "under %.4f mm" % (over, under))


def test_rrstock_replay_matches_analytic_stamp():
    """RR-STOCK independence check (coordinator): replay_stock is a port of
    the judge's stamping, so a shared bug would blind both - compare it with
    heights computed HERE, analytically. Flat stock top Z10 on a 0.1 mm grid;
    one straight G1 at Z8 along X (-5 -> 5, Y0) with (1) a 6 mm ball: away
    from the ends every cell |y| < 3 must read 8 + 3 - sqrt(9 - y^2), cells
    |y| > 3 stay 10; (2) a 6 mm flat: cells |y| <= 3 read 8, the rest 10.
    Checked on |x| <= 3.5 (the end caps are not straight-line analytic)."""
    from engine.entry_depth import replay_stock
    moves = [{"g": 0, "x": -5.0, "y": 0.0, "z": 20.0},
             {"g": 0, "z": 8.0}, {"g": 1, "x": 5.0, "y": 0.0, "z": 8.0},
             {"g": 0, "z": 20.0}]
    with tempfile.TemporaryDirectory() as td:
        for kind, corner in (("ball", 3.0), ("flat", 0.0)):
            A, x0, y0, c = replay_stock(moves, 6.0, corner,
                                        os.path.join(td, kind + ".npy"),
                                        box=(-10.0, 10.0, -10.0, 10.0),
                                        top_z=10.0)
            ny, nx = A.shape
            xs = x0 + (np.arange(nx) + 0.5) * c
            ys = y0 + (np.arange(ny) + 0.5) * c
            X, Y = np.meshgrid(xs, ys)
            m = (np.abs(X) <= 3.5) & (np.abs(Y) <= 5.0)
            if kind == "ball":
                exp = np.where(np.abs(Y) < 3.0,
                               np.minimum(10.0, 8.0 + 3.0 - np.sqrt(
                                   np.maximum(9.0 - Y * Y, 0.0))), 10.0)
            else:
                exp = np.where(np.abs(Y) <= 3.0, 8.0, 10.0)
            err = float(np.max(np.abs(A[m] - exp[m])))
            print("rrstock analytic %s: max |replay - analytic| %.2e mm "
                  "over %d cells" % (kind, err, int(m.sum())))
            assert err <= 1e-6, "%s replay differs from the analytic " \
                "stamp by %.4f mm" % (kind, err)


if __name__ == "__main__":
    for fn in (test_hemisphere_on_plate, test_cone_60deg,
               test_slot_narrower_than_ball, test_plate_at_floor,
               test_cylinder_boss_wall, test_no_duplicate_raster_rows,
               test_cl_jump_between_grid_points_posts_zero_below_cl,
               test_contour_vs_analytic_hemisphere,
               test_contour_vs_analytic_cone,
               test_gap_split_and_verified_link,
               test_flat_plate_length_and_links,
               test_two_boss_rapid_over_boss,
               test_rest_mask_units,
               test_rest_pass_placeholder,
               test_stock_out_roundtrip,
               test_link_plan_stock_ridge,
               test_stock_from_ridge_rapids,
               test_shank_deep_wall_short_flute,
               test_shank_deep_wall_long_flute,
               test_rest_pass_table_tool, test_shank_net_keeps_source_index,
               test_holder_drop_tall_boss,
               test_holder_stock_ridge_along_path,
               test_shank_t31_wall_13mm,
               test_ramp_vertices_never_below_verified_path,
               test_fe5e_ramp_top_clear_of_ridge,
               test_fe5t_public_ramp_top_clear_of_ridge,
               test_fe5f_skip_bore_entries,
               test_fe5fb_fragment_trim_keeps_surface,
               test_fe5fb_real_bore_surface_kept,
               test_fe5fc_buried_ends_keep_middle,
               test_fe5fc_degenerate_pass_never_plunged,
               test_floor_dip_split_finish_and_rest,
               test_floor_pad_rows_inside_stock_box,
               test_fe5g_no_lifted_vertex_in_constant_z_pass,
               test_fe5g_scene_vertices_never_below_cl,
               test_fe5g_net_ramps_and_trims_inpass_drop,
               test_fe5h_entry_estimate_not_below_true_depth,
               test_rrstock_rough_handoff_not_below_judge,
               test_rrstock_finish_handoff_matches_judge,
               test_rrstock_replay_matches_analytic_stamp):
        t = __import__("time").time()
        fn()
        print("%s OK in %.1fs" % (fn.__name__, __import__("time").time() - t))
    print("ALL FINISH TESTS PASSED")
