"""TP1: adaptive_rough_toolpath, the adaptive rough as a STEVE toolpath action.

STEVE sends `part` (STEP in the setup's work frame), `request` (the
ToolpathRequest) and `steve_request_sha256`; we run the existing engine rough
(neutral G21 post, no origin logic) with the request's tool, stock and
limits, judge it with zmap, convert it to toolpath.json moves and validate
those against every request limit before anything is uploaded.

The request is read ONLY in parse_request(), with the field names STEVE sent
in the first live run (connector/testdata/steve_toolpath_request.json).
"""
import json
import os

import runner as runner_mod
from runner import EngineError

ACTION = "adaptive_rough_toolpath"
FORMAT = "steve_connector_toolpath"
MAX_MOVES = 200000
MAX_BYTES = 50 * 1024 * 1024
# posted coordinates are rounded to the control's resolution: plan one
# output step inside every limit (LNC metric resolution 0.001 mm)
INSIDE_MM = 0.001
# STEVE-supplied run inputs: never our settings
STEVE_INPUTS = ("part", "request", "stock", "steve_request_sha256")

SETTINGS = {
    "stepdown_mm": {"type": "number", "minimum": 0.05, "maximum": 100.0,
                    "title": "Stepdown (mm per level)",
                    "description": "depth of each roughing level, mm. "
                                   "Default 1 x the tool diameter; never "
                                   "above the tool's flute length"},
    "optimal_load_mm": {"type": "number", "minimum": 0.02, "maximum": 50.0,
                        "title": "Stepover / optimal load (mm)",
                        "description": "radial engagement the adaptive path "
                                       "holds (its stepover), mm. Default "
                                       "0.16 x the tool diameter; allowed "
                                       "0.02 x D .. 0.5 x D"},
    "stock_to_leave_mm": {"type": "number", "minimum": 0.0, "maximum": 5.0,
                          "default": 0.381,
                          "title": "Stock to leave (mm)",
                          "description": "material left on floors and walls "
                                         "for finishing, mm"},
    "load_limit": {"type": "boolean", "default": True,
                   "title": "Load limiter",
                   "description": "slow the feed only where the tool is "
                                  "overloaded; the path is unchanged"},
}

SPEC = {
    "name": ACTION,
    "title": "Adaptive roughing (SteveCAM)",
    "description": ("Constant-engagement adaptive roughing from SteveCAM, "
                    "generated from a STEVE milling operation."),
    "confirm": False,
    "inputs": {"type": "object", "properties": SETTINGS},
    "x-steve": {"toolpath": {
        "title": "SteveCAM adaptive rough",
        "description": ("Adaptive roughing with a flat end mill: level by "
                        "level at the stepdown, holding a steady side load "
                        "(the optimal load), leaving stock for finishing. "
                        "Judged by SteveCAM's own zmap check before it is "
                        "returned."),
        "cutters": ["flat"]}},
}


def _fail(msg, field, got=None, code="request_field_missing"):
    raise EngineError(msg, code=code, field=field, got=got)


def _need(d, path):
    """d[a][b]... or a plain error naming the request field."""
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or cur.get(k) is None:
            _fail("request.%s is missing" % path, "request." + path,
                  code="request_field_missing")
        cur = cur[k]
    return cur


def _box(d, path):
    """{"minimum_mm": [x,y,z], "maximum_mm": [x,y,z]} -> (lo, hi)."""
    b = _need(d, path)
    lo, hi = b.get("minimum_mm"), b.get("maximum_mm")
    if not (isinstance(lo, list) and isinstance(hi, list)
            and len(lo) == 3 and len(hi) == 3):
        _fail("request.%s must be {minimum_mm, maximum_mm}" % path,
              "request." + path, code="request_field_missing")
    return [float(v) for v in lo], [float(v) for v in hi]


def _regions(req, role):
    """request.tool.geometry.regions of one role, tip-up (z from the tip)."""
    regs = [r for r in _need(req, "tool.geometry.regions")
            if r.get("role") == role]
    if not regs:
        _fail("request.tool.geometry.regions has no %s region" % role,
              "request.tool.geometry.regions", code="request_field_missing")
    return sorted(regs, key=lambda r: r["segment"]["z_start_mm"])


