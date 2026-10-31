"""TASK SP-P3C-2 tests: failure propagation, cancel of both chains and
process-group tracking in connector/runner.py run_slope_split_finish.

Unit only - steps are fakes (test_spp3c.make_fake) EXCEPT the steps named
"long", which run a REAL `python -c "import time; time.sleep(60)"` child
through the REAL EngineRun._spawn: it is tracked in EngineRun._procs, has
its own process group (start_new_session=True) and is reachable by the
real cancel()/_kill_all() killpg. The long child writes its own pid and
its grandchild's pid (0 when none) to a pidfile, so the test can verify
"no orphans" with os.kill(pid, 0).

Run: /opt/homebrew/bin/pytest connector/test_spp3c2.py -q
"""
import os
import signal
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import runner as runner_mod  # noqa: E402
from runner import Cancelled, EngineError  # noqa: E402
from test_spp3c import (_cfg, _write_output, make_fake, spans,  # noqa: E402
                        step_name)
from test_connector import SLOPE_GOOD_INPUTS  # noqa: E402

STEP = os.path.join(HERE, "unused.step")

# the real, unpatched EngineRun._spawn (captured before any monkeypatch):
# long steps run their sleeper child through exactly this code path
REAL_SPAWN = runner_mod.EngineRun._spawn

# prints nothing; first spawns a 60 s grandchild (same process group),
# then writes "<own pid> <grandchild pid or 0>" to $SPP3C2_PIDFILE and
# sleeps 60 s itself
CHILD_CODE = (
    "import os, subprocess, sys, time\n"
    "gp = 0\n"
    "if os.environ.get('SPP3C2_G'):\n"
    "    gp = subprocess.Popen([sys.executable, '-c',\n"
    "                           'import time; time.sleep(60)']).pid\n"
    "with open(os.environ['SPP3C2_PIDFILE'], 'w') as fh:\n"
    "    fh.write('%d %d\\n' % (os.getpid(), gp))\n"
    "time.sleep(60)\n")


def make_spawn(long=None, grandchild=(), durations=None, fail=None):
    """Fake _spawn: every step is test_spp3c's canned fake except the
    steps named in `long` ({step: pidfile}), which write their canned
    outputs and then run a real 60 s sleeper child via REAL_SPAWN.
    Steps in `grandchild` also spawn a 60 s grandchild."""
    long = long or {}
    canned, rec = make_fake(durations or {}, fail or {})
    rec["real"] = {}
    lock = threading.Lock()

    def spawn(self, argv, lo, hi, on_progress, json_out=None,
              extra_env=None):
        a = list(argv)
        name = step_name(a)
        if name not in long:
            return canned(self, argv, lo, hi, on_progress, json_out,
                          extra_env)
        _write_output(self, a, name, json_out, extra_env)
        env = dict(extra_env or {}, SPP3C2_PIDFILE=long[name],
                   SPP3C2_G="1" if name in grandchild else "")
        with lock:
            rec["events"].append(("start", name, time.time()))
            rec["real"][name] = long[name]
        try:
            return REAL_SPAWN(self, [sys.executable, "-c", CHILD_CODE],
                              lo, hi, None, extra_env=env)
        finally:
            with lock:
                rec["events"].append(("end", name, time.time()))

    return spawn, rec


def read_pids(path, timeout=15.0):
    """(child pid, grandchild pid or None) once the pidfile exists."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with open(path) as fh:
                pid, gp = fh.read().split()
            return int(pid), (int(gp) or None)
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError("pidfile %s never appeared" % path)


def gone(pid, timeout):
    """Time at which os.kill(pid, 0) raises ProcessLookupError (the pid
    is gone, i.e. dead AND reaped), or None when it stays alive."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return time.time()
        except PermissionError:
            return time.time()   # alive but not ours: not our scenario
        time.sleep(0.02)
    return None


