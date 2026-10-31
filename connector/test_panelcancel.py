"""Task PANELCANCEL tests: a panel/STEVE "cancel" is read WHILE a job runs.

The connector runs as a REAL subprocess (like test_pidstatus.
test_sigterm_exits_zero does) against the in-process MockSteve. FAKE SPAWN
IS USED, as the brief requires choosing: the launcher monkeypatches
runner.EngineRun.run with a fake that sleeps in 0.05 s steps and raises
runner.Cancelled once self.cancelled is set (exactly what the real _spawn
does on cancel). No real child process is involved, so the "child PID is
gone" assertion is N/A; EngineRun.cancel()/Cancelled/_run_job's
`except Cancelled` reporting path are the real ones.

Fake job durations: the cancel test's job would run LONG (35 s >= 30 s);
a cancel must end it within CANCEL_N s (measured, see results file).

Run through the small-test lane:
    /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 \
        -m pytest -q -p no:cacheprovider connector/test_panelcancel.py

PANELCANCEL_CONNECTOR_DIR (used by the M1 mutation run) points the
launcher at another connector.py; everything else is imported from here.
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import crypto                      # noqa: E402
from mock_steve import MockSteve   # noqa: E402

PY = "/opt/homebrew/bin/python3"
CONNECTOR_DIR = os.environ.get("PANELCANCEL_CONNECTOR_DIR") or HERE
FAKE_STEP = b"STEPFAKE-PANELCANCEL"
CANCEL_N = 10.0    # N: seconds allowed for terminal "cancelled" after the
                   # cancel arrives (measured in the results file)
LONG = 35.0        # the cancel test's fake job duration (>= 30 s per brief)

# adaptive_rough inputs (values from test_connector.GOOD_INPUTS; the model
# file itself is never fetched - SteveClient.download is patched to
# FAKE_STEP, whose sha256/bytes we embed).
RUN_INPUTS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
    "tool_diameter": 12.686, "corner_radius": 0.0, "flute_length": 50.8,
    "stepdown": 4.0, "optimal_load": 2.0, "stock_to_leave": 0.381,
    "rest_stepup": 1.905, "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 13, "units": "mm", "program_number": 1001,
    "model": {
        "kind": "file", "format": "step", "name": "fake.step",
        "sha256": hashlib.sha256(FAKE_STEP).hexdigest(),
        "bytes": len(FAKE_STEP),
        "url": "http://127.0.0.1:9/fake.step", "headers": {},
        "document": {"id": "doc-pc"}, "revision": 1,
    },
}

LAUNCHER = """import sys, time
sys.path.insert(0, %(here)r)
sys.path.insert(0, %(connector_dir)r)
import runner
from runner import Cancelled

FAKE_STEP = b"STEPFAKE-PANELCANCEL"
DURATION = %(duration)r


def fake_run(self, step_path, values, on_progress=None):
    if on_progress:
        on_progress(0.05, "faking")
    deadline = time.time() + DURATION
    while time.time() < deadline:
        if self.cancelled:
            raise Cancelled("cancelled")
        time.sleep(0.05)
    return {"files": []}, {}


runner.EngineRun.run = fake_run

import client as client_mod
client_mod.SteveClient.download = lambda self, url, headers=None: FAKE_STEP

