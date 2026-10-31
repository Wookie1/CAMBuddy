"""TASK SP-P3C-1 tests: the zmap judges run as their own chain beside the
engine chain (connector/runner.py). Unit only - every step is a fake
_spawn; no engine, no FreeCAD, no network.

Run: /opt/homebrew/bin/python3 -m pytest connector/test_spp3c.py -q

This file also keeps a REFERENCE COPY of the pre-change (serial)
run_slope_split_finish as serial_run_slope_split_finish(); the
identical-outputs test compares the two-chain runner against it.
"""
import hashlib
import json
import os
import sys
import threading
import time

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
from runner import (EngineError, FINISH_ENGAGE_FACTOR,  # noqa: E402
                    ROUGH_ENGAGE_FACTOR, ZMAP_JOBS, _check_zmap_gates,
                    _origin_flags, _stock_args, _tool_number,
                    check_tool_entry, posted_units)
from test_connector import SLOPE_GOOD_INPUTS  # noqa: E402

PY = "/opt/homebrew/bin/python3"
STEP = os.path.join(HERE, "unused.step")

ENGINE_STEPS = ["prepare", "rough", "tess", "finish", "post", "clcheck",
                "rest", "post_rest", "clcheck_rest"]
JUDGE_STEPS = ["hf01", "zmap_rough", "zmap_finish", "zmap_rest"]


def step_name(argv):
    """Classify a slope-split _spawn argv into its step name."""
    a = list(argv)
    if any(t.endswith("heightfield.py") for t in a):
        return "hf01"
    if any(t.endswith("_tessellate.py") for t in a):
        return "tess"
    if any(t.endswith("probe_clcheck.py") for t in a):
        return "clcheck_rest" if a[2].endswith("rest.nc") else "clcheck"
    if "verify.zmap" in a:
        return {"rough.nc": "zmap_rough", "finish.nc": "zmap_finish",
                "rest.nc": "zmap_rest"}[os.path.basename(
                    a[a.index("verify.zmap") + 1])]
    if "engine.cli" in a:
        sub = a[a.index("engine.cli") + 1]
        if sub == "prepare":
            return "prepare"
        if sub == "rough":
            return "rough"
        if sub == "finish":
            return "rest" if "--rest-from" in a else "finish"
        if sub == "post":
            out = a[a.index("--out") + 1]
            return "post_rest" if out.endswith("rest.nc") else "post"
    raise AssertionError("unknown step: %r" % a)


ZMAP_REPORT = {
    "gouges": {"count": 0, "max_depth": 0.0, "worst_xy": None},
    "rapid_collisions": {"count": 0, "first_line": None},
    "outside_grid": {"count": 0, "first_line": None},
    "over_flute": {"count": 0, "max_depth": 0.0, "worst_xy": None,
                   "first_line": None},
    "holder": {"status": "checked", "name": "BT30-ER20-60",
               "stickout_mm": 60.0, "dimension_source": "drawing"},
    "holder_hits": {"count": 0, "max_intrusion": 0.0, "worst_xy": None,
                    "first_line": None},
    "leftover": {"max": 0.0, "mean": 0.0, "p95": 0.0},
    "within_0p5mm_fraction": 1.0,
    "cycle_time_s": 1.0,
    "cutting_length_mm": 100.0,
    "rapid_length_mm": 10.0,
    "engagement": {"threshold_mm": 0.45, "count": 0, "max_mm": 0.0,
                   "spikes": []},
    "plunge": {"ramp_angle_deg": 3.0, "count": 0, "flags": []},
}


def _write_output(self, a, name, json_out, extra_env):
    """Canned outputs for one fake step (same shapes the existing
    connector-test fakes write)."""
    def opt(flag):
        return a[a.index(flag) + 1] if flag in a else None

    if name == "prepare":
        with open(os.path.join(self.work, "o.step"), "w") as fh:
            fh.write("ISO-10303-21; fake oriented step\nEND;")
        with open(os.path.join(self.work, "prepare.json"), "w") as fh:
            json.dump({"step": os.path.join(self.work, "o.step"),
                       "hf": os.path.join(self.work, "hf.npz"),
                       "stock": [-10.0, 10.0, -10.0, 10.0, -1.0, 0.4]}, fh)
    elif name == "hf01":
        np.save(extra_env["HF_OUT"], np.full((8, 8), 0.4))
        with open(os.path.splitext(extra_env["HF_OUT"])[0] + ".json",
                  "w") as fh:
            json.dump({"step_sha256": hashlib.sha256(
                           open(extra_env["STEP_IN"], "rb").read()
                       ).hexdigest(),
                       "x0": -12.0, "y0": -12.0,
                       "cell": float(extra_env["CELL"]),
                       "tess_tol": float(extra_env.get("TESS_TOL", 0.01))},
                      fh)
    elif name == "tess":
        with open(extra_env["STL_OUT"], "wb") as fh:
            fh.write(b"solid fake\nendsolid fake\n")
    elif name in ("clcheck", "clcheck_rest"):
        if json_out is not None:
            json_out.append({"below_cl": 0, "points": 42,
                             "max_depth_mm": 0.0})
    elif name in ("zmap_rough", "zmap_finish", "zmap_rest"):
        so = opt("--stock-out")
        if so:
            np.save(so, np.full((8, 8), -1.0))
        with open(opt("--out-json"), "w") as fh:
            json.dump(ZMAP_REPORT, fh)
    else:  # rough / finish / rest / post / post_rest
        out = opt("--out")
        if out:
            with open(out, "w") as fh:
                fh.write(("G21" if "--metric" in a else "G20") +
                         " G90\nG0 X0. Y0. Z5.\n")
        sj = opt("--stats-json")
        if sj:
            with open(sj, "w") as fh:
                json.dump({"levels": [{"skipped": False}], "n_moves": 10},
                          fh)
        so = opt("--stock-out")
        if so:
            np.save(so, np.full((8, 8), 0.2))