def assert_not_busy(run):
    """busy rule: run_slope_split_finish has returned or raised, so the
    judge thread must be joined and no tracked proc may be alive."""
    assert not any(t.name == "judge-chain" for t in threading.enumerate()), \
        "judge thread still alive after run_slope_split_finish ended"
    with run._lock:
        live = [p for p in run._procs if p.poll() is None]
    assert not live, "tracked proc still alive after the run ended"


# --------------------------------------------------------------------------
# judge failure stops the engine
# --------------------------------------------------------------------------
class TestJudgeFailureStopsEngine:
    def test_long_engine_child_killed_rest_never_starts(self, tmp_path,
                                                        monkeypatch):
        """zmap_rough's gate raises while the engine chain waits on a REAL
        60 s child: that child's process group must be dead within 2 s of
        the judge failure, the run must raise the JUDGE's EngineError
        (same object, same code), and no rest-pass engine step may
        start."""
        boom = EngineError("gouges found", code="gouges")
        pf = str(tmp_path / "finish.pid")
        spawn, rec = make_spawn(
            long={"finish": pf},
            durations={"prepare": 0.05, "hf01": 0.05, "rough": 0.5,
                       "tess": 0.01, "zmap_rough": 0.2},
            fail={"zmap_rough": boom})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))

        box = {}

        def watcher():
            pid, _gp = read_pids(pf)
            box["pid"] = pid
            box["death"] = gone(pid, 6.0)

        w = threading.Thread(target=watcher)
        w.start()
        with pytest.raises(EngineError) as ei:
            run.run_slope_split_finish(
                STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
        w.join(15)
        assert ei.value is boom                      # the JUDGE's error
        assert ei.value.code == "gouges"
        s = spans(rec)
        assert "zmap_finish" not in s and "zmap_rest" not in s
        # no rest-pass engine step started after the failed rough gate
        assert "rest" not in s and "post_rest" not in s \
            and "clcheck_rest" not in s
        # the real engine child died within 2 s of the judge failing
        assert box.get("pid"), "engine child never started"
        assert box["death"] is not None, "engine child survived"
        assert box["death"] - s["zmap_rough"]["end"] < 2.0
        assert_not_busy(run)


# --------------------------------------------------------------------------
# engine failure stops the judges
# --------------------------------------------------------------------------
class TestEngineFailureStopsJudges:
    def test_long_judge_child_killed(self, tmp_path, monkeypatch):
        """The engine chain fails at clcheck while the judge chain waits
        on a REAL 60 s zmap child: the child must die within 2 s of the
        engine failure, the run must raise the ENGINE's error, and no
        later judge may start."""
        boom = EngineError("engine died", code="engine_code")
        pf = str(tmp_path / "zmap_rough.pid")
        spawn, rec = make_spawn(
            long={"zmap_rough": pf},
            durations={"hf01": 0.05, "rough": 0.3, "tess": 0.01,
                       "finish": 0.3, "post": 0.01},
            fail={"clcheck": boom})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))

        box = {}

        def watcher():
            pid, _gp = read_pids(pf)
            box["pid"] = pid
            box["death"] = gone(pid, 6.0)

        w = threading.Thread(target=watcher)
        w.start()
        with pytest.raises(EngineError) as ei:
            run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        w.join(15)
        assert ei.value is boom                      # the ENGINE's error
        assert ei.value.code == "engine_code"
        s = spans(rec)
        assert "zmap_finish" not in s
        assert box.get("pid"), "judge child never started"
        assert box["death"] is not None, "judge child survived"
        assert box["death"] - s["clcheck"]["end"] < 2.0
        assert_not_busy(run)