import connector
sys.exit(connector.main())
"""


def start_connector(tmp_path, mock, duration, connector_dir=None):
    """MockSteve (already serving) + a connector subprocess in its message
    loop: enrolled, confirmed, status.json says "idle". Returns (proc, home)."""
    cdir = connector_dir or CONNECTOR_DIR
    if not os.path.isdir(os.path.join(cdir, "panel")):
        # publish_catalog_and_panel() reads panel/ next to ITS connector.py
        os.symlink(os.path.join(HERE, "panel"),
                   os.path.join(cdir, "panel"))
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "config.toml", "w") as fh:
        fh.write('base_url = "%s"\npairing_code = "PAIR-1234"\n'
                 'poll_wait = 1\ntoken_retry = 1\n'
                 'programs_dir = "%s"\nrepo_root = "%s"\n'
                 % (mock.base_url, tmp_path / "programs", REPO))
    launcher = tmp_path / "launch.py"
    with open(launcher, "w") as fh:
        fh.write(LAUNCHER % {"here": HERE,
                             "connector_dir": connector_dir or CONNECTOR_DIR,
                             "duration": duration})
    env = dict(os.environ)
    env["STEVE_BASE_URL"] = mock.base_url
    env.pop("STEVECAM_HOME", None)
    proc = subprocess.Popen([PY, str(launcher), "--home", str(home)],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        assert mock.wait_enroll(30), "connector never enrolled"
        mock.confirm()
        deadline = time.time() + 30
        while time.time() < deadline:
            assert proc.poll() is None, "connector died before idle"
            if status_state(home) == "idle":
                return proc, home
            time.sleep(0.1)
        raise AssertionError("connector never reached idle")
    except Exception:
        shutdown(proc)
        raise


def status_state(home):
    try:
        with open(os.path.join(str(home), "status.json")) as fh:
            return json.load(fh).get("state")
    except (OSError, ValueError):
        return None


def shutdown(proc, timeout=25):
    """SIGTERM the exact PID we started; hard-kill only if it ignores it."""
    if proc.poll() is None:
        os.kill(proc.pid, signal.SIGTERM)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return None
    return None


def wait_status(home, want, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline and status_state(home) != want:
        time.sleep(0.1)
    return status_state(home)


def forge_cancel(mock, run_id):
    """Like mock.enqueue_cancel but with a MUTATED (random) signature -
    built directly to avoid racing the loop against the sig rewrite."""
    env = {"id": None, "run": run_id,
           "connector": mock.enrolled["fingerprint"],
           "issued_at": int(time.time()),
           "expires_at": int(time.time()) + 900,
           "nonce": crypto.b64(os.urandom(12)).rstrip("=")}
    msg = {"id": None, "kind": "cancel", "envelope": env, "kid": mock.kid,
           "sig": crypto.b64(os.urandom(64))}   # bad signature
    with mock.cond:
        msg["id"] = mock.next_id
        mock.next_id += 1
        mock.messages.append(msg)
        mock.cond.notify_all()
    return msg


# ---------------------------------------------------------- (a) mid-job ----

def test_cancel_mid_job(tmp_path):
    """(a) cancel for the ACTIVE run ends the >=30 s job with "cancelled"
    within N (=CANCEL_N, see results) seconds, status.json ends "idle";
    SIGTERM then exits 0 with the pidfile released.
    """
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, LONG)
        mock.enqueue_run(7001, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(7001, "running", timeout=30), \
            "job never reported running"
        t0 = time.time()
        mock.enqueue_cancel(7001)
        term = mock.wait_terminal(7001, timeout=CANCEL_N)
        elapsed = time.time() - t0
        print("PANELCANCEL BRANCH MEASUREMENT: terminal=%r after %.2f s "
              "(N=%s s; the fake job would run %.0f s)"
              % (term, elapsed, CANCEL_N, LONG))
        assert term == "cancelled", \
            "no terminal 'cancelled' within N=%s s (got %r after %.1f s)" \
            % (CANCEL_N, term, elapsed)
        assert elapsed < LONG - 10, \
            "job ran to its end instead of being cancelled"
        states = mock.states_for(7001)
        assert "succeeded" not in states and states[-1] == "cancelled"
        assert wait_status(home, "idle") == "idle", \
            "status.json did not return to idle after the cancel"
        # the fake job would still have ~20 s left: nothing else ran
        assert mock.states_for(7001).count("cancelled") == 1
        rc = shutdown(proc)
        assert rc == 0, "measured exit code: %s" % rc
        proc = None
        assert not (home / "connector.pid").exists()
    finally:
        shutdown(proc) if proc else None
        mock.stop()


@pytest.mark.skipif(os.environ.get("PANELCANCEL_MEASURE_MAIN") != "1",
                    reason="permanently asserts 2da9125's broken behaviour "
                           "and costs ~12 s per run; set "
                           "PANELCANCEL_MEASURE_MAIN=1 to measure it "
                           "(PANELCANCEL3 item 3; body unchanged)")
def test_cancel_mid_job_fails_on_main_connector(tmp_path):
    """(a)-main-measurement: the same scenario against the UNMODIFIED
    connector.py of 2da9125 (git show into a scratch copy): the cancel
    message is only read after the job ended, so the job is NOT cancelled
    within N (=CANCEL_N) seconds. This test asserts the OLD (broken)
    behaviour.
    """
    try:
        src = subprocess.run(["git", "-C", REPO, "show",
                              "2da9125:connector/connector.py"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git show unavailable")
    if src.returncode != 0:
        pytest.skip("git show 2da9125 failed: %s" % src.stderr[-200:])
    scratch = tmp_path / "main_connector"
    scratch.mkdir()
    (scratch / "connector.py").write_text(src.stdout)
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, LONG,
                                     connector_dir=str(scratch))
        mock.enqueue_run(7101, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(7101, "running", timeout=30)
        t0 = time.time()
        mock.enqueue_cancel(7101)
        term = mock.wait_terminal(7101, timeout=CANCEL_N)
        elapsed = time.time() - t0
        print("PANELCANCEL MAIN MEASUREMENT: cancel for the ACTIVE run -> "
              "terminal=%r after %.1f s (job would fake-run %.0f s, still "
              "'running' -> not cancelled within N=%s s)"
              % (term, elapsed, LONG, CANCEL_N))
        assert term != "cancelled", \
            "main connector cancelled mid-job (unexpected) after %.1f s" \
            % elapsed
        assert "running" in mock.states_for(7101), \
            "job was not even running when the cancel arrived"
    finally:
        shutdown(proc) if proc else None
        mock.stop()


# ------------------------------------------------------- (b) other id ------

def test_cancel_other_id_ignored(tmp_path):
    """(b) cancels for a QUEUED run id and an UNKNOWN id are ignored: the
    active job completes "succeeded" (and so does the queued one)."""
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, 4.0)
        mock.enqueue_run(8001, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(8001, "running", timeout=30)
        mock.enqueue_run(8002, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        time.sleep(1.5)                 # the loop reads 8002 while 8001 runs
        mock.enqueue_cancel(8002)       # queued id -> ignored
        mock.enqueue_cancel(99999)      # unknown id -> ignored
        assert mock.wait_terminal(8001, timeout=30) == "succeeded"
        assert "cancelled" not in mock.states_for(8001)
        assert mock.wait_terminal(8002, timeout=30) == "succeeded"
        assert "cancelled" not in mock.states_for(8002)
        assert wait_status(home, "idle") == "idle"
    finally:
        shutdown(proc) if proc else None
        mock.stop()


# -------------------------------------------------------- (c) forged -------

def test_forged_cancel_ignored(tmp_path):
    """(c) a cancel whose signature does not verify is ignored silently:
    the active job completes "succeeded" and nothing is reported for the
    cancel itself."""
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, 4.0)
        mock.enqueue_run(8101, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(8101, "running", timeout=30)
        forge_cancel(mock, 8101)        # matching id, BAD signature
        assert mock.wait_terminal(8101, timeout=30) == "succeeded"
        states = mock.states_for(8101)
        assert "cancelled" not in states and "rejected" not in states
        with mock.lock:
            others = [r for r in mock.reports if str(r["run_id"]) != "8101"]
        assert others == [], "the forged cancel was reported: %r" % others
    finally:
        shutdown(proc) if proc else None
        mock.stop()


# ---------------------------------------------------- (d) second job -------

def test_second_job_waits(tmp_path):
    """(d) a second job enqueued while the first runs waits: it is
    "received" only after the first is terminal; terminal order ==
    enqueue order; one at a time."""
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, 3.0)
        mock.enqueue_run(9001, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(9001, "running", timeout=30)
        mock.enqueue_run(9002, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        time.sleep(1.5)                 # 9001 still runs (3 s fake job)
        assert mock.states_for(9002) == [], \
            "the queued job started while the first still ran"
        assert mock.wait_terminal(9001, timeout=30) == "succeeded"
        assert mock.wait_terminal(9002, timeout=30) == "succeeded"
        with mock.lock:
            reps = [(str(r["run_id"]), r["body"]["state"])
                    for r in mock.reports]
        first_9002 = min(i for i, (rid, _s) in enumerate(reps)
                         if rid == "9002")
        last_9001 = max(i for i, (rid, _s) in enumerate(reps)
                        if rid == "9001")
        assert last_9001 < first_9002, \
            "9002 was reported before 9001 ended: %r" % reps
        assert reps[first_9002][1] == "received"
        assert wait_status(home, "idle") == "idle"
    finally:
        shutdown(proc) if proc else None
        mock.stop()


# =============== PANELCANCEL3 (appended; existing tests untouched) =========
# SIGTERM handler ONLY sets a threading.Event; cancel + join + queued-job
# rejection happen in run_forever's tail, outside signal context.
#
# (a) test_sigterm_while_spawn_holds_lock: SIGTERM while the EngineRun's
#     non-reentrant self._lock (the one cancel() takes, held by the real
#     _spawn around Popen) is HELD by a running job.
# (c) test_queued_job_rejected_on_shutdown: a job still queued at shutdown
#     gets ONE terminal "rejected" report, code "connector_stopping".
#
# MUTATION M2 (scratch copy only, run via PANELCANCEL_CONNECTOR_DIR): the
# handler calls cancel() directly -> test (a) hangs / times out (measured,
# recorded in PANELCANCEL_RESULTS.md; the hard bound is proc.wait's
# SIGTERM_N timeout - never an infinite wait).

SIGTERM_N = 10.0   # N: seconds allowed for exit 0 after SIGTERM in (a)/(c)
LOCK_HOLD = 3.0    # s the fake job holds the EngineRun's self._lock

LAUNCHER_LOCKHOLD = """import sys, time
sys.path.insert(0, %(here)r)
sys.path.insert(0, %(connector_dir)r)
import runner
from runner import Cancelled