def make_fake(durations=None, fail=None):
    """A fake EngineRun._spawn: records start/end times per step, sleeps
    out the simulated duration, writes canned outputs, optionally raises
    for a named step. rec["argv"][name] keeps the LAST argv of each step."""
    durations = durations or {}
    fail = fail or {}
    rec = {"events": [], "argv": {}}
    lock = threading.Lock()

    def fake(self, argv, lo, hi, on_progress, json_out=None,
             extra_env=None):
        a = list(argv)
        name = step_name(a)
        with lock:
            rec["events"].append(("start", name, time.time()))
            rec["argv"][name] = a
        if on_progress:
            on_progress(lo, name)
        dur = durations.get(name, 0.0)
        if dur:
            time.sleep(dur)
        _write_output(self, a, name, json_out, extra_env)
        with lock:
            rec["events"].append(("end", name, time.time()))
        if name in fail:
            raise fail[name]
        return None

    return fake, rec


def spans(rec):
    """{step: {"start": t, "end": t}} from a fake's recorded events."""
    out = {}
    for kind, name, t in rec["events"]:
        d = out.setdefault(name, {})
        d["start" if kind == "start" else "end"] = t
    return out


# --------------------------------------------------------------------------
# Reference copy of the pre-change serial run_slope_split_finish (main
# 2da9125 / task commit 52a73a8, connector/runner.py lines 1008-1605),
# dedented to module level and renamed. Do not edit: the identical-outputs
# test compares the two-chain runner against exactly this code path.
# --------------------------------------------------------------------------
def serial_run_slope_split_finish(self, step_path, values, on_progress=None):
    """Roughing first, then slope-split finishing (a finishing ball must
    never meet raw stock). Returns (result, files) with BOTH posted LNC
    programs; zmap judges the chain: roughing from full stock
    (--stock-out), then the finish with --stock-in."""
    py = self.cfg["engine_python"]
    fc = os.path.join(os.path.dirname(py), "freecadcmd")
    repo = self.cfg["repo_root"]

    # 0) tool numbers up front: refuse a missing finish-tool number
    #    before any engine work (the run reports failed, clearly).
    #    Track 2: every number comes from the effective table (library +
    #    the document's job renumbering)
    self._load_tools(values)
    finish_number = self._finish_tool_number(values)
    rough_number = _tool_number(self.cfg, {
        "tool_type": values["rough_tool_type"],
        "tool_diameter": values["rough_tool_diameter"],
        "corner_radius": values["rough_corner_radius"]},
        self.tools["tools"])

    # 0b) optional corner rest pass (task CR): the rest tool must be a
    #     ball in tools/x7_tools.json with a known holder - an unknown
    #     tool or a missing holder fails the run before any engine work,
    #     exactly like the finish tool. Absent rest_tool_number = the
    #     rough + finish chain unchanged.
    rest_number = values.get("rest_tool_number")
    rest = None
    if rest_number:
        rest_number = int(rest_number)
        rest = check_tool_entry(rest_number, self._table_file())
        if not rest["holder"]:
            raise EngineError(
                "rest tool T%d has no holder in tools/x7_tools.json: the "
                "rest pass is never judged without the holder clearance "
                "check" % rest_number, code="rest_tool_no_holder",
                field="rest_tool_number", got=rest_number)
        if rest["type"] != "ball":
            raise EngineError(
                "rest tool T%d is a %s, not a ball: the corner rest pass "
                "runs with a ball nose from tools/x7_tools.json"
                % (rest_number, rest["type"]), code="rest_tool_not_ball",
                field="rest_tool_number", got=rest_number)
        if rest["diameter_mm"] >= values["tool_diameter"]:
            raise EngineError(
                "rest tool T%d D=%.3f mm is not smaller than the finishing "
                "ball D=%.3f mm: the rest pass cuts with the smaller ball"
                % (rest_number, rest["diameter_mm"],
                   values["tool_diameter"]), code="rest_tool_too_big",
                field="rest_tool_number", got=rest_number)
    self._check_library_geometry([rough_number, finish_number]
                                 + ([rest_number] if rest else []))

    # stage boundaries: with the rest pass the generation stages are
    # squeezed so progress stays monotone and ends at 1.0
    if rest:
        P = {"prepare": (0.02, 0.10), "hf": (0.10, 0.14),
             "rough": (0.14, 0.38), "tess": (0.38, 0.42),
             "finish": (0.42, 0.60), "post": (0.60, 0.63),
             "clcheck": (0.63, 0.66), "zmap_rough": (0.66, 0.76),
             "zmap_finish": (0.76, 0.84), "rest": (0.84, 0.90),
             "post_rest": (0.90, 0.92), "clcheck_rest": (0.92, 0.94),
             "zmap_rest": (0.94, 0.995)}
    else:
        P = {"prepare": (0.02, 0.12), "hf": (0.12, 0.17),
             "rough": (0.17, 0.45), "tess": (0.45, 0.50),
             "finish": (0.50, 0.72), "post": (0.72, 0.76),
             "clcheck": (0.76, 0.80), "zmap_rough": (0.80, 0.90),
             "zmap_finish": (0.90, 0.97)}

    # 1) orient + stock box + part heightfield (for the roughing clip;
    #    grid covers stock + largest tool radius of the run + margin)
    max_tool_r = max(values["tool_diameter"],
                     values["rough_tool_diameter"]) / 2.0
    self._spawn([py, "-m", "engine.cli", "prepare",
                "--step", step_path, "--out-dir", self.work,
                "--orient", values["orientation"],
                "--origin", values.get("origin") or "model_origin",
                *_stock_args(values),
                "--stock-top", "%.4f" % values["stock_top"],
                "--stock-bottom", "%.4f" % values["stock_bottom"],
                "--cell", "0.5",
                "--tool-r", "%.4f" % max_tool_r], *P["prepare"],
                on_progress)
    with open(os.path.join(self.work, "prepare.json")) as fh:
        prep = json.load(fh)
    stock = prep["stock"]
    floor = stock[4] + values["floor_z"]

    # 2) fresh zmap part heightfield (verify/heightfield.py, 0.01 mm
    #    tess, 0.1 mm cell) - independent of the roughing clip grid.
    #    The shared builder covers STOCK_BOX + TOOL_R + MARGIN: zmap
    #    exits non-zero when the stock box or a tool footprint extends
    #    beyond its grid.
    # task HC: remove any stale artifacts from a reused run dir before
    # rebuilding; after each build require the fresh files to exist and
    # the sidecar to pin this run's STEP, cell and tess tolerance
    fr = self._freshness()
    step_sha = fr.sha256_file(prep["step"])
    hf01 = os.path.join(self.work, "part_hf01.npy")
    fr.remove_stale(hf01)
    self._spawn([fc, os.path.join(repo, "verify", "heightfield.py")],
                0.12, 0.17, on_progress,
                extra_env={"STEP_IN": prep["step"], "HF_OUT": hf01,
                          "CELL": "0.1", "TESS_TOL": "0.01",
                          "STOCK_BOX": " ".join("%.4f" % v
                                                for v in stock[:4]),
                          "TOOL_R": "%.4f" % max_tool_r})
    try:
        fr.require_fresh(hf01, step_sha256=step_sha, cell=0.1,
                         tess_tol=0.01)
    except OSError as e:
        raise EngineError(str(e), code="stale_artifact")

    # 3) adaptive roughing (LNC post, full stock); the finish and the rest
    #    pass need the engine's own post-roughing stock for their rapid /
    #    lift / holder clearance (--stock-from), so the rough exports it.
    #    Task UN: every post honors the requested units (--metric only
    #    for mm; inch posts emit G20 with a matching 0.00254 post grid)
    metric = values["units"] == "mm"
    post_grid = "0.001" if metric else "0.00254"
    posted = {}
    nc = os.path.join(self.work, "rough.nc")
    stats_path = os.path.join(self.work, "rough_stats.json")
    rough_stock_out = os.path.join(self.work, "stock_after_rough_engine.npy")
    argv = [py, "-m", "engine.cli", "rough",
            "--step", prep["step"],
            "--stock", *[("%.4f" % v) for v in stock],
            "--tool", "%s:%.4f:%.4f" % (values["rough_tool_type"],
                                       values["rough_tool_diameter"],
                                       values["rough_corner_radius"]),
            "--out", nc, "--floor", "%.4f" % floor,
            "--leave", "%.4f" % values["rough_stock_to_leave"],
            "--stepdown", "%.4f" % values["rough_stepdown"],
            "--optimal-load-mm", "%.4f" % values["rough_optimal_load"],
            "--stepup", "%.4f" % values["rough_rest_stepup"],
            "--hf", prep["hf"], "--min-rest", "0.5",
            "--cut-feed", "%.1f" % values["feed"],
            "--ramp-feed", "%.1f" % values["ramp_feed"],
            "--spindle", str(int(values["rpm"])),
            "--post", "lnc", "--program",
            str(int(values["program_number"])),
            "--tool-number", str(rough_number),
            *self._tools_json_args(),
            "--json-progress", "--stats-json", stats_path]
    # always: the finish (and any rest pass) plans its rapids, lifts and
    # holder clearance against this stock - without it the engine only
    # adds 1 mm over the part and rapids crossed roughing terraces
    fr.remove_stale(rough_stock_out)
    argv += ["--stock-out", rough_stock_out]
    argv += _origin_flags(values)
    if metric:
        argv += ["--metric"]
    argv += self._load_limit_args(values)
    self._spawn(argv, *P["rough"], on_progress)
    posted["rough.nc"] = posted_units(nc, values["units"])

    # 4) tessellate the oriented model (finish input + clcheck probe);
    #    stale model.stl removed first, fresh non-empty output asserted
    stl = os.path.join(self.work, "model.stl")
    fr.remove_stale(stl)
    self._spawn([fc, os.path.join(repo, "engine", "_tessellate.py")],
                0.45, 0.50, on_progress,
                extra_env={"STEP_IN": prep["step"], "STL_OUT": stl,
                          "TOL": "0.01"})
    try:
        fr.require_stl(stl)
    except OSError as e:
        raise EngineError(str(e), code="stale_artifact")

    # 5) slope-split finishing (neutral G-code). PQ: the engine snaps the
    #    emitted points to the output grid matching this op's post units
    #    (metric post -> 0.001 mm; an inch post uses 0.00254 so PQ's
    #    snap stays a no-op on posting)
    fin_neutral = os.path.join(self.work, "finish_neutral.ngc")
    fin_stats = os.path.join(self.work, "finish_stats.json")
    # RR-STOCK: the engine replays its own emitted finish moves into a
    # 0.1 mm stock; the rest pass plans on THAT (never on a judge stock)
    stock_fin_engine = os.path.join(
        self.work, "stock_after_finish_engine.npy")
    fr.remove_stale(stock_fin_engine)
    self._spawn([py, "-m", "engine.cli", "finish",
                "--stl", stl,
                "--tool", "ball:%.4f" % values["tool_diameter"],
                "--out", fin_neutral,
                "--stepover", "%.4f" % values["stepover"],
                "--stepdown", "%.4f" % values["stepdown"],
                "--slope-threshold", "%.2f" % values["slope_threshold"],
                "--floor", "%.4f" % floor,
                "--cut-feed", "%.1f" % values["feed"],
                "--ramp-feed", "%.1f" % values["ramp_feed"],
                "--ramp-angle-deg",
                "%.2f" % (values.get("ramp_angle_deg") or 2.0),
                "--spindle", str(int(values["rpm"])),
                "--post-grid-mm", post_grid,
                "--stock-from", rough_stock_out,
                "--stock-out", stock_fin_engine,
                *self._tools_json_args(),
                "--stats-json", fin_stats], 0.50, 0.72, on_progress)

    # 6) post to LNC in the requested units (task UN: --metric only for
    #    mm, inch posts emit G20; the posted artifact is what clcheck
    #    judges); header carries run-after-roughing
    fin = os.path.join(self.work, "finish.nc")
    argv_fp = [py, "-m", "engine.cli", "post",
               "--in", fin_neutral, "--out", fin,
               "--program", str(int(values["program_number"])),
               "--op-name", "SLOPE SPLIT FINISH (RUN AFTER ROUGHING)",
               "--tool-number", str(finish_number)]
    argv_fp += self._tools_json_args()
    argv_fp += _origin_flags(values)
    if metric:
        argv_fp += ["--metric"]
    self._spawn(argv_fp, 0.72, 0.76, on_progress)
    posted["finish.nc"] = posted_units(fin, values["units"])

    # 7) probe_clcheck on the posted finish output (must be 0)
    cl_lines = []
    self._spawn([py, os.path.join(repo, "engine", "probe_clcheck.py"),
                fin, stl, "%.4f" % values["tool_diameter"]],
               0.76, 0.80, on_progress, json_out=cl_lines)
    cl = cl_lines[-1] if cl_lines else {}
    if cl.get("below_cl", 1) > 0:
        raise EngineError(
            "probe_clcheck: %d points below CL by >0.005 mm in the "
            "finish program (max %.3f mm) - run failed"
            % (cl["below_cl"], cl.get("max_depth_mm", 0.0)),
            code="clcheck", where={"program": "finish.nc"})

    # 8) chained zmap: roughing from full stock (--stock-out), then the
    #    finish with the roughed stock as --stock-in
    check_rough = os.path.join(self.work, "check_rough.json")
    stock_out = os.path.join(self.work, "stock_after_rough.npy")
    self._spawn([py, "-m", "verify.zmap", nc, "--jobs", str(ZMAP_JOBS),
                "--part", hf01,
                "--tool", values["rough_tool_type"],
                "--dia", "%.4f" % values["rough_tool_diameter"],
                "--corner", "%.4f" % values["rough_corner_radius"],
                "--stock", *[("%.4f" % v) for v in stock],
                "--flute", "%.1f" % values["rough_flute_length"],
                "--optimal-load", "%.4f" % values["rough_optimal_load"],
                "--engage-max", "%.4f"
                % (ROUGH_ENGAGE_FACTOR * values["rough_optimal_load"]),
                "--tool-number", str(rough_number),
                *self._tools_json_args(),
                "--out-json", check_rough,
                "--stock-out", stock_out], *P["zmap_rough"], on_progress)
    check_finish = os.path.join(self.work, "check_finish.json")
    png_path = os.path.join(self.work, "preview.png")
    # Finish engagement threshold: 1.5 x the finish stepover (distance
    # between finish passes) rather than the roughing optimal load; finish
    # passes are much lighter and the roughing threshold would over-flag
    # them. Passed explicitly so zmap never derives a roughing threshold.
    # With a rest pass, the finish also exports the stock it leaves: the
    # rest toolpath is generated from it (--rest-from) and judged on it
    # (--stock-in). zmap writes only the .npy, so the runner carries the
    # grid geometry in the heightfield sidecar convention.
    stock_finish = os.path.join(self.work, "stock_after_finish.npy")
    stock_rest = os.path.join(self.work, "stock_after_rest.npy")
    argv_f = [py, "-m", "verify.zmap", fin, "--jobs", str(ZMAP_JOBS),
              "--part", hf01,
              "--tool", "ball",
              "--dia", "%.4f" % values["tool_diameter"],
              "--corner", "%.4f" % (values["tool_diameter"] / 2.0),
              "--stock-in", stock_out,
              "--engage-max", "%.4f"
              % (FINISH_ENGAGE_FACTOR * values["stepover"]),
              "--tool-number", str(finish_number),
              *self._tools_json_args(),
              "--out-json", check_finish]
    # the judge also checks the finish's flute/shank (over_flute), from
    # the same X7 table entry the engine's shank rule used
    fin_tool = check_tool_entry(finish_number, self._table_file())
    if fin_tool["flute_mm"] is not None:
        argv_f += ["--flute", "%.4f" % fin_tool["flute_mm"]]
    if fin_tool["shank_diameter_mm"] is not None:
        argv_f += ["--shank-dia", "%.4f" % fin_tool["shank_diameter_mm"]]
    if rest:
        fr.remove_stale(stock_finish)
    # TASK_VIEW3D: always export the finish's judged stock (the final
    # one when there is no rest pass) - same zmap call, no extra pass
    argv_f += ["--stock-out", stock_finish]
    if not rest:
        argv_f += ["--png", png_path]
    self._spawn(argv_f, *P["zmap_finish"], on_progress)
    with open(check_rough) as fh:
        check_r = json.load(fh)
    with open(check_finish) as fh:
        check_f = json.load(fh)
    _check_zmap_gates(check_r)
    _check_zmap_gates(check_f)

    # 9) optional corner rest pass (task CR): the smaller ball cuts only
    #    where the finish left more than min_rest mm standing, working
    #    from the stock the finish exported. Same gates as the finish:
    #    LNC post (program number +2, rest tool number), probe_clcheck
    #    with the rest ball diameter (0 below CL by >0.005 mm), chained
    #    zmap with --stock-in = the finish's --stock-out and the rest
    #    tool's flute/shank/tool-number/holder, then _check_zmap_gates.
    check_rest_path = os.path.join(self.work, "check_rest.json")
    rest_nc = os.path.join(self.work, "rest.nc")
    cl_rest = check_s = None
    if rest:
        # zmap --stock-out writes only the .npy; the engine reads a
        # heightfield's grid from its sidecar - the same geometry as the
        # judge heightfield this stock was computed on
        with open(os.path.splitext(hf01)[0] + ".json") as fh:
            hf_meta = json.load(fh)
        # merge, never overwrite: zmap's own sidecar carries the true
        # stock_box the rest judge needs for its below_stock_bottom gate
        sc = os.path.splitext(stock_finish)[0] + ".json"
        meta = {}
        if os.path.exists(sc):
            with open(sc) as fh:
                meta = json.load(fh)
        meta.update(x0=hf_meta["x0"], y0=hf_meta["y0"],
                    cell=hf_meta["cell"])
        with open(sc, "w") as fh:
            json.dump(meta, fh)

        # 9a) rest finish (neutral G-code): --tool is the previous (finish)
        #     ball, --rest-tool the smaller ball that does the cutting
        rest_neutral = os.path.join(self.work, "rest_neutral.ngc")
        rest_stats = os.path.join(self.work, "rest_stats.json")
        argv_rest = [py, "-m", "engine.cli", "finish",
                    "--stl", stl,
                    "--out", rest_neutral,
                    "--tool", "ball:%.4f" % values["tool_diameter"],
                    "--rest-from", stock_fin_engine,
                    "--rest-tool", "ball:%.4f" % rest["diameter_mm"],
                    "--min-rest", "%.4f" % (values.get("min_rest") or 0.5),
                    "--stock-from", rough_stock_out,
                    "--stepover", "%.4f" % values["stepover"],
                    "--stepdown", "%.4f" % values["stepdown"],
                    "--slope-threshold",
                    "%.2f" % values["slope_threshold"],
                    "--floor", "%.4f" % floor,
                    "--cut-feed", "%.1f" % values["feed"],
                    "--ramp-feed", "%.1f" % values["ramp_feed"],
                    "--ramp-angle-deg",
                    "%.2f" % (values.get("ramp_angle_deg") or 2.0),
                    "--spindle", str(int(values["rpm"])),
                    "--post-grid-mm", post_grid,
                    *self._tools_json_args(),
                    "--stats-json", rest_stats]
        if rest["flute_mm"] is not None:
            argv_rest += ["--flute", "%.4f" % rest["flute_mm"]]
        if rest["shank_diameter_mm"] is not None:
            argv_rest += ["--shank", "%.4f" % rest["shank_diameter_mm"]]
        if rest["stickout_mm"] is not None:
            argv_rest += ["--stickout", "%.4f" % rest["stickout_mm"]]
        if rest["holder"]:
            argv_rest += ["--holder", rest["holder"]]
        self._spawn(argv_rest, *P["rest"], on_progress)

        # 9b) post to LNC: program number +2, the rest tool's T/H; the
        #     neutral header names the rest tool, so carry its geometry;
        #     task UN: --metric only when mm is requested (else G20)
        argv_rp = [py, "-m", "engine.cli", "post",
                  "--in", rest_neutral, "--out", rest_nc,
                  "--program", str(int(values["program_number"]) + 2),
                  "--op-name", "REST PASS (RUN AFTER FINISH)",
                  "--tool-number", str(rest_number),
                  "--tool-kind", "ball",
                  "--dia", "%.4f" % rest["diameter_mm"],
                  "--corner", "%.4f" % (rest["diameter_mm"] / 2.0)]
        argv_rp += self._tools_json_args()
        argv_rp += _origin_flags(values)
        if metric:
            argv_rp += ["--metric"]
        self._spawn(argv_rp, *P["post_rest"], on_progress)
        posted["rest.nc"] = posted_units(rest_nc, values["units"])

        # 9c) probe_clcheck on the posted rest output with the rest ball
        #     (must be 0)
        cl_rest_lines = []
        self._spawn([py, os.path.join(repo, "engine",
                                       "probe_clcheck.py"),
                     rest_nc, stl, "%.4f" % rest["diameter_mm"]],
                    *P["clcheck_rest"], on_progress,
                    json_out=cl_rest_lines)
        cl_rest = cl_rest_lines[-1] if cl_rest_lines else {}
        if cl_rest.get("below_cl", 1) > 0:
            raise EngineError(
                "probe_clcheck: %d points below CL by >0.005 mm in the "
                "rest program (max %.3f mm) - run failed"
                % (cl_rest["below_cl"], cl_rest.get("max_depth_mm", 0.0)),
                code="clcheck", where={"program": "rest.nc"})

        # 9d) chained zmap of the rest program on the stock the finish
        #     left, with the rest tool's geometry + holder; preview.png is
        #     the leftover after the last program of the chain
        stock_rest = os.path.join(self.work, "stock_after_rest.npy")
        fr.remove_stale(stock_rest)
        argv_zr = [py, "-m", "verify.zmap", rest_nc, "--jobs", str(ZMAP_JOBS),
                   "--part", hf01,
                   "--tool", "ball",
                   "--dia", "%.4f" % rest["diameter_mm"],
                   "--corner", "%.4f" % (rest["diameter_mm"] / 2.0),
                   "--stock-in", stock_finish,
                   "--engage-max", "%.4f"
                   % (FINISH_ENGAGE_FACTOR * values["stepover"]),
                   "--tool-number", str(rest_number),
                   *self._tools_json_args(),
                   "--out-json", check_rest_path, "--png", png_path,
                   "--stock-out", stock_rest]
        if rest["flute_mm"] is not None:
            argv_zr += ["--flute", "%.4f" % rest["flute_mm"]]
        if rest["shank_diameter_mm"] is not None:
            argv_zr += ["--shank-dia", "%.4f" % rest["shank_diameter_mm"]]
        self._spawn(argv_zr, *P["zmap_rest"], on_progress)
        with open(check_rest_path) as fh:
            check_s = json.load(fh)
        _check_zmap_gates(check_s)

    # 10) rest pass summary + combined check.json / result
    if rest:
        result_rest = {
            "file": "rest.nc",
            "run_after_finish": True,
            "estimated_time_min": round(
                check_s["cycle_time_s"] / 60.0, 2),
            "cut_length_mm": check_s["cutting_length_mm"],
            "min_rest_mm": values.get("min_rest") or 0.5,
            "tool": {"type": "ball",
                    "diameter_mm": rest["diameter_mm"],
                    "corner_radius_mm": rest["diameter_mm"] / 2.0,
                    "flute_mm": rest["flute_mm"],
                    "shank_diameter_mm": rest["shank_diameter_mm"],
                    "holder": rest["holder"],
                    "number": rest_number},
            "over_flute": check_s["over_flute"],
            "holder_hits": check_s.get("holder_hits"),
        }
    chain = ["rough", "finish"] + (["rest"] if rest else [])
    check = {
        "tools_table": self._table_record(),
        "chain": chain,
        "part_hf": {"file": "part_hf01.npy", "cell_mm": 0.1,
                   "tess_tol_mm": 0.01},
        "probe_clcheck": {"gcode": "finish.nc", **cl},
        "rough": check_r,
        "finish": check_f,
        "warnings": {
            "engagement": {
                "rough": check_r.get("engagement"),
                "finish": check_f.get("engagement"),
            },
            "plunge": {
                "rough": check_r.get("plunge"),
                "finish": check_f.get("plunge"),
            },
        },
    }
    if rest:
        check["probe_clcheck_rest"] = {"gcode": "rest.nc", **cl_rest}
        check["rest"] = check_s
        check["warnings"]["engagement"]["rest"] = \
            check_s.get("engagement")
        check["warnings"]["plunge"]["rest"] = check_s.get("plunge")
    # FE5f: pass entries with no legal entry (deeper than the ball ZB
    # floor) were SKIPPED by finish/rest, never plunged - the areas stay
    # for a hole op or another setup, so James sees them in the summary
    def _skips(p):
        try:
            with open(p) as fh:
                return json.load(fh).get("fe5_skipped_clusters", [])
        except (OSError, ValueError):
            return []
    check["left_for_hole_op_or_another_setup"] = {
        "finish": _skips(fin_stats),
        "rest": _skips(rest_stats) if rest else [],
    }
    with open(os.path.join(self.work, "check.json"), "w") as fh:
        json.dump(check, fh, indent=2)

    # TASK_VIEW3D: display-only view data: part hf, the FINAL judged
    # stock (rest's when there is a rest pass, the finish's otherwise),
    # the posted programs' paths and the attention markers
    final_stock = stock_rest if rest else stock_finish
    view_progs = [("rough.nc", nc), ("finish.nc", fin)]
    view_checks = {"rough": check_r, "finish": check_f}
    if rest:
        view_progs.append(("rest.nc", rest_nc))
        view_checks["rest"] = check_s
    self._build_view(os.path.join(self.work, "view.bin"),
                    os.path.join(self.work, "view.json"),
                    hf01, final_stock, view_progs, view_checks)
    view_tools = {
        "rough.nc": "T%d %s %.3f mm" % (
            rough_number, values["rough_tool_type"],
            values["rough_tool_diameter"]),
        "finish.nc": "T%d ball %.3f mm" % (finish_number,
                                           values["tool_diameter"]),
    }
    if rest:
        view_tools["rest.nc"] = "T%d %s %.3f mm" % (
            rest_number, rest["type"], rest["diameter_mm"])
    self._build_view_images(
        os.path.join(self.work, "view.json"),
        os.path.join(self.work, "view.bin"),
        os.path.join(self.work, "view_iso.png"),
        os.path.join(self.work, "view_top.png"), view_tools)

    cycle_s = check_r["cycle_time_s"] + check_f["cycle_time_s"]
    cut_mm = check_r["cutting_length_mm"] + check_f["cutting_length_mm"]
    if rest:
        cycle_s += check_s["cycle_time_s"]
        cut_mm += check_s["cutting_length_mm"]
    # the leftover that matters is what the LAST program of the chain
    # leaves: the rest pass when there is one, the finish otherwise
    final_check = check_s if rest else check_f
    result = {
        "units": values["units"],
        "posted_units": posted,
        "estimated_time_min": round(cycle_s / 60.0, 2),
        "cut_length_mm": round(cut_mm, 1),
        "probe_clcheck": cl,
        "zmap": {
            # chained judgement: roughing from full stock, then the
            # finish with the roughed stock as stock-in (then the rest
            # pass with the finished stock as stock-in)
            "stock_in": "roughing",
            "cell_mm": 0.1,
            "gouges": {"rough": check_r["gouges"]["count"],
                      "finish": check_f["gouges"]["count"]},
            "rapid_collisions": {
                "rough": check_r["rapid_collisions"]["count"],
                "finish": check_f["rapid_collisions"]["count"]},
            "leftover": {
                "mean_mm": final_check["leftover"]["mean"],
                "p95_mm": final_check["leftover"]["p95"],
                "max_mm": final_check["leftover"]["max"],
                "within_0p5mm_fraction":
                    final_check["within_0p5mm_fraction"],
            },
        },
        "programs": {
            "rough": {
                "file": "rough.nc",
                "estimated_time_min": round(
                    check_r["cycle_time_s"] / 60.0, 2),
                "cut_length_mm": check_r["cutting_length_mm"],
                "tool": {"type": values["rough_tool_type"],
                        "diameter_mm": values["rough_tool_diameter"],
                        "corner_radius_mm":
                            values["rough_corner_radius"],
                        "number": rough_number},
                "over_flute": check_r["over_flute"],
                "holder_hits": check_r.get("holder_hits"),
            },
            "finish": {
                "file": "finish.nc",
                "run_after_roughing": True,
                "estimated_time_min": round(
                    check_f["cycle_time_s"] / 60.0, 2),
                "cut_length_mm": check_f["cutting_length_mm"],
                "tool": {"type": "ball",
                        "diameter_mm": values["tool_diameter"],
                        "number": finish_number},
            },
        },
        "program_number": values["program_number"],
        "orientation": values["orientation"],
        "stock_box_mm": stock,
        "origin": prep.get("origin", "model_origin"),
        "origin_offset_mm": prep.get("origin_offset", [0.0, 0.0, 0.0]),
        "tools_table": self._table_record(),
        "files": ["rough.nc", "finish.nc", "check.json",
                  "preview.png", "view.bin", "view.json",
                  "view_iso.png", "view_top.png"],
    }
    files = {"rough.nc": (nc, "application/octet-stream"),
             "finish.nc": (fin, "application/octet-stream"),
             "check.json": (os.path.join(self.work, "check.json"),
                           "application/json"),
             "preview.png": (png_path, "image/png"),
             "view.bin": (os.path.join(self.work, "view.bin"),
                          "application/octet-stream"),
             "view.json": (os.path.join(self.work, "view.json"),
                           "application/json"),
             "view_iso.png": (os.path.join(self.work, "view_iso.png"),
                              "image/png"),
             "view_top.png": (os.path.join(self.work, "view_top.png"),
                              "image/png")}
    if rest:
        result["zmap"]["gouges"]["rest"] = check_s["gouges"]["count"]
        result["zmap"]["rapid_collisions"]["rest"] = \
            check_s["rapid_collisions"]["count"]
        result["probe_clcheck_rest"] = cl_rest
        result["programs"]["rest"] = result_rest
        result["rest_program_number"] = int(values["program_number"]) + 2
        result["files"].insert(2, "rest.nc")
        files["rest.nc"] = (rest_nc, "application/octet-stream")
    self._record_used(values, [rough_number, finish_number]
                      + ([rest_number] if rest else []))
    self._drop_view_if_failed(result, files)
    return result, files