# --------------------------------------------------------------------------
# first error wins
# --------------------------------------------------------------------------
class TestSerialOrderWinner:
    def test_engine_first_judge_second(self, tmp_path, monkeypatch):
        """Both chains fail on their own: the reported error is the one
        whose step comes first in the serial order (clcheck before
        zmap_rough), unchanged."""
        boom_e = EngineError("engine boom", code="engine_first")
        boom_j = EngineError("judge boom", code="judge_second")
        spawn, rec = make_spawn(
            durations={"hf01": 0.05, "rough": 0.3, "tess": 0.01,
                       "finish": 0.2, "post": 0.01, "zmap_rough": 1.0},
            fail={"clcheck": boom_e, "zmap_rough": boom_j})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))
        with pytest.raises(EngineError) as ei:
            run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        assert ei.value is boom_e
        assert ei.value.code == "engine_first"
        s = spans(rec)
        assert "zmap_rough" in s          # the judge really did fail later
        assert "zmap_finish" not in s
        assert_not_busy(run)

    def test_judge_first_engine_stops_before_next_step(self, tmp_path,
                                                       monkeypatch):
        """The judge fails first; the engine chain must stop BEFORE its
        next step (post): the post fake never runs, its programmed failure
        never fires, and the internal Cancelled is never reported in place
        of the judge's error (an internal stop never ranks)."""
        boom_j = EngineError("judge first", code="judge_first")
        boom_e = EngineError("engine second", code="engine_second")
        spawn, rec = make_spawn(
            durations={"hf01": 0.05, "rough": 0.3, "tess": 0.01,
                       "finish": 0.4, "zmap_rough": 0.05},
            fail={"zmap_rough": boom_j, "post": boom_e})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))
        with pytest.raises(EngineError) as ei:
            run.run_slope_split_finish(
                STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
        assert ei.value is boom_j
        assert ei.value.code == "judge_first"
        s = spans(rec)
        assert "post" not in s            # stopped before the next step
        assert "clcheck" not in s and "rest" not in s
        assert_not_busy(run)


    @pytest.mark.parametrize("order", ["tess_first", "judge_first"])
    def test_stale_stl_beats_judge_file_error(self, tmp_path, monkeypatch,
                                              order):
        """The exact race behind test_stale_model_stl_fails_run: tess fails
        on its own (stale STL) and the judge's zmap_rough fails with a
        FileNotFoundError. In EITHER timing order the caller gets the tess
        error, because tess comes first in the serial order."""
        boom_t = EngineError("build produced no non-empty STL x",
                             code="stale_artifact")
        boom_j = FileNotFoundError("check_rough.json")
        if order == "tess_first":
            dur = {"hf01": 0.01, "rough": 0.05, "tess": 0.01,
                   "zmap_rough": 0.4}
        else:
            dur = {"hf01": 0.01, "rough": 0.05, "tess": 0.4,
                   "zmap_rough": 0.01}
        spawn, rec = make_spawn(durations=dur,
                                fail={"tess": boom_t, "zmap_rough": boom_j})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))
        with pytest.raises(EngineError) as ei:
            run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        assert ei.value is boom_t and ei.value.code == "stale_artifact"
        assert_not_busy(run)


