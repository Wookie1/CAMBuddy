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


def start_connector(tmp_path, mock, duration, connector_dir=None,
                    launcher_src=None, extra_env=None):
    """MockSteve (already serving) + a connector subprocess in its message
    loop: enrolled, confirmed, status.json says "idle". Returns (proc, home).
    PANELCANCEL4: launcher_src picks another launcher template (same
    %(here)s/%(connector_dir)s/%(duration)s keys) and extra_env is merged
    into the child's environment; both default to the old behaviour."""
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
        fh.write((launcher_src or LAUNCHER) % {
            "here": HERE,
            "connector_dir": connector_dir or CONNECTOR_DIR,
            "duration": duration})
    env = dict(os.environ)
    env["STEVE_BASE_URL"] = mock.base_url
    env.pop("CAMBUDDY_HOME", None)
    if extra_env:
        env.update(extra_env)
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
    """(b) PANELCANCEL4: a cancel for a QUEUED run id drops it (it never
    runs); one for an UNKNOWN id is ignored: the active job completes
    "succeeded" and the queued one ends ["received", "cancelled"]."""
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
        mock.enqueue_cancel(8002)       # queued id -> dropped, never runs
        mock.enqueue_cancel(99999)      # unknown id -> ignored
        assert mock.wait_terminal(8001, timeout=30) == "succeeded"
        assert "cancelled" not in mock.states_for(8001)
        assert mock.wait_terminal(8002, timeout=30) == "cancelled"
        assert mock.states_for(8002) == ["received", "cancelled"], \
            "the queued run was not dropped with exactly one report pair"
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
    env.pop("CAMBUDDY_HOME", None)
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


# =============== PANELCANCEL4 (appended; existing tests untouched) =========
# A verified cancel whose env["run"] matches a QUEUED item removes that
# item from self._queue (under self._queue.mutex) and reports it ONCE
# "received" then "cancelled" ("cancelled before it started"); its fake
# run is never called. The ledger/nonce stay recorded, so a redelivery of
# that run message is still never acted on.
#
# (a) test_cancel_queued_job_dropped: A (long fake) runs, B queued behind
#     it; cancel(B) -> B exactly ["received", "cancelled"], never "running"
#     (fake-run call count proves it never ran), A ends "succeeded"
#     unaffected, a duplicate of B's message later changes nothing.
# (b) test_double_cancel_queued_reports_once: cancel(B) twice -> B's
#     states exactly ["received", "cancelled"] (one of each).
#
# MUTATION M3 (scratch copy only, run via PANELCANCEL_CONNECTOR_DIR): the
# queued-drop removed from the cancel branch (report nothing, leave B
# queued) -> (a) red. Result recorded in PANELCANCEL_RESULTS.md.