def parse_request(req):
    """The ToolpathRequest -> the flat numbers the run uses. Field names as
    STEVE sent them in the first live run (2026-11-04, TP1b)."""
    kind = _need(req, "tool.cutter_type")
    if kind != "flat_end_mill":
        _fail("this action cuts with a flat end mill only; request.tool."
              "cutter_type is %r" % kind, "request.tool.cutter_type", kind,
              code="tool_not_supported")
    cut = _regions(req, "cutter")
    seg = cut[-1]["segment"]
    if any(r["segment"].get("corner_radius_mm") for r in cut):
        _fail("request.tool is a flat end mill with a corner radius",
              "request.tool.geometry.regions", code="tool_not_supported")
    stickout = float(_need(req, "tool.geometry.stickout_mm"))
    shank = _regions(req, "shank")
    # holder outline above the holder nose (tip + stick-out), the
    # [z_lo, z_hi, r_lo, r_hi] form our tool table and zmap read
    holder = [[r["segment"]["z_start_mm"] - stickout,
               r["segment"]["z_end_mm"] - stickout,
               r["segment"]["radius_start_mm"],
               r["segment"]["radius_end_mm"]]
              for r in _regions(req, "holder")]
    lim = "limits."
    return {
        "dia": float(_need(req, "tool.geometry.cutter_diameter_mm")),
        "flute": float(seg["z_end_mm"]),
        "shank": 2.0 * max(r["segment"]["radius_start_mm"] for r in shank),
        "stickout": stickout,
        "holder": holder,
        "stock": _box(req, "setup.stock_mm"),
        "rpm": float(_need(req, lim + "spindle_rpm")),
        "feed": float(_need(req, lim + "feed_mm_min")),
        "plunge": float(_need(req, lim + "plunge_mm_min")),
        "max_feed": float(_need(req, lim + "maximum_feed_mm_min")),
        "top": float(_need(req, lim + "top_mm")),
        "bottom": float(_need(req, lim + "bottom_mm")),
        "clearance": float(_need(req, lim + "clearance_mm")),
        "start": [float(v) for v in _need(req, "start_tip_mm")],
        "retract_z": float(_need(req, "retract_z_mm")),
        "margin_box": _box(req, "margin_box"),
        "tip_envelope": _box(req, "tip_envelope"),
        "posts_arcs": bool(req.get("posts_arcs")),
    }


def settings_for(values, tp):
    """Our settings with tool-relative defaults and ranges (mm, never inch)."""
    d = tp["dia"]
    s = {k: values.get(k, SETTINGS[k].get("default")) for k in SETTINGS}
    if s["stepdown_mm"] is None:
        s["stepdown_mm"] = min(d, tp["flute"])
    if s["stepdown_mm"] > tp["flute"]:
        _fail("stepdown_mm %.3f is above the tool's flute length %.3f mm"
              % (s["stepdown_mm"], tp["flute"]), "stepdown_mm",
              s["stepdown_mm"], code="input_out_of_range")
    if s["optimal_load_mm"] is None:
        s["optimal_load_mm"] = 0.16 * d
    if not 0.02 * d <= s["optimal_load_mm"] <= 0.5 * d:
        _fail("optimal_load_mm %.3f is outside 0.02 x D .. 0.5 x D "
              "(%.3f .. %.3f mm for this %.3f mm tool)"
              % (s["optimal_load_mm"], 0.02 * d, 0.5 * d, d),
              "optimal_load_mm", s["optimal_load_mm"],
              code="input_out_of_range")
    return s


def tool_table(tp, repo_root):
    """A one-tool table (T1) from the request's tool: the engine and zmap
    read tool, flute and holder from it, never from our library."""
    with open(os.path.join(repo_root, "tools", "x7_tools.json")) as fh:
        base = json.load(fh)
    t = {"tool_id": "steve-request", "number": 1, "type": "flat",
         "diameter_mm": tp["dia"], "corner_radius_mm": 0.0,
         "flute_mm": tp["flute"], "shank_diameter_mm": tp["shank"],
         "holder": "steve_request", "stickout_mm": tp["stickout"]}
    out = {k: v for k, v in base.items() if k not in ("tools", "holders")}
    out["tools"] = [t]
    out["holders"] = {"steve_request": {"segments": tp["holder"]}}
    return out


def ngc_to_moves(text, tp):
    """Neutral G21 G0/G1 program -> toolpath.json moves (tool tip, work
    frame), starting from start_tip_mm. The engine posts lines only, so
    arcs never appear whatever posts_arcs says. A straight plunge is held to
    the plunge feed (only ever slower); the last move ends at or above
    retract_z_mm."""
    moves = []
    cur = list(tp["start"])
    feed = None
    for raw in text.splitlines():
        w = raw.split("(")[0].split()
        if not w or w[0] not in ("G0", "G1"):
            continue
        end = list(cur)
        for word in w[1:]:
            if word[0] in "XYZ":
                end["XYZ".index(word[0])] = float(word[1:])
            elif word[0] == "F":
                feed = float(word[1:])
        if end == cur:
            continue
        if w[0] == "G0":
            if not moves:
                # leave start_tip_mm (machine home: may lie outside
                # margin_box) over the first point at retract_z_mm, which
                # sits inside the box, then down
                moves.append({"kind": "rapid",
                              "end_mm": [end[0], end[1], tp["retract_z"]]})
            moves.append({"kind": "rapid", "end_mm": end})
        else:
            f = feed
            if end[:2] == cur[:2] and end[2] < cur[2]:
                f = min(f, tp["plunge"])
            moves.append({"kind": "feed", "end_mm": end, "feed_mm_min": f})
        cur = end
    if cur[2] < tp["retract_z"]:
        moves.append({"kind": "rapid",
                      "end_mm": [cur[0], cur[1], tp["retract_z"]]})
    return moves