# =============================== tests ====================================

def _cfg():
    return {"engine_python": PY, "repo_root": REPO}


# zmap_rough is deliberately long: finish.nc/rest.nc become ready while it
# is still running, so the ordering test also proves each judge waits for
# the PREVIOUS judge to finish (the mutation check, see RESULTS).
DUR_ORDER_REST = {"prepare": 0.05, "hf01": 0.10, "rough": 0.30,
                  "tess": 0.01, "finish": 0.05, "post": 0.01,
                  "clcheck": 0.01, "rest": 0.05, "post_rest": 0.01,
                  "clcheck_rest": 0.01, "zmap_rough": 0.30,
                  "zmap_finish": 0.05, "zmap_rest": 0.05}
DUR_ORDER_NOREST = {k: v for k, v in DUR_ORDER_REST.items()
                    if k not in ("rest", "post_rest", "clcheck_rest",
                                 "zmap_rest")}


class TestChainOrdering:
    def test_judges_follow_programs_and_each_other_rest(self, tmp_path,
                                                        monkeypatch):
        """With the rest pass: every judge starts after its program step
        and after the previous judge; hf01 starts before the rough step
        ends; the run returns only after both chains."""
        fake, rec = make_fake(DUR_ORDER_REST)
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        result, _files = run.run_slope_split_finish(
            STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
        returned = time.time()
        s = spans(rec)

        # the judge chain runs beside the engine chain
        assert s["prepare"]["end"] <= s["hf01"]["start"]
        assert s["hf01"]["start"] < s["rough"]["end"], \
            "hf01 did not start while the rough step was still running"
        # each judge starts after its program step ...
        assert s["zmap_rough"]["start"] >= max(s["rough"]["end"],
                                               s["hf01"]["end"])
        assert s["zmap_finish"]["start"] >= s["post"]["end"]
        assert s["zmap_rest"]["start"] >= s["clcheck_rest"]["end"]
        # ... and after the previous judge finished
        assert s["zmap_finish"]["start"] >= s["zmap_rough"]["end"]
        assert s["zmap_rest"]["start"] >= s["zmap_finish"]["end"]
        # the engine chain stays sequential
        for prev, nxt in [("prepare", "rough"), ("rough", "tess"),
                          ("tess", "finish"), ("finish", "post"),
                          ("post", "clcheck"), ("clcheck", "rest"),
                          ("rest", "post_rest"),
                          ("post_rest", "clcheck_rest")]:
            assert s[nxt]["start"] >= s[prev]["end"], (prev, nxt)
        # the run returns only after BOTH chains finished
        assert returned >= s["clcheck_rest"]["end"]
        assert returned >= s["zmap_rest"]["end"]
        assert result["programs"]["rest"]["file"] == "rest.nc"

    def test_judges_follow_programs_and_each_other_no_rest(self, tmp_path,
                                                           monkeypatch):
        fake, rec = make_fake(DUR_ORDER_NOREST)
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        returned = time.time()
        s = spans(rec)
        assert s["hf01"]["start"] < s["rough"]["end"]
        assert s["zmap_rough"]["start"] >= max(s["rough"]["end"],
                                               s["hf01"]["end"])
        assert s["zmap_finish"]["start"] >= max(s["post"]["end"],
                                                s["zmap_rough"]["end"])
        assert returned >= s["clcheck"]["end"]
        assert returned >= s["zmap_finish"]["end"]


class TestJudgeErrors:
    def test_judge_exception_reraised_in_main_thread(self, tmp_path,
                                                     monkeypatch):
        """An exception raised in the judge thread is re-raised in the
        main thread (same type, same message) after both chains end."""
        boom = RuntimeError("judge boom")
        fake, rec = make_fake({"hf01": 0.02, "zmap_rough": 0.05},
                              fail={"zmap_finish": boom})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        with pytest.raises(RuntimeError) as ei:
            run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        assert type(ei.value) is RuntimeError
        assert str(ei.value) == "judge boom"
        assert ei.value is boom
        # the engine chain still ran to completion beside the dead judge
        s = spans(rec)
        assert s["clcheck"]["end"] >= s["post"]["end"]

    def test_engine_error_releases_judge_chain(self, tmp_path, monkeypatch):
        """An engine-chain failure must not leave the judge thread
        waiting forever: the run raises the engine error promptly."""
        fake, rec = make_fake({"hf01": 0.02},
                              fail={"clcheck": EngineError("engine died")})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        t0 = time.time()
        with pytest.raises(EngineError, match="engine died"):
            run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        assert time.time() - t0 < 5.0, "join after engine error hung"
        # the judge chain never waited forever for the events that the
        # failed engine chain could not deliver, and no judge ran on a
        # program the engine chain never posted
        s = spans(rec)
        assert "zmap_finish" not in s
        assert "zmap_rest" not in s


class TestProgressText:
    @staticmethod
    def _is_checking(msg, total):
        return msg in [runner_mod.CHECKING_FMT % (n, total)
                       for n in (1, 2, 3)]

    def test_checking_messages_after_engine_chain_rest(self, tmp_path,
                                                       monkeypatch):
        fake, _rec = make_fake({"hf01": 0.05, "zmap_rough": 0.12,
                                "zmap_finish": 0.12, "rest": 0.05,
                                "zmap_rest": 0.12})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        msgs = []
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        run.run_slope_split_finish(
            STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31),
            on_progress=lambda p, m: msgs.append((p, m)))
        fmt = runner_mod.CHECKING_FMT
        tail = [m for _p, m in msgs if self._is_checking(m, 3)]
        assert tail == [fmt % (1, 3), fmt % (2, 3), fmt % (3, 3)]
        # nothing but CHECKING text after the engine chain ended
        first = next(i for i, (_p, m) in enumerate(msgs)
                     if self._is_checking(m, 3))
        assert all(self._is_checking(m, 3) for _p, m in msgs[first:])
        # values never decrease and reach 1.0 with the last judge
        vals = [p for p, _m in msgs]
        assert vals == sorted(vals)
        assert msgs[-1][0] == pytest.approx(1.0)

    def test_checking_messages_after_engine_chain_no_rest(self, tmp_path,
                                                          monkeypatch):
        fake, _rec = make_fake({"hf01": 0.05, "zmap_rough": 0.12,
                                "zmap_finish": 0.12})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        msgs = []
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS),
                                   on_progress=lambda p, m:
                                   msgs.append((p, m)))
        fmt = runner_mod.CHECKING_FMT
        tail = [m for _p, m in msgs if self._is_checking(m, 2)]
        assert tail == [fmt % (1, 2), fmt % (2, 2)]
        vals = [p for p, _m in msgs]
        assert vals == sorted(vals)
        assert msgs[-1][0] == pytest.approx(1.0)


