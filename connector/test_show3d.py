"""Task SHOW3D red tests (a), (b), (c): the view.load action returns a run's
stored 3D view files byte-identically and refuses unsafe ids, and the
last_runs event carries the newest <= 10 runs, always < 8 kB.

Fast: in-process Connector against the local MockSteve (no engine, no
subprocess). Run through the small-test lane:
    <lane> /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider \
        connector/test_show3d.py
"""
import builtins
import hashlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import connector as connector_mod  # noqa: E402
from mock_steve import MockSteve  # noqa: E402

VIEW_LOAD = "view.load"
LAST_RUNS = "last_runs"
MAX_EVENT = 8 * 1024


@pytest.fixture()
def conn(tmp_path):
    """Mock STEVE + an enrolled in-process Connector on a temp home."""
    mock = MockSteve(code="PAIR-1234")
    base = mock.serve_forever()
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "config.toml", "w") as fh:
        fh.write('base_url = "%s"\npairing_code = "PAIR-1234"\n'
                 'repo_root = "%s"\n' % (base, REPO))
    mock.confirm()
    c = connector_mod.Connector(str(home))
    c.enroll()
    c.get_token_blocking()
    c.publish_catalog_and_panel()
    yield c, mock, home
    mock.stop()


def dispatch(mock, c, action, inputs, run_id):
    mock.enqueue_run(run_id, action=action, inputs=inputs)
    c.handle_message(mock.messages[-1])
    return mock.wait_terminal(run_id, timeout=10)


def final_report(mock, run_id):
    with mock.lock:
        reps = [r["body"] for r in mock.reports
                if str(r["run_id"]) == str(run_id)]
    return reps[-1] if reps else None


def make_view_run(home, run_id, pngs=True):
    d = home / "runs" / str(run_id)
    d.mkdir(parents=True)
    data = {"view.bin": b"VIEWBIN-" + str(run_id).encode() + b"\x00\x01\x02",
            "view.json": json.dumps({"format": "cambuddy-view",
                                     "version": 2}).encode()}
    if pngs:
        data["view_iso.png"] = b"\x89PNG-iso"
        data["view_top.png"] = b"\x89PNG-top"
    for name, blob in data.items():
        (d / name).write_bytes(blob)
    return d, data


# ------------------------------------------------------- (a) run files -----

def test_view_load_returns_run_files(conn):
    c, mock, home = conn
    d, data = make_view_run(home, "4242")
    assert dispatch(mock, c, VIEW_LOAD, {"run_id": "4242"}, 9001) \
        == "succeeded", final_report(mock, 9001)
    assert sorted(mock.file_names(9001)) == sorted(data)
    for name, blob in data.items():
        info = mock.file_info(9001, name)
        assert info["sha256"] == hashlib.sha256(blob).hexdigest(), name
    assert mock.file_info(9001, "view.bin")["media"] == \
        "application/octet-stream"
    assert mock.file_info(9001, "view.json")["media"] == "application/json"
    assert mock.file_info(9001, "view_iso.png")["media"] == "image/png"
    # the source run's files are untouched (copies, not moves)
    for name, blob in data.items():
        assert (d / name).read_bytes() == blob
    # a run without the pictures: only the two data files are uploaded
    make_view_run(home, "4243", pngs=False)
    assert dispatch(mock, c, VIEW_LOAD, {"run_id": "4243"}, 9002) \
        == "succeeded", final_report(mock, 9002)
    assert sorted(mock.file_names(9002)) == ["view.bin", "view.json"]
    # the action is declared in the published catalog
    assert VIEW_LOAD in [a["name"] for a in mock.catalog["actions"]]
    body = final_report(mock, 9001)
    assert body["result"]["run_id"] == "4242"
    assert sorted(body["result"]["files"]) == sorted(data)


# ------------------------------------------------------- (b) refusals ------

BAD_IDS = ["", "..", "../x", "a/b", "/tmp/evil",
           "/private/var", "a b", "run.id", "x" * 65, "..%2fx", "\u00e9"]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_view_load_refuses_bad_ids(conn, bad):
    c, mock, home = conn
    (home / "runs").mkdir(parents=True)
    (home / "runs" / "777").mkdir()          # exists, but no view.*
    outside = home / "outside"               # a runs/ symlink pointing out
    outside.mkdir()
    (outside / "view.bin").write_bytes(b"OUTSIDE-BIN")
    (outside / "view.json").write_bytes(b"{}")
    os.symlink(str(outside), str(home / "runs" / "link-out"))
    rid = 9100 + BAD_IDS.index(bad)
    final = dispatch(mock, c, VIEW_LOAD, {"run_id": bad}, rid)
    assert final in ("rejected", "failed"), (bad, final)
    assert mock.file_names(rid) == [], "a refusal uploaded files for %r" % bad
    body = final_report(mock, rid)
    err = body.get("error") or {}
    assert err.get("code"), "refusal without a clear code for %r: %s" % (
        bad, body)
    assert err["code"] != "action_unknown", "view.load is not an action: %s" % (
        err,)
    assert err["code"] != "internal_error", "raw failure for %r: %s" % (
        bad, err)


