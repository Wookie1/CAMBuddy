#!/usr/bin/env python3
"""Task D item 3: like-for-like roughing benchmark, ours vs Fusion OVERALL
ROUGHING (1001.nc split at "(INSERT CONTOUR)"), same tool (12.7 bull, corner
0.127), same part heightfield (0.5 mm) and stock box. Reads the two zmap JSONs
and writes out/bench_rough.json side by side."""
import json

ours = json.load(open("out/zmap_roughD.json"))
fus = json.load(open("out/zmap_fusion_roughD.json"))


def metrics(r):
    return {
        "gouges": r["gouges"],
        "rapid_collisions": r["rapid_collisions"]["count"],
        "rapid_collision_first_line": r["rapid_collisions"]["first_line"],
        "leftover_mm": {"mean": round(r["leftover"]["mean"], 3),
                        "p95": round(r["leftover"]["p95"], 3),
                        "max": round(r["leftover"]["max"], 3)},
        "within_0p5mm_fraction": round(r["within_0p5mm_fraction"], 4),
        "cutting_length_mm": r["cutting_length_mm"],
        "cycle_time_s": r["cycle_time_s"],
    }


bench = {
    "comparison": "single Adaptive rough (ours, plain fallback) vs Fusion "
                  "OVERALL ROUGHING section of reference/1001.nc",
    "common": {
        "tool": {"type": "bull", "dia_mm": 12.7, "corner_mm": 0.127},
        "part_heightfield": ours["part"],
        "cell_mm": ours["cell"],
        "stock_box": ours["stock_box"],
    },
    "ours": {
        "gcode": ours["gcode"],
        "op": "AdaptiveRoughFusion (FreeCAD/VibeCAD Path Adaptive, plain: "
              "ModelAwareExperiment failed to the floor with 'TypeError: "
              "undefined curve type' from degenerate BSpline edges, see "
              "out/run_cam_D.log)",
        "params": {"stepdown_mm": 1.9, "start_depth_mm": 60.96,
                   "final_depth_mm": 25.1, "stepover_percent": 15.0,
                   "stock_to_leave_mm": 0.3,
                   "cut_feed_mm_min": 3429.0, "plunge_feed_mm_min": 1270.0},
        **metrics(ours),
    },
    "fusion": {
        "gcode": fus["gcode"],
        "op": "OVERALL ROUGHING, T3 D=0.5in CR=0.005in bullnose, S7500 "
              "(lines 1-40321 of reference/1001.nc, G20)",
        "params_measured": {"stepdown_mm": 1.9,
                            "cut_feed_mm_min": 3429.0,
                            "ramp_feed_mm_min": 1270.0,
                            "stepover_mm_median": 2.0},
        **metrics(fus),
    },
    "notes": [
        "Ours is a purely-2D plain Adaptive bounded by the stock outline (the "
        "model-aware mode that would respect walls errors on this STEP's "
        "degenerate edges), so it cuts through every feature above Z 25.1: the "
        "gouge/leftover deltas vs Fusion reflect that mandated fallback, not a "
        "tool-shape mismatch.",
        "Fusion roughing section carries no G41/G42 (comp starts at INSERT "
        "CONTOUR), so the wear-model sim is exact for this split.",
        "Cycle times: feed moves at their F words, rapids assumed 15000 mm/min.",
    ],
}
with open("out/bench_rough.json", "w") as fh:
    json.dump(bench, fh, indent=2)
print(json.dumps(bench, indent=2))
