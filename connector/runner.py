"""Run adaptive_rough via the engine subprocesses.

Every engine call uses subprocess list args (never shell=True), env
ENGINE_WORKERS=4, cwd = repo root, and its own work dir
~/.stevecam/runs/<run_id>/. Engine JSON progress lines
({"progress":0.4,"message":"level 3/7"}) are mapped to run progress.
"""
import json
import os
import signal
import subprocess
import threading


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
                                 os.path.join(cfg["repo_root"], "tools",
                                            "x7_tools.json"))
        if e:
            return int(e["number"])
    except Exception:
        pass
    return 1  # not in the table: explicit number keeps the post happy


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
        # 1) orient + stock box + part heightfield
        self._spawn([py, "-m", "engine.cli", "prepare",
                    "--step", step_path, "--out-dir", self.work,
                    "--orient", values["orientation"],
                    "--stock-xy", "%.4f" % values["stock_xy"],
                    "--stock-top", "%.4f" % values["stock_top"],
                    "--stock-bottom", "%.4f" % values["stock_bottom"],
                    "--cell", str(cell)], 0.05, 0.2, on_progress)
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

        # 3) independent zmap check + leftover preview
        if on_progress:
            on_progress(0.88, "checking")
        check_path = os.path.join(self.work, "check.json")
        png_path = os.path.join(self.work, "preview.png")
        self._spawn([py, "-m", "verify.zmap", nc,
                    "--part", prep["hf"],
                    "--tool", values["tool_type"],
                    "--dia", "%.4f" % values["tool_diameter"],
                    "--corner", "%.4f" % values["corner_radius"],
                    "--stock", *[("%.4f" % v) for v in stock],
                    "--flute", "%.1f" % values["flute_length"],
                    "--optimal-load", "%.4f" % values["optimal_load"],
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
                                     os.path.join(self.cfg["repo_root"],
                                                 "tools", "x7_tools.json"))
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

        # 1) orient + stock box + part heightfield (for the roughing clip)
        self._spawn([py, "-m", "engine.cli", "prepare",
                    "--step", step_path, "--out-dir", self.work,
                    "--orient", values["orientation"],
                    "--stock-xy", "%.4f" % values["stock_xy"],
                    "--stock-top", "%.4f" % values["stock_top"],
                    "--stock-bottom", "%.4f" % values["stock_bottom"],
                    "--cell", "0.5"], 0.02, 0.12, on_progress)
        with open(os.path.join(self.work, "prepare.json")) as fh:
            prep = json.load(fh)
        stock = prep["stock"]
        floor = stock[4] + values["floor_z"]

        # 2) fresh zmap part heightfield (verify/heightfield.py, 0.01 mm
        #    tess, 0.1 mm cell) - independent of the roughing clip grid
        hf01 = os.path.join(self.work, "part_hf01.npy")
        self._spawn([fc, os.path.join(repo, "verify", "heightfield.py")],
                    0.12, 0.17, on_progress,
                    extra_env={"STEP_IN": prep["step"], "HF_OUT": hf01,
                              "CELL": "0.1", "TESS_TOL": "0.01",
                              "PAD": "0"})

        # 3) adaptive roughing (LNC post, full stock)
        nc = os.path.join(self.work, "rough.nc")
        stats_path = os.path.join(self.work, "rough_stats.json")
        self._spawn([py, "-m", "engine.cli", "rough",
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
                    "--json-progress", "--stats-json", stats_path],
                   0.17, 0.45, on_progress)

        # 4) tessellate the oriented model (finish input + clcheck probe)
        stl = os.path.join(self.work, "model.stl")
        self._spawn([fc, os.path.join(repo, "engine", "_tessellate.py")],
                    0.45, 0.50, on_progress,
                    extra_env={"STEP_IN": prep["step"], "STL_OUT": stl,
                              "TOL": "0.01"})

        # 5) slope-split finishing (neutral G-code)
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
                    "--tool-number", str(rough_number),
                    "--out-json", check_rough,
                    "--stock-out", stock_out], 0.80, 0.90, on_progress)
        check_finish = os.path.join(self.work, "check_finish.json")
        png_path = os.path.join(self.work, "preview.png")
        # Finish engagement threshold: use the finish stepover (distance between
        # finish passes) rather than the roughing optimal load; finish passes are
        # much lighter and the roughing threshold would over-flag them.
        self._spawn([py, "-m", "verify.zmap", fin,
                    "--part", hf01,
                    "--tool", "ball",
                    "--dia", "%.4f" % values["tool_diameter"],
                    "--corner", "%.4f" % (values["tool_diameter"] / 2.0),
                    "--stock-in", stock_out,
                    "--engage-max", "%.4f" % (1.5 * values["stepover"]),
                    "--tool-number", str(finish_number),
                    "--out-json", check_finish, "--png", png_path],
                   0.90, 0.97, on_progress)
        with open(check_rough) as fh:
            check_r = json.load(fh)
        with open(check_finish) as fh:
            check_f = json.load(fh)
        _check_zmap_gates(check_r)
        _check_zmap_gates(check_f)

        # 9) combined check.json + result
        check = {
            "chain": ["rough", "finish"],
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
        with open(os.path.join(self.work, "check.json"), "w") as fh:
            json.dump(check, fh, indent=2)

        result = {
            "units": "mm",
            "estimated_time_min": round(
                (check_r["cycle_time_s"] + check_f["cycle_time_s"]) / 60.0,
                2),
            "cut_length_mm": round(
                check_r["cutting_length_mm"] + check_f["cutting_length_mm"],
                1),
            "probe_clcheck": cl,
            "zmap": {
                # chained judgement: roughing from full stock, then the
                # finish with the roughed stock as stock-in
                "stock_in": "roughing",
                "cell_mm": 0.1,
                "gouges": {"rough": check_r["gouges"]["count"],
                          "finish": check_f["gouges"]["count"]},
                "rapid_collisions": {
                    "rough": check_r["rapid_collisions"]["count"],
                    "finish": check_f["rapid_collisions"]["count"]},
                "leftover": {
                    "mean_mm": check_f["leftover"]["mean"],
                    "p95_mm": check_f["leftover"]["p95"],
                    "max_mm": check_f["leftover"]["max"],
                    "within_0p5mm_fraction":
                        check_f["within_0p5mm_fraction"],
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
        return result, files
