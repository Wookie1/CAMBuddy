#!/usr/bin/env python3
"""RR-STOCK2 red tests (run on the UNCHANGED code first).

(a) test_rrstock2_restrough_handoff_not_below_judge: engine.cli rest-rough
    gets --stock-out - a replay_stock of its OWN emitted ball moves onto its
    --stock-from input stock. Judge the SAME emitted program with verify.zmap
    (0.1 mm grid, --stock-in = the same input stock); at every cell with
    standing stock the engine handoff must be >= judge - 0.1 mm.
(b) test_rrstock2_skip_clusters_have_reason: every FE5f skip cluster carries
    a non-empty "reason"; a cluster centred over a THROUGH OPENING (no part
    at its centre) gets "left_for_hole_op_or_another_setup", everything else
    "entry_deeper_than_floor_no_legal_ramp" (unit call on the classifier).

Run (small-test lane, VibeCAD python):
    <lane> /Applications/VibeCAD.app/Contents/Resources/bin/python -c \
        "import sys; sys.path.insert(0,'.'); import engine.test_rrstock2 as t; t.<name>()"
"""
import argparse
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

import zmap  # noqa: E402 (tests may import verify; engine code must not)

CELL = 0.1
RR_TOL = 0.1  # mm, brief's TOL


def test_rrstock2_restrough_handoff_not_below_judge():
    """RR-STOCK2 red (a): rest-rough --stock-out replays its emitted ball
    program onto its --stock-from stock; compare with zmap judging the SAME
    program on the same input stock, 0.1 mm grid."""
    import subprocess
    from engine import cli as climod
    from engine import model as emod
    from engine.test_engine import _rr1b_pocket_scene

    # the CLI must OFFER the flag (red on unchanged code: no --stock-out)
    r = subprocess.run([sys.executable, "-m", "engine.cli", "rest-rough",
                        "--help"], cwd=ROOT, capture_output=True, text=True)
    assert any(ln.strip().startswith("--stock-out")
               for ln in r.stdout.splitlines()), \
        "engine.cli rest-rough has no --stock-out flag (rc=%d)" % r.returncode

    lo, hi = 10.0, 30.0
    surf, stock, _, _ = _rr1b_pocket_scene((lo, hi))
    # the CLI's STEP tessellation is FreeCAD-bound; the scene IS a synthetic
    # part, so hand the CLI this exact surf instead of a tessellated STEP
    emod.step_to_stl = lambda step, *a, **k: step
    emod.load_surf = lambda stl: surf
    dia = 9.525
    with tempfile.TemporaryDirectory() as td:
        stockp = os.path.join(td, "stock_in.npy")
        np.save(stockp, stock[0])
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": stock[1], "y0": stock[2], "cell": stock[3]},
                      fh)
        ngc = os.path.join(td, "rest_rough.ngc")
        eng_stock = os.path.join(td, "stock_after_restrough_engine.npy")
        ns = argparse.Namespace(
            step="synth.step", stock_from=stockp, out=ngc,
            tool="ball:%.3f" % dia, floor=24.0, stepdown=2.0, ae=1.905,
            rest_leave=0.2, min_excess=0.5, min_helix_r=1.903,
            ramp_angle_deg=2.0, cut_feed=2280.0, ramp_feed=850.0,
            spindle=8000, clearance=None, zb_floor=0.5, shallow=0.25,
            workers=4, stats_json=None, post="neutral", program=1003,
            op_name="REST ROUGH", metric=False, tool_number=None,
            stock_out=eng_stock)
        rc = climod.rest_rough_main(ns)
        assert rc == 0 and os.path.exists(ngc)
        assert os.path.exists(eng_stock), \
            "rest-rough --stock-out wrote no handoff stock"

        # judge: zmap replay of the SAME emitted program, 0.1 mm grid,
        # stock-in = the same (uniform 30.0) input stock
        n = int(round(40.0 / CELL))
        xs = (np.arange(n) + 0.5) * CELL
        Xc, Yc = np.meshgrid(xs, xs)
        part = np.where((Xc >= lo) & (Xc <= hi) & (Yc >= lo) & (Yc <= hi),
                        24.0, 30.0)
        stock0 = np.full((n, n), 30.0)
        with open(ngc) as fh:
            gmv = zmap.parse_gcode(fh.read())
        res = zmap.simulate(gmv, part, CELL, 0.0, 0.0,
                            (0.0, 40.0, 0.0, 40.0, 20.0, 30.0),
                            tool="ball", dia=dia, stock_init=stock0)
        judge = res["stock"]
        E = np.load(eng_stock)
        with open(eng_stock[:-4] + ".json") as fh:
            emeta = json.load(fh)
        assert abs(float(emeta["x0"])) < 1e-9 \
            and abs(float(emeta["y0"])) < 1e-9 \
            and abs(float(emeta["cell"]) - CELL) < 1e-9, \
            "engine replay grid %s != judge grid" % emeta
        assert E.shape == judge.shape, "grid shape mismatch"
        standing = np.isfinite(judge) & (judge > part + 0.01)
        deficit = np.where(standing, judge - E, -np.inf)
        viol = standing & (deficit > RR_TOL)
        n_v = int(viol.sum())
        worst = float(np.max(deficit)) if standing.any() else 0.0
        print("rrstock2(a): standing=%d cells, handoff below judge by "
              ">%.2f at %d cells, max deficit %.3f mm"
              % (int(standing.sum()), RR_TOL, n_v, worst))
        assert n_v == 0, (
            "engine rest-rough handoff is BELOW the judge replay at %d "
            "standing cells (max %.3f mm)" % (n_v, worst))
        # two-sided (coordinator): a handoff that wrote its INPUT stock back
        # unchanged passes the one-sided check; it must also not stand
        # above what the program really left anywhere
        fin = np.isfinite(judge) & np.isfinite(E)
        over = float(np.max(np.where(fin, E - judge, -np.inf)))
        under = float(np.max(np.where(fin, judge - E, -np.inf)))
        print("rrstock2(a) two-sided: max over %.3f mm, max under %.3f mm "
              "(TOL %.2f)" % (over, under, RR_TOL))
        assert over <= RR_TOL, (
            "engine rest-rough handoff stands ABOVE the judge replay by "
            "%.3f mm - the handoff must be the program's own replay" % over)