# --------------------------------------------------------------------------
# cancel with no orphans (children AND grandchildren, both chains)
# --------------------------------------------------------------------------
class TestCancelNoOrphans:
    @staticmethod
    def _make(tmp_path, monkeypatch):
        pf_e = str(tmp_path / "engine.pid")
        pf_j = str(tmp_path / "judge.pid")
        spawn, _rec = make_spawn(
            long={"finish": pf_e, "zmap_rough": pf_j},
            grandchild=("finish", "zmap_rough"),
            durations={"hf01": 0.05, "rough": 0.3, "tess": 0.01})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))
        return run, [pf_e, pf_j]

    @staticmethod
    def _assert_no_orphans(pairs, t_cancel):
        pids = [p for pair in pairs for p in pair if p]
        assert len(pids) == 4, "expected 2 children + 2 grandchildren"
        for pid in pids:
            t_gone = gone(pid, 6.0)
            assert t_gone is not None, "pid %s survived cancel" % pid
            # the 6 s window starts AT the cancel, not at the raise: a
            # child that only dies because its own 60 s sleep ended is
            # an orphan the cancel failed to kill
            assert t_gone <= t_cancel + 6.0, \
                "pid %s died too late (%.1f s after cancel)" % (
                    pid, t_gone - t_cancel)

    def test_cancel_from_another_thread(self, tmp_path, monkeypatch):
        """One REAL child with a REAL grandchild per chain; cancel() from
        another thread must leave no orphan within 6 s, the run must raise
        Cancelled and the judge thread must be joined."""
        run, pfs = self._make(tmp_path, monkeypatch)
        pairs = {}
        box = {}

        def watcher():
            pairs["engine"] = read_pids(pfs[0])
            pairs["judge"] = read_pids(pfs[1])
            box["cancel"] = time.time()
            run.cancel()                # the connector's stop() path

        def do_run():
            try:
                run.run_slope_split_finish(
                    STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
            except BaseException as e:      # noqa: BLE001
                box["exc"] = e

        w = threading.Thread(target=watcher)
        r = threading.Thread(target=do_run)
        w.start()
        r.start()
        r.join(90)
        w.join(60)
        assert not r.is_alive() and not w.is_alive()
        assert isinstance(box.get("exc"), Cancelled), \
            "run must raise Cancelled, got %r" % (box.get("exc"),)
        assert "cancel" in box, "children never both started"
        self._assert_no_orphans(list(pairs.values()), box["cancel"])
        assert_not_busy(run)

    def test_simulated_sigterm_from_main_thread(self, tmp_path, monkeypatch):
        """The connector's SIGTERM path: run_slope_split_finish on the
        MAIN thread, a SIGTERM handler calling run.cancel() (exactly
        connector.py stop()), fired by a helper thread once both chains
        have their real children up."""
        run, pfs = self._make(tmp_path, monkeypatch)
        pairs = {}
        box = {}

        def on_term(*_):
            box["cancel"] = time.time()
            run.cancel()

        def helper():
            try:
                pairs["engine"] = read_pids(pfs[0])
                pairs["judge"] = read_pids(pfs[1])
                os.kill(os.getpid(), signal.SIGTERM)
            except BaseException as e:      # noqa: BLE001
                box["helper"] = e

        old = signal.signal(signal.SIGTERM, on_term)
        h = threading.Thread(target=helper)
        try:
            h.start()
            with pytest.raises(Cancelled):
                run.run_slope_split_finish(
                    STEP, dict(SLOPE_GOOD_INPUTS, rest_tool_number=31))
        finally:
            signal.signal(signal.SIGTERM, old)
            h.join(60)
        assert "cancel" in box, "children never both started"
        self._assert_no_orphans(list(pairs.values()), box["cancel"])
        assert_not_busy(run)


# --------------------------------------------------------------------------
# busy: never return or raise while a judge thread or tracked proc is live
# --------------------------------------------------------------------------
class TestNeverBusy:
    def test_success_path(self, tmp_path, monkeypatch):
        """After a successful return the judge thread is joined and no
        tracked proc is alive."""
        fake, _rec = make_fake({"hf01": 0.02, "zmap_rough": 0.02})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))
        run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        assert_not_busy(run)
        assert run._procs == set()

    def test_failure_path_after_real_child_kill(self, tmp_path, monkeypatch):
        """After the raise (engine error, judge chain's REAL child just
        killed) the child pid is gone, the judge thread is joined and no
        tracked proc is alive."""
        boom = EngineError("engine died", code="engine_code")
        pf = str(tmp_path / "zmap_rough.pid")
        spawn, _rec = make_spawn(
            long={"zmap_rough": pf},
            durations={"hf01": 0.05, "rough": 0.3, "tess": 0.01,
                       "finish": 0.3, "post": 0.01},
            fail={"clcheck": boom})
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", spawn)
        run = runner_mod.EngineRun(_cfg(), str(tmp_path / "work"))
        box = {}

        def watcher():
            box["pid"] = read_pids(pf)[0]

        w = threading.Thread(target=watcher)
        w.start()
        with pytest.raises(EngineError):
            run.run_slope_split_finish(STEP, dict(SLOPE_GOOD_INPUTS))
        w.join(15)
        assert box.get("pid")
        assert gone(box["pid"], 6.0) is not None
        assert_not_busy(run)
