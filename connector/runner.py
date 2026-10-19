"""Run adaptive_rough via the engine subprocesses.

Every engine call uses subprocess list args (never shell=True), env
ENGINE_WORKERS=4, cwd = repo root, and its own work dir
~/.stevecam/runs/<run_id>/. Engine JSON progress lines
({"progress":0.4,"message":"level 3/7"}) are mapped to run progress.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading

# Engagement warning factors (report-only warnings, never gates):
# roughing warns above ROUGH_ENGAGE_FACTOR x optimal load, finishing above
# FINISH_ENGAGE_FACTOR x stepover.
ROUGH_ENGAGE_FACTOR = 1.2
FINISH_ENGAGE_FACTOR = 1.5


class Cancelled(Exception):
    pass


class EngineError(Exception):
    pass


def _check_zmap_gates(check):
    """Raise EngineError if any zmap gate fails: gouges, rapid collisions,
    shank/over-flute hits > 0, or holder hits > 0 (S5)."""
    gouges = check.get("gouges", {})
    if isinstance(gouges, dict) and gouges.get("count", 0) > 0:
        raise EngineError(
            "zmap gate: %d gouges (max %.3f mm)"
            % (gouges["count"], gouges.get("max_depth", 0.0)))
    rapids = check.get("rapid_collisions", {})
    if isinstance(rapids, dict) and rapids.get("count", 0) > 0:
        raise EngineError(
            "zmap gate: %d rapid collisions (first line %s)"
            % (rapids["count"], rapids.get("first_line", "?")))
    of = check.get("over_flute")
    if isinstance(of, dict) and of.get("count", 0) > 0:
        raise EngineError(
            "zmap gate: %d over-flute/shank hits (max %.3f mm)"
            % (of["count"], of.get("max_depth", 0.0)))
    hd = check.get("holder") or {}
    if hd.get("status") != "checked" or not isinstance(check.get("holder_hits"), dict):
        raise EngineError(
            "zmap gate: holder unknown (%s) - a run is never judged without "
            "the holder clearance check" % hd.get("reason", hd.get("status", "no holder report")))
    hh = check.get("holder_hits")
    if isinstance(hh, dict) and hh.get("count", 0) > 0:
        raise EngineError(
            "zmap gate: %d holder hits (max intrusion %.3f mm, first line "
            "%s) - the holder cannot keep 1.0 mm clearance"
            % (hh["count"], hh.get("max_intrusion", 0.0),
               hh.get("first_line", "?")))


def _tool_number(cfg, values):
    if values.get("tool_number"):
        return int(values["tool_number"])
    try:  # X7 table lookup via the engine's own module (under repo root)
        import sys
        if cfg["repo_root"] not in sys.path:
            sys.path.insert(0, cfg["repo_root"])
        from engine import post_lnc
        e = post_lnc.lookup_tool(values["tool_type"], values["tool_diameter"],
                                 values["corner_radius"],
                                 post_lnc.load_tool_table(
                                     os.path.join(cfg["repo_root"], "tools",
                                                "x7_tools.json")))
        if e:
            return int(e["number"])
    except Exception:
        pass
    return 1  # not in the table: explicit number keeps the post happy


T_WORD_RE = re.compile(r"\bT\s*(\d+)", re.IGNORECASE)

# task CPc: check_program input fields judged in this order
CHECK_PROGRAM_FIELDS = ("program", "program_2", "program_3")


def program_tool_numbers(text):
    """Distinct T word numbers in a posted program (comments stripped),
    in order of first appearance."""
    out = []
    for line in text.splitlines():
        s = line.split(";", 1)[0]
        depth = 0
        kept = []
        for ch in s:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                kept.append(ch)
        for m in T_WORD_RE.findall("".join(kept)):
            n = int(m)
            if n not in out:
                out.append(n)
    return out


def check_tool_entry(number, path=None):
    """check_program: the tools/x7_tools.json entry for tool `number`.
    Returns {type, diameter_mm, corner_radius_mm, flute_mm,
    shank_diameter_mm, holder, stickout_mm}. Unknown tool (no entry, a
    null number, or missing shape data) -> EngineError, same as today's
    refusal to run a tool the table does not know."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools", "x7_tools.json")
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError) as e:
        raise EngineError("cannot read tool table %s: %s" % (path, e))
    e = next((t for t in data.get("tools", [])
              if t.get("number") == int(number)), None)
    if e is None:
        raise EngineError(
            "tool T%d is not in tools/x7_tools.json: unknown tool - add it "
            "to the X7 table (or pass a tool_number that is in the table)"
            % int(number))
    for k in ("type", "diameter_mm"):
        if e.get(k) is None:
            raise EngineError("tool T%d entry in %s has no %s"
                              % (int(number), path, k))
    return {"number": int(number), "type": e["type"],
            "diameter_mm": float(e["diameter_mm"]),
            "corner_radius_mm": float(e.get("corner_radius_mm") or 0.0),
            "flute_mm": (float(e["flute_mm"])
                         if e.get("flute_mm") is not None else None),
            "shank_diameter_mm": (float(e["shank_diameter_mm"])
                                  if e.get("shank_diameter_mm") is not None
                                  else float(e["diameter_mm"])),
            "holder": e.get("holder"),
            "stickout_mm": (float(e["stickout_mm"])
                            if e.get("stickout_mm") is not None else None)}