class TestJudgeJobs:
    def test_jobs_overlap_then_full(self, tmp_path, monkeypatch):
        """--jobs is ZMAP_JOBS_OVERLAP for a judge that starts while the
        engine chain still runs and ZMAP_JOBS for one that starts after
        it (the rest judge: its program is the engine chain's last step)."""
        assert runner_mod.ZMAP_JOBS == 12
        # the shipped overlap value equals ZMAP_JOBS (12, CF chain proof
        # 2026-10-31); a distinct value here keeps the selection testable
        monkeypatch.setattr(runner_mod, "ZMAP_JOBS_OVERLAP", 6)
        fake, rec = make_fake({"hf01": 0.01, "rough": 0.02, "tess": 0.05,
                               "finish": 0.05, "post": 0.05,
                               "clcheck": 0.05, "rest": 0.05,
                               "post_rest": 0.05, "clcheck_rest": 0.05,
                               "zmap_rough": 0.02, "zmap_finish": 0.02,
                               "zmap_rest": 0.02})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        run.run_slope_split_finish(
            STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))

        def jobs(name):
            a = rec["argv"][name]
            return int(a[a.index("--jobs") + 1])

        assert jobs("zmap_rough") == runner_mod.ZMAP_JOBS_OVERLAP
        assert jobs("zmap_finish") == runner_mod.ZMAP_JOBS_OVERLAP
        assert jobs("zmap_rest") == runner_mod.ZMAP_JOBS

    def test_argv_identical_to_serial_except_jobs(self, tmp_path,
                                                  monkeypatch):
        """Every step argv is byte-identical to the serial runner's except
        the --jobs value."""
        fake, rec = make_fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        par_dir = str(tmp_path / "p")
        run = runner_mod.EngineRun(_cfg(), par_dir)
        run.run_slope_split_finish(
            STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
        fake2, rec2 = make_fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake2)
        ser_dir = str(tmp_path / "s")
        run2 = runner_mod.EngineRun(_cfg(), ser_dir)
        serial_run_slope_split_finish(run2, STEP,
                                      dict(SLOPE_GOOD_INPUTS,
                                           rest_tool_number=31))
        for name, a in rec["argv"].items():
            b = [x.replace(ser_dir, par_dir) if isinstance(x, str) else x
                 for x in rec2["argv"][name]]
            if "--jobs" in a:
                a = list(a)
                a[a.index("--jobs") + 1] = b[a.index("--jobs") + 1]
            assert a == b, name


