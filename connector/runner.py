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

    def _spawn(self, argv, stage_lo, stage_hi, on_progress):
        env = dict(os.environ, ENGINE_WORKERS="4")
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
                    "--out-json", check_path, "--png", png_path],
                   0.88, 0.95, on_progress)
        with open(check_path) as fh:
            check = json.load(fh)

        result = {
            "units": "mm",
            "estimated_time_min": round(check["cycle_time_s"] / 60.0, 2),
            "cut_length_mm": check["cutting_length_mm"],
            "rapid_length_mm": check["rapid_length_mm"],
            "zmap_gouges": check["gouges"],
            "rapid_collisions": check["rapid_collisions"],
            "over_flute": check["over_flute"],
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