def document(moves, request_sha256):
    return {"format": FORMAT, "version": 1, "units": "mm",
            "coordinate_space": "work", "request_sha256": request_sha256,
            "moves": moves}


_MOVE_KEYS = {"rapid": {"kind", "end_mm"},
              "feed": {"kind", "end_mm", "feed_mm_min"},
              "arc": {"kind", "end_mm", "center_mm", "direction", "turns",
                      "feed_mm_min"}}


def violations(doc, tp, request_sha256):
    """Every rule STEVE checks on toolpath.json, as [(field, move, limit,
    message)]: empty = acceptable. Run on OUR output before uploading."""
    out = []
    top = {"format": FORMAT, "version": 1, "units": "mm",
           "coordinate_space": "work"}
    for k, v in top.items():
        if doc.get(k) != v:
            out.append((k, None, v, "%s must be %r" % (k, v)))
    if set(doc) != set(top) | {"request_sha256", "moves"}:
        out.append(("toolpath", None, None, "extra or missing top-level "
                    "fields: %s" % sorted(set(doc) ^ (set(top) | {
                        "request_sha256", "moves"}))))
    if doc.get("request_sha256") != request_sha256:
        out.append(("request_sha256", None, request_sha256,
                    "request_sha256 does not repeat steve_request_sha256"))
    moves = doc.get("moves") or []
    if not moves:
        out.append(("moves", None, None, "no moves"))
    if len(moves) > MAX_MOVES:
        out.append(("moves", None, MAX_MOVES, "%d moves > %d"
                    % (len(moves), MAX_MOVES)))
    size = len(json.dumps(doc, separators=(",", ":")).encode("utf-8"))
    if size > MAX_BYTES:
        out.append(("toolpath", None, MAX_BYTES, "%d bytes > %d"
                    % (size, MAX_BYTES)))
    fmax = min(tp["feed"], tp["max_feed"])
    cur = tp["start"]
    for i, m in enumerate(moves):
        kind = m.get("kind")
        if kind not in _MOVE_KEYS or set(m) != _MOVE_KEYS[kind]:
            out.append(("moves[%d]" % i, i, None, "bad move fields"))
            continue
        if kind == "arc" and not tp["posts_arcs"]:
            out.append(("moves[%d].kind" % i, i, "posts_arcs",
                        "arc while posts_arcs is false"))
        e = m["end_mm"]
        for name in ("margin_box", "tip_envelope"):
            lo, hi = tp[name]
            for a in range(3):
                if not lo[a] + INSIDE_MM <= e[a] <= hi[a] - INSIDE_MM:
                    out.append(("moves[%d].end_mm" % i, i, name,
                                "%s %.4f outside %s [%.4f, %.4f] (one step "
                                "inside)" % ("XYZ"[a], e[a], name, lo[a],
                                             hi[a])))
        if kind != "rapid":
            f = m["feed_mm_min"]
            if not isinstance(f, (int, float)) or f <= 0 or f > fmax:
                out.append(("moves[%d].feed_mm_min" % i, i, fmax,
                            "feed %r above the operation/machine feed %.1f"
                            % (f, fmax)))
            elif e[:2] == cur[:2] and e[2] < cur[2] and f > tp["plunge"]:
                out.append(("moves[%d].feed_mm_min" % i, i, tp["plunge"],
                            "straight plunge at %.1f above the plunge feed "
                            "%.1f" % (f, tp["plunge"])))
        cur = e
    if moves and moves[-1].get("end_mm", [0, 0, -1e9])[2] < tp["retract_z"]:
        out.append(("moves[%d].end_mm" % (len(moves) - 1), len(moves) - 1,
                    "retract_z_mm", "last move ends at Z %.4f below "
                    "retract_z_mm %.4f" % (moves[-1]["end_mm"][2],
                                           tp["retract_z"])))
    return out


def check_or_fail(doc, tp, request_sha256):
    bad = violations(doc, tp, request_sha256)
    if bad:
        field, move, limit, msg = bad[0]
        raise EngineError("toolpath refused before upload (%d problems); "
                          "first: %s" % (len(bad), msg),
                          code="toolpath_limit", field=field, got=move,
                          allowed=limit)