def test_rrstock2_skip_clusters_have_reason():
    """RR-STOCK2 red (b): the FE5f through-bore scene (the
    test_fe5f_skip_bore_entries setup) - every skip cluster carries a
    non-empty reason and the bore cluster is classified
    left_for_hole_op_or_another_setup; the classifier unit call shows a
    cluster NOT over a through opening gets
    entry_deeper_than_floor_no_legal_ramp."""
    from engine import model
    from engine.finish import finish
    from engine.test_finish import bored_cyl_stl

    cell, top, boss_r, bore_r = 0.5, 14.0, 8.0, 4.8
    stock_bore = top + 2.0
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
        A = np.full(CX.shape, top + 0.3)
        A[R <= bore_r] = stock_bore
        np.save(stockp, A)
        with open(stockp[:-4] + ".json", "w") as fh:
            json.dump({"x0": gx0, "y0": gy0, "cell": cell}, fh)
        moves, stats = finish(surf, stl_path=stl, tool=("ball", 9.525, 0.0),
                              stepover=1.5, floor_z=6.0, threads=4,
                              stock_from=stockp, ramp_angle_deg=2.0)
        clusters = stats.get("fe5_skipped_clusters", [])
        assert clusters, "no skip clusters reported"
        for c in clusters:
            assert c.get("reason"), "skip cluster without reason: %s" % c
        d0, c0 = min((math.hypot(c["center"][0], c["center"][1]), c)
                     for c in clusters)
        assert d0 <= 1.0, \
            "no skip cluster centred on the bore axis: %s" % (clusters,)
        assert c0["reason"] == "left_for_hole_op_or_another_setup", \
            "bore cluster reason is %r, want left_for_hole_op_or_another_" \
            "setup" % c0["reason"]

    # unit call: the classifier over the SAME bored-cyl part - the bore
    # axis has no part (through opening); r 6.5 is solid boss at z 14
    # (above the floor 6.0): not a through opening
    from engine.finish import _fe5_skip_reason
    cl = [{"center": [0.0, 0.0], "bbox": [-1.0, 1.0, -1.0, 1.0],
           "max_depth_mm": 5.0, "n": 2},
          {"center": [6.5, 0.0], "bbox": [6.0, 7.0, -0.5, 0.5],
           "max_depth_mm": 3.0, "n": 1}]
    out = _fe5_skip_reason(cl, surf, 6.0)
    assert out[0]["reason"] == "left_for_hole_op_or_another_setup", out
    assert out[1]["reason"] == "entry_deeper_than_floor_no_legal_ramp", out
    print("rrstock2(b): %d cluster(s); bore cluster reason %r; unit call "
          "classified %r / %r"
          % (len(clusters), c0["reason"], out[0]["reason"],
             out[1]["reason"]))


if __name__ == "__main__":
    for fn in (test_rrstock2_skip_clusters_have_reason,
               test_rrstock2_restrough_handoff_not_below_judge):
        t = __import__("time").time()
        fn()
        print("%s OK in %.1fs" % (fn.__name__, __import__("time").time() - t))
    print("RRSTOCK2 ENGINE TESTS PASSED")