FAKE_STEP = b"STEPFAKE-PANELCANCEL"
DURATION = %(duration)r
HOLD = %(hold)r


def fake_run(self, step_path, values, on_progress=None):
    if on_progress:
        on_progress(0.05, "faking")
    # The EXACT lock EngineRun.cancel() must take, held the way the real
    # _spawn holds it around Popen (here: HOLD s of sleep instead of a
    # fork/exec). Nothing inside checks self.cancelled - while this is
    # held, any cancel() call blocks on the lock.
    with self._lock:
        hold_until = time.time() + HOLD
        while time.time() < hold_until:
            time.sleep(0.05)
    deadline = time.time() + DURATION
    while time.time() < deadline:
        if self.cancelled:
            raise Cancelled("cancelled")
        time.sleep(0.05)
    return {"files": []}, {}


runner.EngineRun.run = fake_run

import client as client_mod
client_mod.SteveClient.download = lambda self, url, headers=None: FAKE_STEP

import connector
sys.exit(connector.main())
"""


def start_connector_lockhold(tmp_path, mock, duration, hold):
    """start_connector with the lock-holding fake (LAUNCHER_LOCKHOLD): the
    job reports "running", then holds the EngineRun's own non-reentrant
    self._lock for `hold` s.

    Honest-equivalence note (brief (a)): with the worker design jobs run
    on the FIFO WORKER thread, so the thread a signal can interrupt (the
    MAIN thread) is never inside _spawn's `with self._lock:`. The property
    under test is what the HANDLER must guarantee: it does no work at all
    (only Event.set()), so it cannot block or deadlock on the held lock;
    the cancel that must wait for that lock runs later, on the loop
    thread, outside signal context. Holding the lock on the worker thread
    while SIGTERM arrives still forces every shutdown path except the
    handler to face the blocked-cancel situation, which is exactly the
    failure a cancel()-calling handler would have hit (deadlock-prone,
    seconds of teardown in signal context)."""
    cdir = CONNECTOR_DIR
    if not os.path.isdir(os.path.join(cdir, "panel")):
        os.symlink(os.path.join(HERE, "panel"),
                   os.path.join(cdir, "panel"))
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "config.toml", "w") as fh:
        fh.write('base_url = "%s"\npairing_code = "PAIR-1234"\n'
                 'poll_wait = 1\ntoken_retry = 1\n'
                 'programs_dir = "%s"\nrepo_root = "%s"\n'
                 % (mock.base_url, tmp_path / "programs", REPO))
    launcher = tmp_path / "launch_lockhold.py"
    with open(launcher, "w") as fh:
        fh.write(LAUNCHER_LOCKHOLD % {"here": HERE, "connector_dir": cdir,
                                      "duration": duration, "hold": hold})
    env = dict(os.environ)
    env["STEVE_BASE_URL"] = mock.base_url
    env.pop("STEVECAM_HOME", None)
    proc = subprocess.Popen([PY, str(launcher), "--home", str(home)],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        assert mock.wait_enroll(30), "connector never enrolled"
        mock.confirm()
        deadline = time.time() + 30
        while time.time() < deadline:
            assert proc.poll() is None, "connector died before idle"
            if status_state(home) == "idle":
                return proc, home
            time.sleep(0.1)
        raise AssertionError("connector never reached idle")
    except Exception:
        shutdown(proc)
        raise


def test_sigterm_while_spawn_holds_lock(tmp_path):
    """(a) SIGTERM while the run's self._lock is HELD (fake job holds it
    LOCK_HOLD s on the worker thread - the closest honest equivalent under
    the worker design, see start_connector_lockhold). The handler only
    sets the Event; the loop sees it within one <=1 s poll slice, then the
    shutdown tail cancels (blocking on the held lock OUTSIDE signal
    context), joins the worker, writes status "off", main() releases the
    pidfile and exits 0. Hard bound SIGTERM_N (measured); no hang."""
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector_lockhold(tmp_path, mock, LONG,
                                              LOCK_HOLD)
        mock.enqueue_run(7301, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(7301, "running", timeout=30), \
            "job never reported running"
        # "running" is reported BEFORE the fake takes the lock, and the
        # hold lasts LOCK_HOLD s: SIGTERM lands while the lock is held.
        t0 = time.time()
        os.kill(proc.pid, signal.SIGTERM)     # the exact PID we started
        rc = proc.wait(timeout=SIGTERM_N)     # hard timeout: never infinite
        elapsed = time.time() - t0
        print("PANELCANCEL3 (a) MEASUREMENT: SIGTERM while the run lock is "
              "held -> exit %s after %.2f s (N=%s s; lock held %.1f s, the "
              "fake job would run %.0f s)"
              % (rc, elapsed, SIGTERM_N, LOCK_HOLD, LONG))
        assert rc == 0, "measured exit code: %s" % rc
        proc = None
        assert not (home / "connector.pid").exists(), "pidfile not removed"
        assert wait_status(home, "off", timeout=2.0) == "off", \
            "status.json did not say 'off'"
        assert mock.wait_terminal(7301, timeout=5.0) == "cancelled", \
            "the held-lock job was not cancelled"
    finally:
        shutdown(proc) if proc else None
        mock.stop()


def test_queued_job_rejected_on_shutdown(tmp_path):
    """(c) job A (long fake) runs, job B enqueued behind it (remembered +
    queued, no reports yet); SIGTERM: A ends "cancelled"; B gets exactly
    ONE "rejected" report, error code "connector_stopping", message
    "connector shut down before this run started"; B never reaches
    "running" (never executed at all); exit 0; pidfile removed; status
    "off"."""
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, LONG)
        mock.enqueue_run(7401, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(7401, "running", timeout=30), \
            "job A never reported running"
        mock.enqueue_run(7402, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        time.sleep(1.5)               # the loop reads 7402 while 7401 runs
        assert mock.states_for(7402) == [], \
            "the queued job started while A still ran"
        t0 = time.time()
        os.kill(proc.pid, signal.SIGTERM)   # the exact PID we started
        rc = proc.wait(timeout=SIGTERM_N)   # hard timeout
        print("PANELCANCEL3 (c) MEASUREMENT: SIGTERM with A running + B "
              "queued -> exit %s after %.2f s" % (rc, time.time() - t0))
        assert rc == 0, "measured exit code: %s" % rc
        proc = None
        assert not (home / "connector.pid").exists(), "pidfile not removed"
        assert wait_status(home, "off", timeout=2.0) == "off", \
            "status.json did not say 'off'"
        states_a = mock.states_for(7401)
        assert states_a[-1] == "cancelled", \
            "active job A did not end 'cancelled': %r" % states_a
        states_b = mock.states_for(7402)
        assert states_b == ["rejected"], \
            "queued job B did not get exactly one 'rejected': %r" % states_b
        assert "running" not in states_b and "received" not in states_b, \
            "the queued job was executed: %r" % states_b
        with mock.lock:
            body_b = [r["body"] for r in mock.reports
                      if str(r["run_id"]) == "7402"]
        err = body_b[0].get("error") or {}
        assert err.get("code") == "connector_stopping", err
        assert err.get("message") == \
            "connector shut down before this run started", err
    finally:
        shutdown(proc) if proc else None
        mock.stop()