class TestIdenticalOutputs:
    def test_check_json_and_result_byte_identical_to_serial(self, tmp_path,
                                                            monkeypatch):
        """check.json and the result are byte-identical to the serial
        runner's (reference copy above) under canned step outputs."""
        values = dict(SLOPE_GOOD_INPUTS, rest_tool_number=31)
        fake, _rec = make_fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run1 = runner_mod.EngineRun(_cfg(), str(tmp_path / "two-chain"))
        res1, _f1 = run1.run_slope_split_finish(STEP, dict(values))
        run2 = runner_mod.EngineRun(_cfg(), str(tmp_path / "serial"))
        res2, _f2 = serial_run_slope_split_finish(run2, STEP, dict(values))

        with open(os.path.join(str(tmp_path / "two-chain"),
                               "check.json"), "rb") as fh:
            b1 = fh.read()
        with open(os.path.join(str(tmp_path / "serial"),
                               "check.json"), "rb") as fh:
            b2 = fh.read()
        assert b1 == b2, "check.json differs from the serial runner's"
        assert json.dumps(res1, sort_keys=True) == \
            json.dumps(res2, sort_keys=True)

    def test_identical_outputs_no_rest(self, tmp_path, monkeypatch):
        values = dict(SLOPE_GOOD_INPUTS)
        fake, _rec = make_fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run1 = runner_mod.EngineRun(_cfg(), str(tmp_path / "two-chain"))
        res1, _f1 = run1.run_slope_split_finish(STEP, dict(values))
        run2 = runner_mod.EngineRun(_cfg(), str(tmp_path / "serial"))
        res2, _f2 = serial_run_slope_split_finish(run2, STEP, dict(values))
        with open(os.path.join(str(tmp_path / "two-chain"),
                               "check.json"), "rb") as fh:
            b1 = fh.read()
        with open(os.path.join(str(tmp_path / "serial"),
                               "check.json"), "rb") as fh:
            b2 = fh.read()
        assert b1 == b2
        assert json.dumps(res1, sort_keys=True) == \
            json.dumps(res2, sort_keys=True)


class TestStepsLog:
    def test_one_line_per_step_both_chains(self, tmp_path, monkeypatch):
        fake, _rec = make_fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        run.run_slope_split_finish(
            STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
        with open(os.path.join(str(tmp_path), "steps.log")) as fh:
            entries = [ln.split() for ln in fh if ln.strip()]
        assert [e[0] for e in entries if e[3] == "engine"] == ENGINE_STEPS
        assert [e[0] for e in entries if e[3] == "judge"] == JUDGE_STEPS
        assert len(entries) == len(ENGINE_STEPS) + len(JUDGE_STEPS)
        for name, t0, t1, chain in entries:
            assert chain in ("engine", "judge")
            assert float(t0) <= float(t1), name

    def test_steps_log_no_rest(self, tmp_path, monkeypatch):
        fake, _rec = make_fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path))
        run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        with open(os.path.join(str(tmp_path), "steps.log")) as fh:
            names = [ln.split()[0] for ln in fh if ln.strip()]
        assert sorted(names) == sorted(ENGINE_STEPS[:6] + JUDGE_STEPS[:3])
