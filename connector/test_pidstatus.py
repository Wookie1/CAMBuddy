"""Task MENUBAR red tests (a), (b), (c): the connector refuses to start a
second instance (pidfile), takes over stale/foreign pidfiles, and keeps a
secret-free status.json next to state.json.

Fast: in-process Connector with stubbed network + short-lived subprocesses.
Run through the small-test lane:
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_pidstatus.py
"""
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

import connector as connector_mod  # noqa: E402
import crypto                      # noqa: E402
from client import SteveError      # noqa: E402
from mock_steve import MockSteve   # noqa: E402

REFUSAL = ("connector already running (pid %d); "
           "not starting a second one")


# ------------------------------------------- (a) second instance refuses ---

def test_second_connector_refuses(tmp_path):
    """A live connector.py PID in <home>/connector.pid makes a second
    `connector.py --home <home>` refuse: exit 0, exact line, pidfile kept."""
    home = tmp_path / "home"
    home.mkdir()
    dummy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)",
         "connector/connector.py"])
    try:
        (home / "connector.pid").write_text("%d\n" % dummy.pid)
        env = dict(os.environ)
        env["STEVE_BASE_URL"] = "http://127.0.0.1:9"
        env["CAMBUDDY_HOME"] = str(home)
        out = subprocess.run(
            [sys.executable, os.path.join(REPO, "connector", "connector.py"),
             "--home", str(home)],
            capture_output=True, text=True, timeout=15, env=env, cwd=REPO)
        assert out.returncode == 0, out.stderr[-400:]
        assert REFUSAL % dummy.pid in out.stdout, out.stdout[-400:]
        assert int((home / "connector.pid").read_text().strip()) == dummy.pid
    finally:
        dummy.kill()
        dummy.wait()


# ------------------------------------------------ (b) stale pid takeover ---

def test_stale_pidfile_is_taken_over(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    pidfile = home / "connector.pid"

    # a PID that is not alive any more
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    pidfile.write_text("%d\n" % dead.pid)
    ok, other = connector_mod.acquire_pidfile(str(home))
    assert ok is True and other is None
    assert int(pidfile.read_text().strip()) == os.getpid()
    connector_mod.release_pidfile(str(home))
    assert not pidfile.exists()

    # a live PID that is some other program (sleep, not connector.py)
    sleeper = subprocess.Popen(["sleep", "60"])
    try:
        pidfile.write_text("%d\n" % sleeper.pid)
        ok, other = connector_mod.acquire_pidfile(str(home))
        assert ok is True and other is None
        assert int(pidfile.read_text().strip()) == os.getpid()
        # release removes only OUR pid
        pidfile.write_text("%d\n" % sleeper.pid)
        connector_mod.release_pidfile(str(home))
        assert int(pidfile.read_text().strip()) == sleeper.pid
    finally:
        sleeper.kill()
        sleeper.wait()
        if pidfile.exists():
            pidfile.unlink()


# ------------------------------------------------------- (c) status file ---

@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """In-process Connector on a temp home, network calls stubbed."""
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "config.toml", "w") as fh:
        fh.write('base_url = "http://127.0.0.1:9"\nrepo_root = "%s"\n' % REPO)
    c = connector_mod.Connector(str(home))
    # a fake trusted-key value + a state that would carry secrets: none of
    # these may ever reach status.json
    c.state["steve_keys"] = {"kid-1": "SUPERSECRET-STEVE-KEY-B64=="}
    c._save()
    yield c, home
    del monkeypatch