class EngineRun:
    """Runs one roughing job; .cancel() stops the active subprocess."""

    def __init__(self, cfg, work_dir):
        self.cfg = cfg
        self.work = work_dir
        os.makedirs(work_dir, exist_ok=True)
        self._proc = None
        self._lock = threading.Lock()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()

    def _freshness(self):
        """engine.freshness (task HC): guards against stale build outputs."""
        if self.cfg["repo_root"] not in sys.path:
            sys.path.insert(0, self.cfg["repo_root"])
        from engine import freshness
        return freshness

    def _spawn(self, argv, stage_lo, stage_hi, on_progress, json_out=None,
               extra_env=None):
        env = dict(os.environ, ENGINE_WORKERS="4")
        if extra_env:
            env.update(extra_env)
        with self._lock:
            if self.cancelled:
                raise Cancelled("cancelled")
            proc = subprocess.Popen(
                argv, cwd=self.cfg["repo_root"], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True)
            self._proc = proc
        err_lines = []

        def drain():
            for line in proc.stderr:
                err_lines.append(line)
                if len(err_lines) > 200:
                    del err_lines[:100]
        t = threading.Thread(target=drain, daemon=True)
        t.start()
        last = [None]
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if json_out is not None:
                json_out.append(obj)
            if "progress" not in obj:
                continue
            p = stage_lo + (stage_hi - stage_lo) * float(obj["progress"])
            msg = obj.get("message", "")
            if last[0] is None or p - last[0] >= 0.02 or msg != last[1]:
                last = [p, msg]
                if on_progress:
                    on_progress(p, msg)
            if self.cancelled:
                self.cancel()
        proc.wait()
        t.join(timeout=2)
        if self.cancelled:
            raise Cancelled("cancelled")
        if proc.returncode != 0:
            raise EngineError("engine failed (rc=%d): %s"
                             % (proc.returncode, "".join(err_lines[-25:])))
        return proc

    def run(self, step_path, values, on_progress=None):
        py = self.cfg["engine_python"]
        cell = 0.5
        # 1) orient + stock box + part heightfield (grid covers the run's
        #    stock + tool radius + margin via STOCK_BOX/TOOL_R, task Z5b)
        self._spawn([py, "-m", "engine.cli", "prepare",
                    "--step", step_path, "--out-dir", self.work,
                    "--orient", values["orientation"],
                    "--stock-xy", "%.4f" % values["stock_xy"],
                    "--stock-top", "%.4f" % values["stock_top"],
                    "--stock-bottom", "%.4f" % values["stock_bottom"],
                    "--cell", str(cell),
                    "--tool-r", "%.4f" % (values["tool_diameter"] / 2.0)],
                   0.05, 0.2, on_progress)
        with open(os.path.join(self.work, "prepare.json")) as fh:
            prep = json.load(fh)
        stock = prep["stock"]
        floor = stock[4] + values["floor_z"]

        # 2) rough (LNC post) with JSON progress
        nc = os.path.join(self.work, "rough.nc")
        stats_path = os.path.join(self.work, "stats.json")
        self._spawn([py, "-m", "engine.cli", "rough",
                    "--step", prep["step"],
                    "--stock", *[("%.4f" % v) for v in stock],
                    "--tool", "%s:%.4f:%.4f" % (values["tool_type"],
                                               values["tool_diameter"],
                                               values["corner_radius"]),
                    "--out", nc, "--floor", "%.4f" % floor,
                    "--leave", "%.4f" % values["stock_to_leave"],
                    "--stepdown", "%.4f" % values["stepdown"],
                    "--optimal-load-mm", "%.4f" % values["optimal_load"],
                    "--stepup", "%.4f" % values["rest_stepup"],
                    "--hf", prep["hf"], "--min-rest", "0.5",
                    "--cut-feed", "%.1f" % values["feed"],
                    "--ramp-feed", "%.1f" % values["ramp_feed"],
                    "--spindle", str(int(values["rpm"])),
                    "--post", "lnc", "--program",
                    str(int(values["program_number"])),
                    "--tool-number", str(_tool_number(self.cfg, values)),
                    "--json-progress", "--stats-json", stats_path],
                   0.2, 0.85, on_progress)
        with open(stats_path) as fh:
            stats = json.load(fh)

        # 3) independent zmap check + leftover preview. The zmap part grid
        #    must cover stock + tool radius (zmap exits non-zero if the
        #    stock box extends beyond the grid by more than half a cell, or
        #    a tool footprint leaves the grid): the shared heightfield
        #    builder grows the grid from STOCK_BOX + TOOL_R + MARGIN.
        if on_progress:
            on_progress(0.86, "checking")
        fc = os.path.join(os.path.dirname(py), "freecadcmd")
        # task HC: remove any stale heightfield from a reused run dir
        # before rebuilding, then require the fresh .npy + sidecar to match
        fr = self._freshness()
        step_sha = fr.sha256_file(prep["step"])
        hf_zmap = os.path.join(self.work, "part_hf_zmap.npy")
        fr.remove_stale(hf_zmap)
        self._spawn([fc, os.path.join(self.cfg["repo_root"], "verify",
                                       "heightfield.py")],
                    0.86, 0.90, on_progress,
                    extra_env={"STEP_IN": prep["step"], "HF_OUT": hf_zmap,
                              "CELL": str(cell), "TESS_TOL": "0.01",
                              "STOCK_BOX": " ".join("%.4f" % v
                                                    for v in stock[:4]),
                              "TOOL_R": "%.4f" % (values["tool_diameter"] / 2.0)})
        try:
            fr.require_fresh(hf_zmap, step_sha256=step_sha, cell=cell,
                             tess_tol=0.01)
        except OSError as e:
            raise EngineError(str(e))
        check_path = os.path.join(self.work, "check.json")
        png_path = os.path.join(self.work, "preview.png")
        self._spawn([py, "-m", "verify.zmap", nc,
                    "--part", hf_zmap,
                    "--tool", values["tool_type"],
                    "--dia", "%.4f" % values["tool_diameter"],
                    "--corner", "%.4f" % values["corner_radius"],
                    "--stock", *[("%.4f" % v) for v in stock],
                    "--flute", "%.1f" % values["flute_length"],
                    "--optimal-load", "%.4f" % values["optimal_load"],
                    "--engage-max", "%.4f"
                    % (ROUGH_ENGAGE_FACTOR * values["optimal_load"]),
                    "--tool-number", str(_tool_number(self.cfg, values)),
                    "--out-json", check_path, "--png", png_path],
                   0.88, 0.95, on_progress)
        with open(check_path) as fh:
            check = json.load(fh)
        _check_zmap_gates(check)

        result = {
            "units": "mm",
            "estimated_time_min": round(check["cycle_time_s"] / 60.0, 2),
            "cut_length_mm": check["cutting_length_mm"],
            "rapid_length_mm": check["rapid_length_mm"],
            "zmap_gouges": check["gouges"],
            "rapid_collisions": check["rapid_collisions"],
            "over_flute": check["over_flute"],
            "holder_hits": check.get("holder_hits"),
            "leftover": {
                "mean_mm": check["leftover"]["mean"],
                "p95_mm": check["leftover"]["p95"],
                "within_0p5mm_fraction": check["within_0p5mm_fraction"],
            },
            "levels_machined": sum(1 for l in stats["levels"]
                                   if not l.get("skipped")),
            "n_moves": stats.get("n_moves"),
            "tool": {"type": values["tool_type"],
                    "diameter_mm": values["tool_diameter"],
                    "corner_radius_mm": values["corner_radius"],
                    "number": _tool_number(self.cfg, values)},
            "program_number": values["program_number"],
            "orientation": values["orientation"],
            "stock_box_mm": stock,
            "files": ["rough.nc", "check.json", "preview.png"],
        }
        files = {"rough.nc": (nc, "application/octet-stream"),
                 "check.json": (check_path, "application/json"),
                 "preview.png": (png_path, "image/png")}
        return result, files

    # -------------------------------------------------- check_program ----
    def run_check_program(self, program_path, step_path, values,
                          on_progress=None):
        """check_program (task CP / CPc): judge up to three posted programs
        in sequence with the independent zmap --strict against the oriented
        part and the stock box. Each program brings its own tool from its
        own T word (one T per program, looked up in tools/x7_tools.json)
        and its own holder; each is judged on the stock left by the previous
        one (--stock-in = previous --stock-out; first program: full stock
        box). The tool_number override applies to "program" only and must
        match its T. Gates as adaptive_rough on EVERY program; the first
        failing program fails the run and is named in the error. preview.png
        is the leftover after the LAST program. Returns check.json +
        preview.png; nothing new is uploaded as .nc, nothing goes to the
        machine."""
        py = self.cfg["engine_python"]
        fc = os.path.join(os.path.dirname(py), "freecadcmd")
        repo = self.cfg["repo_root"]

        # 1) every program's own tool up front, in order: one T word each,
        #    known in the X7 table (unknown tool or holder fails the run,
        #    same as today)
        programs = [("program", program_path)]
        for pname in CHECK_PROGRAM_FIELDS[1:]:
            extra = os.path.join(self.work, pname + ".nc")
            if os.path.exists(extra):
                programs.append((pname, extra))
        resolved = []
        for i, (pname, ppath) in enumerate(programs):
            with open(ppath) as fh:
                ptext = fh.read()
            numbers = program_tool_numbers(ptext)
            if len(numbers) > 1:
                raise EngineError("multi-tool programs not supported yet "
                                  "(%s T words: %s)"
                                  % (pname, ", ".join("T%d" % n
                                                   for n in numbers)))
            number = (int(values["tool_number"])
                     if i == 0 and values.get("tool_number")
                     else (numbers[0] if numbers else None))
            if number is None:
                raise EngineError("no T word in the program and no "
                                  "tool_number override: the tool cannot be "
                                  "resolved")
            tool = check_tool_entry(number, os.path.join(repo, "tools",
                                                         "x7_tools.json"))
            if numbers and number != numbers[0]:
                raise EngineError("tool_number T%d does not match the "
                                  "program's T%d: refusing to judge with a "
                                  "different tool" % (number, numbers[0]))
            resolved.append((pname, ppath, number, tool))
        cell = 0.1  # judge grid: same 0.1 mm as the finishing chain

        # 2) orient + stock box + part heightfield (shared builder grid:
        #    STOCK_BOX + TOOL_R + margin, task Z5b; TOOL_R covers the
        #    largest tool of the sequence)
        if on_progress:
            on_progress(0.05, "preparing part")
        max_tool_r = max(t["diameter_mm"] for _, _, _, t in resolved) / 2.0
        self._spawn([py, "-m", "engine.cli", "prepare",
                     "--step", step_path, "--out-dir", self.work,
                     "--orient", values["orientation"],
                     "--stock-xy", "%.4f" % values["stock_xy"],
                     "--stock-top", "%.4f" % values["stock_top"],
                     "--stock-bottom", "%.4f" % values["stock_bottom"],
                     "--cell", "0.5",
                     "--tool-r", "%.4f" % max_tool_r],
                    0.05, 0.35, on_progress)
        with open(os.path.join(self.work, "prepare.json")) as fh:
            prep = json.load(fh)
        stock = prep["stock"]

        # 3) fresh judge heightfield (task HC: stale files removed first,
        #    sidecar must pin this run's STEP/cell/tess tol)
        fr = self._freshness()
        step_sha = fr.sha256_file(prep["step"])
        hf_zmap = os.path.join(self.work, "part_hf_zmap.npy")
        fr.remove_stale(hf_zmap)
        if on_progress:
            on_progress(0.35, "building heightfield")
        self._spawn([fc, os.path.join(repo, "verify", "heightfield.py")],
                    0.35, 0.55, on_progress,
                    extra_env={"STEP_IN": prep["step"], "HF_OUT": hf_zmap,
                              "CELL": str(cell), "TESS_TOL": "0.01",
                              "STOCK_BOX": " ".join("%.4f" % v
                                                    for v in stock[:4]),
                              "TOOL_R": "%.4f" % max_tool_r})
        try:
            fr.require_fresh(hf_zmap, step_sha256=step_sha, cell=cell,
                             tess_tol=0.01)
        except OSError as e:
            raise EngineError(str(e))

        # 4) zmap --strict per program, in order, carrying the stock: each
        #    program is judged with --stock-in = the previous program's
        #    --stock-out (first program: the full stock box). Unsupported
        #    codes fail with the first offender (full list in check json);
        #    gates on EVERY program and the first failing program fails the
        #    run and is named in the error. No optimal load input for this
        #    action: engagement is report-only, no threshold. preview.png
        #    is the leftover after the LAST program.
        nprog = len(resolved)
        png_path = os.path.join(self.work, "preview.png")
        entries = []
        stock_in = None  # None: the first program starts from full stock
        for i, (pname, ppath, number, tool) in enumerate(resolved):
            lo = 0.55 + 0.40 * i / nprog
            hi = 0.55 + 0.40 * (i + 1) / nprog
            if on_progress:
                on_progress(lo, "checking %s" % pname)
            out_json = os.path.join(self.work, "check_%d.json" % (i + 1))
            argv = [py, "-m", "verify.zmap", ppath,
                    "--part", hf_zmap,
                    "--tool", tool["type"],
                    "--dia", "%.4f" % tool["diameter_mm"],
                    "--corner", "%.4f" % tool["corner_radius_mm"],
                    "--tool-number", str(number),
                    "--strict", "--engage-report",
                    "--out-json", out_json]
            if stock_in is None:
                argv += ["--stock", *[("%.4f" % v) for v in stock]]
            else:
                argv += ["--stock-in", stock_in]
            if i < nprog - 1:
                stock_in = os.path.join(self.work,
                                        "stock_after_%s.npy" % pname)
                fr.remove_stale(stock_in)
                argv += ["--stock-out", stock_in]
            if i == nprog - 1:
                argv += ["--png", png_path]
            if tool["flute_mm"] is not None:
                argv += ["--flute", "%.4f" % tool["flute_mm"]]
            if tool["shank_diameter_mm"] is not None:
                argv += ["--shank-dia", "%.4f" % tool["shank_diameter_mm"]]
            try:
                self._spawn(argv, lo, hi, on_progress)
                with open(out_json) as fh:
                    check = json.load(fh)
                _check_zmap_gates(check)
            except EngineError as e:
                raise EngineError("%s failed: %s" % (pname, e))
            entries.append({"name": pname,
                            "tool": {"number": number, "type": tool["type"],
                                     "diameter_mm": tool["diameter_mm"],
                                     "corner_radius_mm":
                                         tool["corner_radius_mm"],
                                     "flute_mm": tool["flute_mm"],
                                     "shank_diameter_mm":
                                         tool["shank_diameter_mm"],
                                     "holder": tool["holder"],
                                     "stickout_mm": tool["stickout_mm"]},
                            "check": check})

        first = entries[0]
        check = {"programs": entries}
        # top-level keys for the first program kept exactly as they were
        # (single-program callers see no change)
        check.update(first["check"])
        with open(os.path.join(self.work, "check.json"), "w") as fh:
            json.dump(check, fh, indent=2)

        result = {
            "units": "mm",
            "program": os.path.basename(program_path),
            "programs": [{"name": e["name"],
                          "tool_number": e["tool"]["number"]}
                         for e in entries],
            "tool": first["tool"],
            "orientation": values["orientation"],
            "stock_box_mm": stock,
            "strict": True,
            "unsupported": first["check"].get("unsupported", []),
            "zmap_gouges": first["check"]["gouges"],
            "rapid_collisions": first["check"]["rapid_collisions"],
            "over_flute": first["check"]["over_flute"],
            "holder_hits": first["check"].get("holder_hits"),
            "outside_grid": first["check"].get("outside_grid"),
            "engagement": first["check"].get("engagement"),
            "leftover": {
                "mean_mm": first["check"]["leftover"]["mean"],
                "p95_mm": first["check"]["leftover"]["p95"],
                "within_0p5mm_fraction":
                    first["check"]["within_0p5mm_fraction"],
            },
            "estimated_time_min": round(
                first["check"]["cycle_time_s"] / 60.0, 2),
            "cut_length_mm": first["check"]["cutting_length_mm"],
            "rapid_length_mm": first["check"]["rapid_length_mm"],
            "files": ["check.json", "preview.png"],
        }
        files = {"check.json": (os.path.join(self.work, "check.json"),
                                 "application/json"),
                 "preview.png": (png_path, "image/png")}
        return result, files

    # ------------------------------------------------- slope_split_finish --
    def _finish_tool_number(self, values):
        """Tool number for the finishing ball: explicit tool_number input,
        else the X7 table. Refuses (EngineError -> run failed) when the ball
        is not in the table and no number was given - never a silent T1."""
        if values.get("tool_number"):
            return int(values["tool_number"])
        try:  # X7 table lookup via the engine's own module (under repo root)
            import sys
            if self.cfg["repo_root"] not in sys.path:
                sys.path.insert(0, self.cfg["repo_root"])
            from engine import post_lnc
            e = post_lnc.lookup_tool("ball", values["tool_diameter"],
                                     values["tool_diameter"] / 2.0,
                                     post_lnc.load_tool_table(
                                         os.path.join(self.cfg["repo_root"],
                                                    "tools", "x7_tools.json")))
            if e:
                return int(e["number"])
        except Exception:
            pass
        raise EngineError(
            "finish tool ball D=%.3f mm is not in tools/x7_tools.json and "
            "no tool_number was given: pass a tool_number or add the tool "
            "to the X7 table" % values["tool_diameter"])

    def run_slope_split_finish(self, step_path, values, on_progress=None):
        """Roughing first, then slope-split finishing (a finishing ball must
        never meet raw stock). Returns (result, files) with BOTH posted LNC
        programs; zmap judges the chain: roughing from full stock
        (--stock-out), then the finish with --stock-in."""
        py = self.cfg["engine_python"]
        fc = os.path.join(os.path.dirname(py), "freecadcmd")
        repo = self.cfg["repo_root"]

        # 0) tool numbers up front: refuse a missing finish-tool number
        #    before any engine work (the run reports failed, clearly)
        finish_number = self._finish_tool_number(values)
        rough_number = _tool_number(self.cfg, {
            "tool_type": values["rough_tool_type"],
            "tool_diameter": values["rough_tool_diameter"],
            "corner_radius": values["rough_corner_radius"]})

        # 0b) optional corner rest pass (task CR): the rest tool must be a
        #     ball in tools/x7_tools.json with a known holder - an unknown
        #     tool or a missing holder fails the run before any engine work,
        #     exactly like the finish tool. Absent rest_tool_number = the
        #     rough + finish chain unchanged.
        rest_number = values.get("rest_tool_number")
        rest = None
        if rest_number:
            rest_number = int(rest_number)
            rest = check_tool_entry(rest_number,
                                   os.path.join(repo, "tools", "x7_tools.json"))
            if not rest["holder"]:
                raise EngineError(
                    "rest tool T%d has no holder in tools/x7_tools.json: the "
                    "rest pass is never judged without the holder clearance "
                    "check" % rest_number)
            if rest["type"] != "ball":
                raise EngineError(
                    "rest tool T%d is a %s, not a ball: the corner rest pass "
                    "runs with a ball nose from tools/x7_tools.json"
                    % (rest_number, rest["type"]))
            if rest["diameter_mm"] >= values["tool_diameter"]:
                raise EngineError(
                    "rest tool T%d D=%.3f mm is not smaller than the finishing "
                    "ball D=%.3f mm: the rest pass cuts with the smaller ball"
                    % (rest_number, rest["diameter_mm"],
                       values["tool_diameter"]))

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
                    "--stock-xy", "%.4f" % values["stock_xy"],
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
            raise EngineError(str(e))

        # 3) adaptive roughing (LNC post, full stock); the rest pass needs the
        #    engine's own post-roughing stock for its rapid/lift clearance
        #    (--stock-from), so the rough step exports it when a rest follows
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
                "--json-progress", "--stats-json", stats_path]
        if rest:
            fr.remove_stale(rough_stock_out)
            argv += ["--stock-out", rough_stock_out]
        self._spawn(argv, *P["rough"], on_progress)

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
            raise EngineError(str(e))

        # 5) slope-split finishing (neutral G-code). PQ: the engine snaps the
        #    emitted points to the output grid matching this op's post units
        #    (step 6 posts metric -> 0.001 mm; an inch post would be 0.00254)
        fin_neutral = os.path.join(self.work, "finish_neutral.ngc")
        fin_stats = os.path.join(self.work, "finish_stats.json")
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
                    "--spindle", str(int(values["rpm"])),
                    "--post-grid-mm", "0.001",
                    "--stats-json", fin_stats], 0.50, 0.72, on_progress)

        # 6) post to LNC (metric: the posted artifact is what clcheck
        #    judges, and inch rounding on the corner CL ridge would exceed
        #    the 0.005 mm criterion); header carries run-after-roughing
        fin = os.path.join(self.work, "finish.nc")
        self._spawn([py, "-m", "engine.cli", "post",
                    "--in", fin_neutral, "--out", fin,
                    "--program", str(int(values["program_number"])),
                    "--op-name", "SLOPE SPLIT FINISH (RUN AFTER ROUGHING)",
                    "--tool-number", str(finish_number),
                    "--metric"], 0.72, 0.76, on_progress)

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
                % (cl["below_cl"], cl.get("max_depth_mm", 0.0)))

        # 8) chained zmap: roughing from full stock (--stock-out), then the
        #    finish with the roughed stock as --stock-in
        check_rough = os.path.join(self.work, "check_rough.json")
        stock_out = os.path.join(self.work, "stock_after_rough.npy")
        self._spawn([py, "-m", "verify.zmap", nc,
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
        argv_f = [py, "-m", "verify.zmap", fin,
                  "--part", hf01,
                  "--tool", "ball",
                  "--dia", "%.4f" % values["tool_diameter"],
                  "--corner", "%.4f" % (values["tool_diameter"] / 2.0),
                  "--stock-in", stock_out,
                  "--engage-max", "%.4f"
                  % (FINISH_ENGAGE_FACTOR * values["stepover"]),
                  "--tool-number", str(finish_number),
                  "--out-json", check_finish]
        if rest:
            fr.remove_stale(stock_finish)
            argv_f += ["--stock-out", stock_finish]
        else:
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
            with open(os.path.splitext(stock_finish)[0] + ".json", "w") as fh:
                json.dump({"x0": hf_meta["x0"], "y0": hf_meta["y0"],
                          "cell": hf_meta["cell"]}, fh)

            # 9a) rest finish (neutral G-code): --tool is the previous (finish)
            #     ball, --rest-tool the smaller ball that does the cutting
            rest_neutral = os.path.join(self.work, "rest_neutral.ngc")
            rest_stats = os.path.join(self.work, "rest_stats.json")
            argv_rest = [py, "-m", "engine.cli", "finish",
                        "--stl", stl,
                        "--out", rest_neutral,
                        "--tool", "ball:%.4f" % values["tool_diameter"],
                        "--rest-from", stock_finish,
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
                        "--spindle", str(int(values["rpm"])),
                        "--post-grid-mm", "0.001",
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
            #     neutral header names the rest tool, so carry its geometry
            self._spawn([py, "-m", "engine.cli", "post",
                        "--in", rest_neutral, "--out", rest_nc,
                        "--program", str(int(values["program_number"]) + 2),
                        "--op-name", "REST PASS (RUN AFTER FINISH)",
                        "--tool-number", str(rest_number),
                        "--tool-kind", "ball",
                        "--dia", "%.4f" % rest["diameter_mm"],
                        "--corner", "%.4f" % (rest["diameter_mm"] / 2.0),
                        "--metric"], *P["post_rest"], on_progress)

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
                    % (cl_rest["below_cl"], cl_rest.get("max_depth_mm", 0.0)))

            # 9d) chained zmap of the rest program on the stock the finish
            #     left, with the rest tool's geometry + holder; preview.png is
            #     the leftover after the last program of the chain
            argv_zr = [py, "-m", "verify.zmap", rest_nc,
                       "--part", hf01,
                       "--tool", "ball",
                       "--dia", "%.4f" % rest["diameter_mm"],
                       "--corner", "%.4f" % (rest["diameter_mm"] / 2.0),
                       "--stock-in", stock_finish,
                       "--engage-max", "%.4f"
                       % (FINISH_ENGAGE_FACTOR * values["stepover"]),
                       "--tool-number", str(rest_number),
                       "--out-json", check_rest_path, "--png", png_path]
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
        with open(os.path.join(self.work, "check.json"), "w") as fh:
            json.dump(check, fh, indent=2)

        cycle_s = check_r["cycle_time_s"] + check_f["cycle_time_s"]
        cut_mm = check_r["cutting_length_mm"] + check_f["cutting_length_mm"]
        if rest:
            cycle_s += check_s["cycle_time_s"]
            cut_mm += check_s["cutting_length_mm"]
        # the leftover that matters is what the LAST program of the chain
        # leaves: the rest pass when there is one, the finish otherwise
        final_check = check_s if rest else check_f
        result = {
            "units": "mm",
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
            "files": ["rough.nc", "finish.nc", "check.json",
                     "preview.png"],
        }
        files = {"rough.nc": (nc, "application/octet-stream"),
                 "finish.nc": (fin, "application/octet-stream"),
                 "check.json": (os.path.join(self.work, "check.json"),
                               "application/json"),
                 "preview.png": (png_path, "image/png")}
        if rest:
            result["zmap"]["gouges"]["rest"] = check_s["gouges"]["count"]
            result["zmap"]["rapid_collisions"]["rest"] = \
                check_s["rapid_collisions"]["count"]
            result["probe_clcheck_rest"] = cl_rest
            result["programs"]["rest"] = result_rest
            result["rest_program_number"] = int(values["program_number"]) + 2
            result["files"].insert(2, "rest.nc")
            files["rest.nc"] = (rest_nc, "application/octet-stream")
        return result, files