def run(engine, step_path, request, request_sha256, values, on_progress):
    """The engine rough in the request's work frame -> (result, toolpath
    document path). Gates as adaptive_rough: zmap gouge / rapid / entry /
    over-flute / holder / axial, plus the rough's own clcheck."""
    tp = parse_request(request)
    s = settings_for(values, tp)
    cfg, work = engine.cfg, engine.work
    py = cfg["engine_python"]
    os.makedirs(work, exist_ok=True)
    table = os.path.join(work, "steve_tool.json")
    with open(table, "w") as fh:
        json.dump(tool_table(tp, cfg["repo_root"]), fh, indent=1)
    lo, hi = tp["stock"]
    stock = [lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]]
    cut_feed = min(tp["feed"], tp["max_feed"])
    ngc = os.path.join(work, "rough.ngc")
    stats_path = os.path.join(work, "stats.json")
    engine._spawn([py, "-m", "engine.cli", "rough", "--step", step_path,
                   "--stock", *["%.4f" % v for v in stock],
                   "--tool", "flat:%.4f" % tp["dia"], "--out", ngc,
                   "--floor", "%.4f" % tp["bottom"],
                   "--leave", "%.4f" % s["stock_to_leave_mm"],
                   "--stepdown", "%.4f" % s["stepdown_mm"],
                   "--optimal-load-mm", "%.4f" % s["optimal_load_mm"],
                   "--cut-feed", "%.1f" % cut_feed,
                   "--ramp-feed", "%.1f" % min(tp["plunge"], cut_feed),
                   "--spindle", str(int(tp["rpm"])),
                   "--tools-json", table, "--tool-number", "1",
                   "--flute", "%.4f" % tp["flute"],
                   "--json-progress", "--stats-json", stats_path,
                   "--load-limit" if s["load_limit"] else "--no-load-limit"],
                  0.05, 0.75, on_progress)
    with open(stats_path) as fh:
        stats = json.load(fh)
    if not stats.get("n_moves"):
        raise EngineError("nothing to cut: every level found no stock "
                          "region - adaptive roughing only clears enclosed "
                          "stock", code="nothing_to_cut")
    if stats.get("clcheck_violations"):
        raise EngineError("clcheck gate: %d violations"
                          % stats["clcheck_violations"], code="clcheck")

    if on_progress:
        on_progress(0.78, "checking")
    hf = os.path.join(work, "part_hf_zmap.npy")
    fc = os.path.join(os.path.dirname(py), "freecadcmd")
    engine._spawn([fc, os.path.join(cfg["repo_root"], "verify",
                                    "heightfield.py")], 0.78, 0.82,
                  on_progress, extra_env={
                      "STEP_IN": step_path, "HF_OUT": hf, "CELL": "0.5",
                      "TESS_TOL": "0.01",
                      "STOCK_BOX": " ".join("%.4f" % v for v in stock[:4]),
                      "TOOL_R": "%.4f" % (tp["dia"] / 2.0)})
    check_path = os.path.join(work, "check.json")
    load = s["optimal_load_mm"]
    engine._spawn([py, "-m", "verify.zmap", ngc,
                   "--jobs", str(runner_mod.ZMAP_JOBS), "--part", hf,
                   "--tool", "flat", "--dia", "%.4f" % tp["dia"],
                   "--corner", "0", "--stock", *["%.4f" % v for v in stock],
                   "--flute", "%.4f" % tp["flute"],
                   "--optimal-load", "%.4f" % load,
                   "--engage-max", "%.4f"
                   % (runner_mod.ROUGH_ENGAGE_FACTOR * load),
                   "--tool-number", "1", "--tools-json", table,
                   "--out-json", check_path], 0.82, 0.95, on_progress)
    with open(check_path) as fh:
        check = json.load(fh)
    runner_mod._check_zmap_gates(check)

    with open(ngc) as fh:
        doc = document(ngc_to_moves(fh.read(), tp), request_sha256)
    check_or_fail(doc, tp, request_sha256)
    out = os.path.join(work, "toolpath.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    ll = stats.get("load_limit") or {}
    eng = check.get("engagement") or {}
    result = {
        "estimated_time_min": round(check["cycle_time_s"] / 60.0, 2),
        "cut_length_mm": check["cutting_length_mm"],
        "n_moves": len(doc["moves"]),
        "max_load_mm": eng.get("max_mm"),
        "engagement_over_threshold": eng.get("count"),
        "reduced_feed_windows": ll.get("windows_slowed", 0),
        "gates": {k: (check.get(k) or {}).get("count", 0)
                  for k in ("gouges", "rapid_collisions", "entry_stock",
                            "over_flute", "holder_hits", "axial_plunges")},
        "clcheck_violations": stats.get("clcheck_violations", 0),
        "settings": s,
        "cut_feed_mm_min": cut_feed,
        "leftover": {"mean_mm": check["leftover"]["mean"],
                     "p95_mm": check["leftover"]["p95"]},
    }
    return result, out, check