def test_status_file(conn, monkeypatch):
    c, home = conn
    status = home / "status.json"
    posted = []
    monkeypatch.setattr(c.client, "post_event",
                        lambda name, data: posted.append((name, data)))

    c.emit_state("busy", "adaptive_rough", 0.42)
    st = json.loads(status.read_text())
    assert st["state"] == "busy"
    assert st["action"] == "adaptive_rough"
    assert st["progress"] == 0.42
    assert st["pid"] == os.getpid()
    assert st["updated"].endswith("Z")
    assert "commit" in st
    assert st["fingerprint"] == c.fingerprint
    assert len(posted) == 1

    # an unchanged event still refreshes status.json (but posts nothing)
    time.sleep(0.01)
    c.emit_state("busy", "adaptive_rough", 0.42)
    st2 = json.loads(status.read_text())
    assert st2["updated"] != st["updated"]
    assert len(posted) == 1

    # a failing post_event still updates status.json
    def boom(name, data):
        raise SteveError("network", "down")
    monkeypatch.setattr(c.client, "post_event", boom)
    c.emit_state("idle", None, None)
    st3 = json.loads(status.read_text())
    assert st3["state"] == "idle"

    # the file text carries no secrets
    text = status.read_text()
    secret = crypto.b64(c.sk.private_bytes_raw())
    forbidden = [secret, "SUPERSECRET-STEVE-KEY-B64==", "steve_keys",
                 "token", "pairing"]
    low = text.lower()
    for bad in forbidden:
        assert bad not in text and bad.lower() not in low, bad


def test_last_run_refreshed_in_record_run_end(conn, monkeypatch):
    c, home = conn
    monkeypatch.setattr(c.client, "post_event", lambda name, data: None)
    c.emit_state("idle")
    assert json.loads((home / "status.json").read_text())["last_run"] is None
    c.record_run_end("1001", "adaptive_rough", "doc-7")
    st = json.loads((home / "status.json").read_text())
    assert st["last_run"] is not None
    assert st["last_run"]["run_id"] == "1001"
    assert st["last_run"]["action"] == "adaptive_rough"


# ------------------------------------------------ MENUBAR2: SIGTERM exit 0 --

def test_sigterm_exits_zero(tmp_path):
    """MENUBAR2: a REAL `connector.py --home <tmp>` child running its message
    loop against a local fake STEVE (mock_steve.MockSteve, a stdlib
    http.server thread on 127.0.0.1:<free port>) exits 0 on SIGTERM: the
    handler sets _stop, the loop ends after the current <=1 s long-poll,
    main() releases the pidfile and returns 0, status.json says "off"."""
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "config.toml", "w") as fh:
        fh.write('pairing_code = "PAIR-1234"\npoll_wait = 1\ntoken_retry = 1\n'
                 'programs_dir = "%s"\nrepo_root = "%s"\n'
                 % (tmp_path / "programs", REPO))
    mock = MockSteve(code="PAIR-1234")
    base = mock.serve_forever()          # 127.0.0.1 on a free port
    env = dict(os.environ)
    env["STEVE_BASE_URL"] = base
    env.pop("CAMBUDDY_HOME", None)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "connector.py"), "--home",
         str(home)], cwd=REPO, env=env,
         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert mock.wait_enroll(20), "connector never enrolled"
        mock.confirm()
        # wait until the child's own status.json says "idle" (<= 20 s):
        # it has passed enroll/token/publish and sits in the message loop
        status = home / "status.json"
        pidfile = home / "connector.pid"
        deadline = time.time() + 20

        def _status_state():
            try:
                with open(status) as fh:
                    return json.load(fh).get("state")
            except (OSError, ValueError):
                return None

        while time.time() < deadline and _status_state() != "idle":
            assert proc.poll() is None, "connector died before idle"
            time.sleep(0.1)
        assert _status_state() == "idle", "status.json never said idle"
        assert int(pidfile.read_text().strip()) == proc.pid

        os.kill(proc.pid, signal.SIGTERM)   # the exact PID we started
        rc = proc.wait(timeout=15)
        assert rc == 0, "measured exit code: %s" % rc
        assert not pidfile.exists(), "connector.pid not released"
        assert _status_state() == "off"
    finally:
        if proc.poll() is None:            # only our own child, exact PID
            proc.kill()
            proc.wait()
        mock.stop()