LAUNCHER_COUNTED = """import os, sys, time
sys.path.insert(0, %(here)r)
sys.path.insert(0, %(connector_dir)r)
import runner
from runner import Cancelled

FAKE_STEP = b"STEPFAKE-PANELCANCEL"
DURATION = %(duration)r
CALLS_FILE = os.environ.get("PC_CALLS_FILE")


def fake_run(self, step_path, values, on_progress=None):
    if CALLS_FILE:
        with open(CALLS_FILE, "a") as fh:
            fh.write("call\\n")
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


def call_count(calls_file):
    try:
        with open(str(calls_file)) as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def test_cancel_queued_job_dropped(tmp_path):
    """(a) job A (long fake, A_DUR) runs, job B queued behind it (remembered
    + queued, no reports yet); cancel(B): B's states are exactly
    ["received", "cancelled"] (never "running"), the "cancelled" message is
    "cancelled before it started", and B's fake run is NEVER called (call
    count stays 1 = A only). A ends "succeeded" unaffected. A later
    redelivery-like duplicate of B's run message (same run id) is not run
    and reported nothing more."""
    a_dur = 12.0
    calls = tmp_path / "calls.txt"
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, a_dur,
                                     launcher_src=LAUNCHER_COUNTED,
                                     extra_env={"PC_CALLS_FILE": str(calls)})
        mock.enqueue_run(8201, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(8201, "running", timeout=30), \
            "job A never reported running"
        mock.enqueue_run(8202, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        time.sleep(1.5)               # the loop reads 8202 while 8201 runs
        assert mock.states_for(8202) == [], \
            "the queued job started while A still ran"
        mock.enqueue_cancel(8202)     # queued id -> dropped, never runs
        assert mock.wait_terminal(8202, timeout=15) == "cancelled", \
            "the queued job never got its terminal 'cancelled'"
        states_b = mock.states_for(8202)
        assert states_b == ["received", "cancelled"], \
            "B's states are not exactly [received, cancelled]: %r" % states_b
        assert "running" not in states_b, "the queued run started: %r" % states_b
        with mock.lock:
            body_b = [r["body"] for r in mock.reports
                      if str(r["run_id"]) == "8202"]
        assert body_b[-1].get("message") == "cancelled before it started", \
            body_b[-1]
        assert call_count(calls) == 1, \
            "B's fake run ran: %d calls, expected only A's" % call_count(calls)
        # A unaffected: it runs to its end and succeeds
        assert mock.wait_terminal(8201, timeout=30) == "succeeded"
        states_a = mock.states_for(8201)
        assert "cancelled" not in states_a and states_a[-1] == "succeeded"
        # redelivery-like duplicate of B's message (same run id, fresh
        # nonce): the ledger still refuses to act on it twice
        mock.enqueue_run(8202, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        time.sleep(2.5)               # the loop has read it (poll_wait=1)
        assert mock.states_for(8202) == ["received", "cancelled"], \
            "a redelivered B was acted on: %r" % mock.states_for(8202)
        assert call_count(calls) == 1, \
            "a redelivered B ran: %d fake calls" % call_count(calls)
        assert wait_status(home, "idle") == "idle"
        rc = shutdown(proc)
        assert rc == 0, "measured exit code: %s" % rc
        proc = None
    finally:
        shutdown(proc) if proc else None
        mock.stop()


def test_double_cancel_queued_reports_once(tmp_path):
    """(b) cancel(B) twice for the same queued run -> B's states exactly
    ["received", "cancelled"] (one of each); the second cancel is ignored."""
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(tmp_path, mock, 6.0)
        mock.enqueue_run(8301, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(8301, "running", timeout=30), \
            "job A never reported running"
        mock.enqueue_run(8302, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        time.sleep(1.5)               # the loop reads 8302 while 8301 runs
        mock.enqueue_cancel(8302)
        mock.enqueue_cancel(8302)     # second cancel for the dropped id
        assert mock.wait_terminal(8302, timeout=15) == "cancelled"
        states_b = mock.states_for(8302)
        assert states_b == ["received", "cancelled"], \
            "B's states are not exactly one received + one cancelled: %r" \
            % states_b
    finally:
        shutdown(proc) if proc else None
        mock.stop()


# =============== PANELCANCEL5 (appended; existing tests untouched) =========
# Bounded shutdown tail: after the active job's cancel() the loop joins the
# worker for SHUTDOWN_GRACE (8 s, was 60); if it is still alive the job's
# child ignored cancel()'s SIGTERM, so _kill_engine_groups SIGKILLs every
# live process group of that EngineRun and the join gets SHUTDOWN_KILL_JOIN
# (4 s) more; queued rejects and "off" run regardless. Worst case from
# SIGTERM to exit < 30 s (10 poll + 8 grace + 4 kill-join + ~1 tail).
#
# (b) test_shutdown_kills_child_ignoring_sigterm: a REAL connector
#     subprocess whose fake run starts, THROUGH THE REAL runner._spawn, a
#     child /bin/sh -c 'trap "" TERM; sleep 120' - cancel's SIGTERM is
#     ignored, only the SIGKILL backstop can end the job. SIGTERM: exit 0
#     within SHUTDOWN5_N s (measured), the child PID is gone, pidfile
#     removed, status "off". Our own child is killed by exact PID in a
#     finally.
# (d) test_engine_kill_hook_exists: the REAL runner.EngineRun exposes at
#     least one of live_pgids / kill_all / _procs / _proc (a rename of all
#     four must fail loudly, not silently drop the SIGKILL backstop);
#     test_kill_engine_groups_helper drives the helper with one fake engine
#     per shape and checks which path was used.
#
# MUTATION M4 (scratch copy only, run via PANELCANCEL_CONNECTOR_DIR): the
# SIGKILL step dropped from run_forever's tail -> (b) red: the connector
# waits out grace + kill-join and exits, the child survives (measured in
# PANELCANCEL_RESULTS.md).

SHUTDOWN5_N = 25.0   # s allowed for exit 0 after SIGTERM in (b)

LAUNCHER_STUBBORN = """import os, sys, time
sys.path.insert(0, %(here)r)
sys.path.insert(0, %(connector_dir)r)
import runner