def test_view_load_refuses_symlink_run_without_reading_outside(conn):
    """The link-out run holds a valid view outside <home>/runs: refused,
    nothing uploaded, and NO file below the outside dir was ever opened."""
    c, mock, home = conn
    (home / "runs").mkdir(parents=True)
    outside = home / "outside2"
    outside.mkdir()
    (outside / "view.bin").write_bytes(b"OUTSIDE-BIN")
    (outside / "view.json").write_bytes(b"{}")
    os.symlink(str(outside), str(home / "runs" / "link-out"))
    opened = []
    real_open = builtins.open

    def spy_open(file, *a, **k):
        opened.append(os.path.abspath(str(file)))
        return real_open(file, *a, **k)
    builtins.open = spy_open
    try:
        final = dispatch(mock, c, VIEW_LOAD, {"run_id": "link-out"}, 9250)
    finally:
        builtins.open = real_open
    assert final in ("rejected", "failed"), final
    assert mock.file_names(9250) == []
    assert not [p for p in opened if p.startswith(str(outside) + os.sep)], \
        "read a file outside <home>/runs: %s" % opened
    body = final_report(mock, 9250)
    code = (body.get("error") or {}).get("code")
    assert code and code != "action_unknown", body


def test_view_load_refuses_run_without_view(conn):
    c, mock, home = conn
    d = home / "runs" / "5555"
    d.mkdir(parents=True)
    (d / "check.json").write_bytes(b"{}")    # a run without view.*
    assert dispatch(mock, c, VIEW_LOAD, {"run_id": "5555"}, 9260) \
        in ("rejected", "failed")
    assert mock.file_names(9260) == []
    body = final_report(mock, 9260)
    assert "no 3D view" in (body.get("error") or {}).get("message", ""), body


# ---------------------------------------------------- (c) last_runs --------

def test_last_runs_event_shape(conn):
    import time as _t
    c, mock, home = conn
    doc = "D" * 128
    ids = []
    for i in range(25):
        rid = ("%04x" % i).rjust(4, "0") + "-" + "f" * (59 - len("%04x" % i))
        ids.append(rid)
        d = home / "runs" / rid
        d.mkdir(parents=True)
        if i % 2 == 0:                       # the even runs have a view
            (d / "view.bin").write_bytes(b"B")
            (d / "view.json").write_bytes(b"{}")
        c.record_run_end(rid, "adaptive_rough" if i % 3 else
                         "check_program", doc)
        _t.sleep(0.002)                      # distinct at values
    evs = [e for e in mock.events if e["name"] == LAST_RUNS]
    assert evs, "no last_runs event was posted"
    runs = evs[-1]["data"]["runs"]
    assert len(runs) == 10, "expected the 10 newest, got %d" % len(runs)
    assert [r["run_id"] for r in runs] == list(reversed(ids[-10:])), \
        "not the 10 newest first"
    for r in runs:
        assert set(r) >= {"run_id", "action", "document_id", "at",
                          "has_view"}
        assert r["document_id"] == doc
        assert r["action"] in ("adaptive_rough", "check_program")
        assert r["has_view"] == (int(r["run_id"][:4], 16) % 2 == 0)
    size = len(json.dumps(evs[-1]["data"]).encode("utf-8"))
    assert size < MAX_EVENT, "last_runs event is %d bytes >= 8 kB" % size
    # every run end posted one (the count never shrinks)
    assert len(evs) == 25


def test_last_runs_declared_in_catalog(conn):
    c, mock, _home = conn
    assert LAST_RUNS in [e["name"] for e in mock.catalog["events"]], \
        mock.catalog["events"]


# ------------------------- run-id by exact directory match (coordinator) ----
def test_view_load_accepts_any_existing_run_dir_name(conn):
    """STEVE's run-id format is not assumed: an id with ':' and '.' that is
    the exact name of a run dir loads."""
    c, mock, home = conn
    rid = "run:2026-10-28.v1"
    _, data = make_view_run(home, rid)
    assert dispatch(mock, c, VIEW_LOAD, {"run_id": rid}, 9301) == "succeeded", \
        final_report(mock, 9301)
    assert sorted(mock.file_names(9301)) == sorted(data)


@pytest.mark.parametrize("bad", ["..", "../x", "/private/tmp", ".hidden",
                                 "a/b", "a\\b", "a\x00b", "x" * 129,
                                 "run:2026-10-28.v1x"])
def test_view_load_refuses_non_child_ids(conn, bad):
    """Only an exact existing child name loads: '..', '../x', absolute
    paths, dot-names, separators, NUL, over-long ids and near-misses of a
    real name are refused, and nothing is uploaded."""
    c, mock, home = conn
    make_view_run(home, "run:2026-10-28.v1")
    hid = home / "runs" / ".hidden"
    hid.mkdir()
    (hid / "view.bin").write_bytes(b"HIDDEN")
    (hid / "view.json").write_bytes(b"{}")
    rid = 9400 + abs(hash(bad)) % 500
    final = dispatch(mock, c, VIEW_LOAD, {"run_id": bad}, rid)
    assert final in ("rejected", "failed"), (bad, final)
    assert mock.file_names(rid) == [], "a refusal uploaded files for %r" % bad


def test_view_load_refuses_symlinked_dir_with_listed_name(conn):
    """A symlink in runs/ whose name is listed by os.listdir but which points
    outside <home>/runs is refused by the realpath containment check."""
    c, mock, home = conn
    (home / "runs").mkdir(parents=True)
    outside = home / "outside"
    outside.mkdir()
    (outside / "view.bin").write_bytes(b"OUTSIDE-BIN")
    (outside / "view.json").write_bytes(b"{}")
    os.symlink(str(outside), str(home / "runs" / "run:linked.out"))
    assert "run:linked.out" in os.listdir(str(home / "runs"))
    final = dispatch(mock, c, VIEW_LOAD, {"run_id": "run:linked.out"}, 9901)
    assert final in ("rejected", "failed"), final
    assert mock.file_names(9901) == []