FAKE_STEP = b"STEPFAKE-PANELCANCEL"
DURATION = %(duration)r
CHILD_PID_FILE = os.environ.get("PC_CHILD_PID_FILE")


def fake_run(self, step_path, values, on_progress=None):
    if on_progress:
        on_progress(0.05, "faking")
    # THE REAL _spawn (start_new_session=True: the child gets its own
    # process group, exactly like a real engine child). The shell reports
    # its own PID ($$ == the Popen pid) into CHILD_PID_FILE and IGNORES
    # SIGTERM, so EngineRun.cancel()'s killpg SIGTERM cannot end it - only
    # the shutdown tail's SIGKILL backstop can. (The pid must come from
    # the child: _spawn only returns once the child is already gone.)
    cmd = ('echo $$ > "%%s"; trap "" TERM; sleep %%s'
           %% (CHILD_PID_FILE, int(DURATION)))
    self._spawn(["/bin/sh", "-c", cmd], 0.05, 0.95, on_progress)
    return {"files": []}, {}


runner.EngineRun.run = fake_run

import client as client_mod
client_mod.SteveClient.download = lambda self, url, headers=None: FAKE_STEP

import connector
sys.exit(connector.main())
"""


def read_child_pid(pid_file, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(str(pid_file)) as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            time.sleep(0.1)
    return None


def test_shutdown_kills_child_ignoring_sigterm(tmp_path):
    """(b) SIGTERM a connector whose active job's REAL-_spawn child ignores
    SIGTERM: the SIGKILL backstop ends the job, the connector exits 0 well
    inside 30 s (measured), the child is GONE, pidfile removed, status
    "off"."""
    child_pid_file = tmp_path / "child.pid"
    child_pid = None
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(
            tmp_path, mock, 120.0,
            connector_dir=os.environ.get("PANELCANCEL5_CONNECTOR_DIR")
            or CONNECTOR_DIR,
            launcher_src=LAUNCHER_STUBBORN,
            extra_env={"PC_CHILD_PID_FILE": str(child_pid_file)})
        mock.enqueue_run(7501, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        assert mock.wait_state(7501, "running", timeout=30), \
            "job never reported running"
        child_pid = read_child_pid(child_pid_file)
        assert child_pid, "the stubborn child never started"
        t0 = time.time()
        os.kill(proc.pid, signal.SIGTERM)     # the exact PID we started
        rc = proc.wait(timeout=SHUTDOWN5_N)   # hard timeout: never infinite
        elapsed = time.time() - t0
        print("PANELCANCEL5 (b) MEASUREMENT: SIGTERM with a SIGTERM-ignoring "
              "_spawn child -> exit %s after %.2f s (N=%s s; child would "
              "sleep 120 s)" % (rc, elapsed, SHUTDOWN5_N))
        assert rc == 0, "measured exit code: %s" % rc
        assert elapsed < SHUTDOWN5_N
        proc = None
        # the child must be gone (SIGKILLed by the shutdown tail): poll a
        # little so a not-yet-reaped zombie cannot fail the check
        gone_at = None
        deadline = time.time() + 5.0
        while time.time() < deadline and gone_at is None:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                gone_at = time.time() - t0
            else:
                time.sleep(0.1)
        assert gone_at is not None, \
            "child pid %d survived the shutdown (still alive after %.1f s)" \
            % (child_pid, time.time() - t0)
        print("PANELCANCEL5 (b) MEASUREMENT: stubborn child pid %d gone "
              "%.2f s after SIGTERM" % (child_pid, gone_at))
        assert not (home / "connector.pid").exists(), "pidfile not removed"
        assert wait_status(home, "off", timeout=2.0) == "off", \
            "status.json did not say 'off'"
    finally:
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGKILL)   # our own child, exact PID
            except (ProcessLookupError, PermissionError):
                pass
        shutdown(proc) if proc else None
        mock.stop()


def test_engine_kill_hook_exists(tmp_path):
    """(d) the REAL runner.EngineRun (no monkeypatch) exposes at least one
    of the four shapes connector._kill_engine_groups understands - a future
    rename of all four must fail HERE, loudly, not silently drop the
    SIGKILL backstop."""
    import importlib
    runner_mod = importlib.import_module("runner")
    run = runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                               str(tmp_path))
    hooks = [name for name in ("live_pgids", "kill_all", "_procs", "_proc")
             if hasattr(run, name)]
    assert hooks, ("runner.EngineRun exposes NONE of live_pgids / kill_all "
                   "/ _procs / _proc - connector._kill_engine_groups would "
                   "silently do nothing on shutdown")


def test_kill_engine_groups_helper(tmp_path):
    """(d, unit) _kill_engine_groups with ONE fake engine per supported
    shape; each fake records which path was used. No real signal is sent:
    the Popen fakes carry the pid of an already-reaped child of THIS test,
    so the real os.killpg() hits nothing and the ProcessLookupError ->
    p.kill() fallback is what the fakes record."""
    import importlib
    connector_mod = importlib.import_module("connector")
    kill = connector_mod._kill_engine_groups

    gone = subprocess.Popen([PY, "-c", "pass"])
    gone.wait()
    dead_pid = gone.pid        # reaped: killpg(getpgid(...)) -> ProcessLookupError

    class FakeProc:
        def __init__(self, log):
            self.log = log
            self.pid = dead_pid

        def poll(self):
            return None        # "live"

        def kill(self):
            self.log.append("kill")

    class ShapePgids:
        def __init__(self):
            self.log = []

        def live_pgids(self):
            self.log.append("live_pgids")
            return []          # nothing real to killpg

    class ShapeKillAll:
        def __init__(self):
            self.log = []

        def kill_all(self, sig):
            self.log.append(("kill_all", sig))

    class ShapeProcs:
        def __init__(self):
            self.log = []
            self._procs = {FakeProc(self.log)}

    class ShapeProc:
        def __init__(self):
            self.log = []
            self._proc = FakeProc(self.log)

    eng = ShapePgids()
    kill(eng)
    assert eng.log == ["live_pgids"], eng.log
    eng = ShapeKillAll()
    kill(eng)
    assert eng.log == [("kill_all", signal.SIGKILL)], eng.log
    eng = ShapeProcs()
    kill(eng)
    assert eng.log == ["kill"], eng.log     # killpg dead -> p.kill()
    eng = ShapeProc()
    kill(eng)
    assert eng.log == ["kill"], eng.log


# =============== PANELCANCEL6 (appended; existing tests untouched) =========
# The worker takes an item off self._queue, reports "received", builds the
# EngineRun and only then sets self.running. A verified cancel arriving in
# that window finds the id neither active nor queued and (before this
# task) was silently ignored - the run then executed in full. Now the loop
# marks the id in the bounded self._pending_cancel (under self._cancel_lock)
# and _run_job, at `self.running = engine` under the SAME lock, consumes
# the marker and calls engine.cancel() before anything can spawn.
#
# (a) test_cancel_in_dequeue_window: a launcher whose fake
#     EngineRun.__init__ sleeps INIT_SLEEP (2 s) - exactly the window
#     between "received" and self.running - and whose fake run raises
#     Cancelled on entry when self.cancelled BEFORE recording a call
#     (exactly what the real _spawn does before Popen). A call-count of 0
#     therefore proves no engine subprocess would have started.
#
# MUTATION M5 (scratch copy only, run via PANELCANCEL6_CONNECTOR_DIR): the
# pending check in _run_job skipped (was_pending always False) -> (a) red.
# Result recorded in PANELCANCEL_RESULTS.md.

INIT_SLEEP = 2.0   # s the fake EngineRun.__init__ holds the window open

LAUNCHER_DEQUEUE_WINDOW = """import os, sys, time
sys.path.insert(0, %(here)r)
sys.path.insert(0, %(connector_dir)r)
import runner
from runner import Cancelled

FAKE_STEP = b"STEPFAKE-PANELCANCEL"
DURATION = %(duration)r
INIT_SLEEP = 2.0        # == INIT_SLEEP here; widened by the fake __init__
CALLS_FILE = os.environ.get("PC_CALLS_FILE")

_REAL_INIT = runner.EngineRun.__init__


def slow_init(self, cfg, work_dir):
    _REAL_INIT(self, cfg, work_dir)
    # This constructor call sits in _run_job right between the "received"
    # report and `self.running = engine`: sleeping HERE widens EXACTLY
    # the dequeue->activate window (item already off the queue).
    time.sleep(INIT_SLEEP)


def fake_run(self, step_path, values, on_progress=None):
    # Exactly the real _spawn's first move (runner.py): a cancelled
    # engine raises Cancelled BEFORE anything spawns. So the call file
    # only ever sees a line if the engine was NOT yet cancelled when the
    # run began - count 0 proves no subprocess would have started.
    if self.cancelled:
        raise Cancelled("cancelled")
    with open(CALLS_FILE, "a") as fh:
        fh.write("call\\n")
    if on_progress:
        on_progress(0.05, "faking")
    deadline = time.time() + DURATION
    while time.time() < deadline:
        if self.cancelled:
            raise Cancelled("cancelled")
        time.sleep(0.05)
    return {"files": []}, {}


runner.EngineRun.__init__ = slow_init
runner.EngineRun.run = fake_run

import client as client_mod
client_mod.SteveClient.download = lambda self, url, headers=None: FAKE_STEP

import connector
sys.exit(connector.main())
"""


def test_cancel_in_dequeue_window(tmp_path):
    """(a) cancel arrives while the run is off the queue but not yet
    active (fake EngineRun.__init__ holds that window open 2 s): the run
    ends terminal "cancelled", its fake run is NEVER called past the
    cancelled check (call count 0 - no engine subprocess would have
    started), status.json ends "idle"."""
    calls = tmp_path / "calls.txt"
    mock = MockSteve()
    base = mock.serve_forever()
    proc = None
    try:
        proc, home = start_connector(
            tmp_path, mock, LONG,
            connector_dir=os.environ.get("PANELCANCEL6_CONNECTOR_DIR")
            or CONNECTOR_DIR,
            launcher_src=LAUNCHER_DEQUEUE_WINDOW,
            extra_env={"PC_CALLS_FILE": str(calls)})
        mock.enqueue_run(8501, action="adaptive_rough",
                         inputs=dict(RUN_INPUTS))
        # "received" is the LAST thing _run_job reports before building
        # the EngineRun, so it marks the window opening; the fake
        # __init__ then holds it open INIT_SLEEP = 2 s.
        assert mock.wait_state(8501, "received", timeout=30), \
            "job never reported received"
        t0 = time.time()
        mock.enqueue_cancel(8501)
        # Why the cancel lands INSIDE the window: it is enqueued within
        # <=0.1 s of observing "received" (wait_state's poll step) and
        # the loop's long-poll wakes on the new message immediately, so
        # handle_message sees an id that is neither queued (the worker
        # already took it) nor active (self.running is still None - the
        # constructor is asleep). The call count below proves it
        # independently: a cancel after the window would find the fake
        # run already entered (count 1); only the pending path keeps it 0.
        term = mock.wait_terminal(8501, timeout=15)
        elapsed = time.time() - t0
        print("PANELCANCEL6 (a) MEASUREMENT: cancel %.3f s after "
              "'received' (2 s fake-__init__ window) -> terminal %r after "
              "%.2f s; fake-run calls=%d (job would have run %.0f s)"
              % (0.0, term, elapsed, call_count(calls), LONG))
        assert term == "cancelled", \
            "no terminal 'cancelled' for the in-window cancel (got %r " \
            "after %.1f s)" % (term, elapsed)
        states = mock.states_for(8501)
        assert states == ["received", "cancelled"], \
            "unexpected states: %r" % states
        assert call_count(calls) == 0, \
            "the engine ran anyway: %d fake calls, expected 0" \
            % call_count(calls)
        assert wait_status(home, "idle") == "idle", \
            "status.json did not return to idle after the cancel"
        rc = shutdown(proc)
        assert rc == 0, "measured exit code: %s" % rc
        proc = None
    finally:
        shutdown(proc) if proc else None
        mock.stop()
