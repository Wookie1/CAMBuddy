"""STEVE connector v1 (roughing). Separate light process: stdlib + crypto.py.

Flow: enroll -> pending -> token (retry while pending_confirmation) ->
PUT /catalog -> PUT /panels -> long-poll GET /messages -> verify envelopes
(steve_keys pinned at enroll; newer /keys lists only if signed by a trusted
key) -> download+check inputs -> run engine -> upload files -> report states.
Persistent ledger: never act on a run id twice. Never contacts
stevecad.studio unless the configured base_url says so; tests point it at
the local mock.
"""
import datetime
import hashlib
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog as catalog_mod  # noqa: E402
import config as config_mod    # noqa: E402
import crypto                  # noqa: E402
import toollib                 # noqa: E402
import envelope                # noqa: E402
import errors                  # noqa: E402
from client import SteveClient, SteveError  # noqa: E402
from runner import EngineRun, EngineError, Cancelled  # noqa: E402

VERSION = "1.0.0"
PANEL_NAME = catalog_mod.ACTION
# SHOW3D: this connector's own run-id shape (the ids STEVE sends: digits or
# uuid-like). No separators, no dots: anything else is refused unread.
RUN_ID_MAX = 128             # view.load run_id length cap (STEVE's id format is not assumed)
LAST_RUNS_MAX = 10           # the last_runs event lists at most this many
LAST_RUNS_MAX_BYTES = 8 * 1024   # event data stays under 8 kB


# --------------------------------------------------------------- pidfile --
def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_is_connector(pid):
    """True when PID's command line mentions connector.py."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return "connector.py" in out.stdout


def acquire_pidfile(home):
    """MENUBAR: claim <home>/connector.pid for os.getpid() -> (True, None).
    (False, PID) only when a live connector.py already holds it. No file,
    unreadable content, a dead PID or a live PID of some other program are
    all taken over. Written atomically (tmp + os.replace)."""
    path = os.path.join(config_mod.state_dir(home), "connector.pid")
    other = None
    try:
        with open(path) as fh:
            other = int(fh.read().strip())
    except (OSError, ValueError):
        other = None
    if (other is not None and other > 0 and other != os.getpid()
            and _pid_alive(other) and _pid_is_connector(other)):
        return False, other
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("%d\n" % os.getpid())
    os.replace(tmp, path)
    return True, None


def release_pidfile(home):
    """Remove <home>/connector.pid only when it holds our own PID."""
    path = os.path.join(config_mod.state_dir(home), "connector.pid")
    try:
        with open(path) as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return
    if pid == os.getpid():
        try:
            os.remove(path)
        except OSError:
            pass


def prepare_values(values_in, action):
    """Run inputs -> (ok, code, mm values). Task UN: convert inch inputs to
    mm FIRST (an omitted units input is the catalog default, inch: task
    (a)), then validate the mm values against the catalog's mm ranges.
    Track 2: job renumbering follows the STEVE document - an explicit
    document_id, else the model's own document."""
    raw = values_in
    values_in = catalog_mod.to_mm(values_in, action)
    spec = catalog_mod.get_action(action) or {}
    takes_doc = "document_id" in spec.get("inputs", {}).get("properties", {})
    if takes_doc and not values_in.get("document_id"):
        doc = (values_in.get("model") or {}).get("document") \
            if isinstance(values_in.get("model"), dict) else None
        if isinstance(doc, dict) and doc.get("id"):
            values_in = dict(values_in, document_id=str(doc["id"]))
    ok, out = catalog_mod.validate(values_in, action, raw=raw)
    if not ok:
        return False, out["code"], out  # out = the agent error (task f)
    return True, "", out


class Connector:
    def __init__(self, home_override=None):
        self.cfg = config_mod.load(home_override)
        self.home = self.cfg["home"]
        os.makedirs(self.home, exist_ok=True)
        self.sk = crypto.load_or_create_key(os.path.join(self.home,
                                                        "identity.key"))
        self.fingerprint = crypto.fingerprint(crypto.public_raw(self.sk))
        self.state_path = os.path.join(self.home, "state.json")
        self.ledger_path = os.path.join(self.home, "ledger.json")
        self.state = self._load_json(self.state_path, {})
        self.ledger = self._load_json(self.ledger_path,
                                     {"runs": [], "nonces": []})
        self.client = SteveClient(self.cfg["base_url"], self.sk)
        self.running = None          # active EngineRun (for cancel)
        self.current_run = None
        self._last_event = None
        self._last_keys_refresh = 0.0
        # PANELCANCEL3: the SIGTERM/SIGINT handler ONLY sets this Event
        # (no cancel, no join, no I/O, no status write - it runs on the
        # MAIN thread between bytecodes, possibly while that thread holds
        # a non-reentrant lock). Every read is an is_set() check; the
        # shutdown work happens in run_forever's tail, outside signals.
        self._stop = threading.Event()
        # PANELCANCEL: jobs and tool actions run on ONE long-lived FIFO
        # worker while the message loop keeps polling (only "cancel" is
        # handled there). self._lock serializes status/event/report writes
        # between the worker and the loop; the worker exists only while
        # run_forever runs - direct handle_message callers stay inline.
        self._queue = queue.Queue()
        self._worker = None
        self._lock = threading.RLock()
        # PANELCANCEL4: run ids dropped from the queue by a cancel, so a
        # second cancel for the same id reports nothing twice. Only the
        # loop thread touches it (cancels are handled on the loop thread
        # while the worker exists; direct callers are single-threaded).
        self._dropped = set()
        # MENUBAR: <home>/status.json for the menu-bar app (secret-free).
        self.status_path = os.path.join(self.home, "status.json")
        self.commit = self._git_commit()
        self.last_run = self._newest_run()

    # -------------------------------------------------------------- status --
    def _git_commit(self):
        """Short HEAD of the repo this connector runs from ('' on failure),
        computed once at start."""
        try:
            out = subprocess.run(
                ["git", "-C", self.cfg["repo_root"], "rev-parse", "--short",
                 "HEAD"], capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def _newest_run(self):
        """The newest entry of _last_runs_data()["runs"], or None. Never
        raises."""
        try:
            runs = self._last_runs_data().get("runs") or []
            return runs[0] if runs else None
        except Exception:
            return None

    def _write_status(self, state, action=None, progress=None):
        """Atomic <home>/status.json: {pid, state, action, progress,
        updated (UTC ISO), fingerprint, connector_name, commit, last_run}.
        NEVER carries keys, steve_keys, tokens, identity or the pairing
        code. Never raises into the run loop. PANELCANCEL: serialized by
        self._lock (worker vs loop; RLock so emit_state may nest)."""
        try:
            with self._lock:
                data = {"pid": os.getpid(), "state": state, "action": action,
                        "progress": progress, "updated": self._utc_now(),
                        "fingerprint": self.fingerprint,
                        "connector_name": self.cfg["connector_name"],
                        "commit": self.commit, "last_run": self.last_run}
                tmp = self.status_path + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(data, fh, sort_keys=True)
                os.replace(tmp, self.status_path)
        except Exception:
            pass

    # ------------------------------------------------------------ persist --
    @staticmethod
    def _load_json(path, default):
        if os.path.exists(path):
            with open(path) as fh:
                return json.load(fh)
        return default

    def _save(self):
        for path, obj in ((self.state_path, self.state),
                         (self.ledger_path, self.ledger)):
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(obj, fh)
            os.replace(tmp, path)

    def _remember_run(self, run_id):
        if run_id not in self.ledger["runs"]:
            self.ledger["runs"].append(run_id)
        self._save()

    def _remember_nonce(self, nonce):
        if nonce and nonce not in self.ledger["nonces"]:
            self.ledger["nonces"].append(nonce)
        self._save()

    # ------------------------------------------------------------ startup --
    def enroll(self):
        st = self.state
        if st.get("enrolled"):
            return  # token is memory-only: get_token_blocking() re-fetches
        pub = crypto.b64(crypto.public_raw(self.sk))
        out = self.client.enroll(self.cfg["pairing_code"], pub,
                                self.cfg["connector_name"], VERSION,
                                catalog_mod.published_catalog())
        signed = out.get("steve_keys") or {}
        keys = {}
        try:
            for k in signed["list"]["keys"]:
                keys[k["kid"]] = k["public_key"]
        except (KeyError, TypeError):
            keys = {}
        if not keys:
            raise SteveError("keys_untrusted",
                            "enroll response carries no usable steve_keys")
        # self-consistency: the enroll keys list must carry at least one
        # valid signature by a key in that same list
        if not crypto.verify_signed_list(keys, signed):
            raise SteveError("keys_untrusted",
                            "enroll steve_keys list is not signed by a key "
                            "in the list itself")
        st["enrolled"] = True
        st["fingerprint"] = out["fingerprint"]
        st["cursor"] = 0
        st["steve_keys"] = keys
        self._save()

    def refresh_steve_keys(self):
        """Accept a newer GET /keys list only if signed by a trusted key."""
        try:
            listing = self.client.get_keys()
        except SteveError:
            return
        trusted = self.state.get("steve_keys", {})
        if not trusted or not crypto.verify_signed_list(trusted, listing):
            return
        try:
            keys = {k["kid"]: k["public_key"] for k in listing["list"]["keys"]}
        except (KeyError, TypeError):
            return
        if keys and keys != trusted:
            self.state["steve_keys"] = keys
            self._save()

    def get_token_blocking(self):
        while not self._stop.is_set():
            try:
                return self.client.get_token()  # token stays in memory only
            except SteveError as e:
                if e.code != "pending_confirmation":
                    raise
                time.sleep(float(self.cfg["token_retry"]))

    def publish_catalog_and_panel(self):
        self.client.put_catalog(catalog_mod.published_catalog())
        panel_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "panel")
        files = {}
        for name in sorted(os.listdir(panel_dir)):
            path = os.path.join(panel_dir, name)
            if not os.path.isfile(path) or name == "dev.html":
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                files[name] = data.decode("utf-8")
            except UnicodeDecodeError:
                files[name] = "base64:" + crypto.b64(data)
        self.client.put_panel(PANEL_NAME, "STEVE CAM roughing", ["right"],
                             files)

    # ------------------------------------------------------------- events --
    def emit_state(self, state, action=None, progress=None):
        data = {"state": state, "action": action, "progress": progress}
        # MENUBAR: status.json is refreshed on EVERY call, even when the
        # event is unchanged or the post below fails.
        # PANELCANCEL: the _last_event check/update, the status write and
        # the post are ONE critical section (worker vs loop).
        with self._lock:
            self._write_status(state, action, progress)
            if data == self._last_event:
                return
            self._last_event = data
            try:
                self.client.post_event(catalog_mod.EVENT, data)
            except SteveError:
                pass

    def _report(self, run_id, state, **kw):
        """PANELCANCEL: client.report_run serialized against the other
        thread's writes (same self._lock; exception behaviour unchanged -
        SteveError propagates to the caller's existing handlers)."""
        with self._lock:
            return self.client.report_run(run_id, state, **kw)

    # ----------------------------------------------------------- messages --
    def verify_envelope(self, msg):
        """Return (ok, code). Trust, signature, fingerprint, expiry, nonce."""
        kid = msg.get("kid")
        keys = self.state.get("steve_keys", {})
        if kid not in keys:
            return False, "kid_untrusted"
        env = msg.get("envelope") or {}
        if not crypto.verify_envelope(crypto.unb64(keys[kid]), env,
                                     msg.get("sig", "")):
            return False, "envelope_sig_invalid"
        if env.get("connector") != self.fingerprint:
            return False, "connector_mismatch"
        issued = crypto.parse_time(env.get("issued_at"))
        expires = crypto.parse_time(env.get("expires_at"))
        if issued is None or expires is None:
            return False, "envelope_bad_time"
        if expires <= time.time():
            return False, "envelope_expired"
        if env.get("nonce") in self.ledger["nonces"]:
            return False, "nonce_replayed"
        return True, ""

    def handle_message(self, msg):
        ok, code = self.verify_envelope(msg)
        env = msg.get("envelope") or {}
        run_id = env.get("id")
        kind = msg.get("kind")
        if kind == "cancel":
            # PANELCANCEL: a cancel is acted on ONLY when its envelope
            # verifies (a forged/expired/unknown-kid one is ignored
            # silently, no report).
            # PANELCANCEL4: it names either the ACTIVE run (unchanged: the
            # worker's `except Cancelled` path reports "cancelled" once and
            # ends the run, status.json ends "idle") or a QUEUED one: that
            # item is removed from the FIFO queue under self._queue.mutex
            # (the very lock queue.Queue.get()/put() take, so the worker
            # cannot pick the item off between our check and our removal)
            # and reported ONCE "received" then "cancelled" (STEVE's state
            # machine, mirrored in mock_steve.NEXT_OK, only allows
            # "received"/"rejected" as a run's first report and
            # "cancelled" only after "received"). Its engine/tool action
            # never starts; the ledger/nonce stay recorded, so a
            # redelivery of that run is never acted on again. A cancel for
            # any other id (finished, unknown, or already dropped) is
            # ignored, no report.
            if not ok:
                return
            target = env.get("run")
            if self.running and self.current_run == target:
                self.running.cancel()
                return
            if target in self._dropped:
                return          # second cancel for a dropped id: ignored
            with self._queue.mutex:
                for item in list(self._queue.queue):
                    if item[1] == target:
                        self._queue.queue.remove(item)
                        self._dropped.add(target)
                        break
                else:
                    return      # not queued (finished/unknown): ignored
            try:
                self._report(target, "received")
                self._report(target, "cancelled",
                             message="cancelled before it started")
            except SteveError:
                pass
            return
        if not ok:
            if run_id is not None and code != "nonce_replayed":
                self._safe_reject(run_id, code)
            return
        if run_id is None:
            return
        if run_id in self.ledger["runs"]:
            return  # never act twice
        self._remember_nonce(env.get("nonce"))
        action = env.get("action")
        if action not in catalog_mod.ENGINE_ACTIONS + catalog_mod.TOOL_ACTIONS:
            self._remember_run(run_id)
            self._safe_reject(run_id, "action_unknown")
            return
        self._remember_run(run_id)
        if action in catalog_mod.TOOL_ACTIONS:
            self._dispatch(("tool", run_id, env, action))
            return
        self._dispatch(("job", run_id, env, action))

    # ------------------------------------------------------------- worker --
    def _dispatch(self, item):
        """PANELCANCEL: while run_forever is up, jobs and tool actions go
        to the FIFO worker (arrival order, one at a time - exactly today's
        ordering) and the loop keeps polling; without a worker (direct
        callers, e.g. tests) they run inline as before."""
        if self._worker is not None:
            self._queue.put(item)
        else:
            self._exec(item)

    def _exec(self, item):
        kind, run_id, env, action = item
        if kind == "tool":
            self._run_tool_action(run_id, env, action)
        else:
            self._run_job(run_id, env, action)

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if self._stop.is_set():
                # PANELCANCEL3: shutdown was requested while this item was
                # already off the queue - put it BACK unrun; run_forever's
                # tail rejects every still-queued item and nothing queued
                # is ever executed.
                self._queue.put(item)
                break
            try:
                self._exec(item)
            except Exception:
                pass  # one bad job must not kill the worker

    def tool_action(self, action, values):
        """Track 2: tools.list / tools.update / job.get / job.renumber on
        the library (<home>/tools.json) and the per-document jobs
        (<home>/jobs/). Returns the result; ToolLibError -> {code,
        message}."""
        home, repo = self.home, self.cfg["repo_root"]
        if action == catalog_mod.TOOLS_LIST:
            return toollib.tools_list(home, repo)
        if action == catalog_mod.TOOLS_UPDATE:
            return toollib.update_tool(home, repo, values.get("tool_id"),
                                       values.get("changes"),
                                       values.get("pockets"))
        if action == catalog_mod.JOB_GET:
            return toollib.job_get(home, values["document_id"])
        if action == catalog_mod.JOB_SETUP:
            return toollib.set_setup(home, values["document_id"],
                                     values["setup"])
        return toollib.renumber(home, repo, values["document_id"],
                                values["tool_id"], values["t"])

    # ------------------------------------------------------------ show3d --
    VIEW_FILES = (("view.bin", "application/octet-stream"),
                  ("view.json", "application/json"),
                  ("view_iso.png", "image/png"),
                  ("view_top.png", "image/png"))

    def _view_load_files(self, run_id):
        """SHOW3D: [(name, path, media)] for view.load, or None to refuse.
        STEVE's run-id format is not assumed: run_id must EXACTLY equal the
        name of an existing direct child of <home>/runs (os.listdir, string
        equality), never contain '/', '\\' or NUL, never start with '.',
        and be <= RUN_ID_MAX long; the directory must resolve INSIDE
        <home>/runs (no symlink escape); view.bin + view.json must be plain
        files in it (the pictures are optional). Nothing is ever read
        outside <home>/runs."""
        if (not isinstance(run_id, str) or not 0 < len(run_id) <= RUN_ID_MAX
                or run_id.startswith(".")
                or any(ch in run_id for ch in ("/", "\\", "\0"))):
            return None
        root = os.path.realpath(os.path.join(self.home, "runs"))
        try:
            if run_id not in os.listdir(root):
                return None
        except OSError:
            return None
        d = os.path.join(root, run_id)
        if os.path.realpath(d) != d or not os.path.isdir(d):
            return None
        out = []
        for name, media in self.VIEW_FILES:
            p = os.path.join(d, name)
            if os.path.realpath(p) != p or not os.path.isfile(p):
                if name in ("view.bin", "view.json"):
                    return None      # no 3D view for that run
                continue
            out.append((name, p, media))
        return out

    def _run_view_load(self, run_id, values):
        """SHOW3D: upload byte-copies of another run's view files as the
        files of this view.load run (display only; runs fast, no engine)."""
        src = self._view_load_files(values.get("run_id"))
        if src is None:
            err = errors.make_error("no_view", "no 3D view for that run",
                                    field="run_id")
            try:
                self._report(
                    run_id, "failed", error=err,
                    result=envelope.for_failure(catalog_mod.VIEW_ACTION,
                                                err))
            except SteveError:
                pass
            return
        try:
            for name, path, media in src:
                with open(path, "rb") as fh:
                    self.client.put_file(run_id, name, fh.read(), media)
            result = {"run_id": values["run_id"],
                      "files": [n for n, _p, _m in src]}
            result = dict(result, **envelope.for_tool_action(
                catalog_mod.VIEW_ACTION, result))
            self._report(run_id, "succeeded", result=result,
                                   message="done")
        except SteveError:
            pass

    @staticmethod
    def _utc_now():
        return datetime.datetime.now(
            datetime.timezone.utc).isoformat(
                timespec="milliseconds").replace("+00:00", "Z")

    def record_run_end(self, run_id, action, document_id):
        """SHOW3D: a cutting/check run ended - keep a small per-run meta
        file (<home>/runs/<id>/run_meta.json) and post the last_runs event.
        Never raises into the run loop."""
        try:
            d = os.path.join(self.home, "runs", str(run_id))
            has_view = (os.path.isfile(os.path.join(d, "view.bin"))
                        and os.path.isfile(os.path.join(d, "view.json")))
            meta = {"run_id": str(run_id), "action": str(action),
                    "document_id": str(document_id or ""),
                    "at": self._utc_now(), "has_view": bool(has_view)}
            os.makedirs(d, exist_ok=True)
            tmp = os.path.join(d, "run_meta.json.tmp")
            with open(tmp, "w") as fh:
                json.dump(meta, fh, sort_keys=True)
            os.replace(tmp, os.path.join(d, "run_meta.json"))
        except OSError:
            pass
        # MENUBAR: refresh last_run (and status.json) with the new entry.
        # PANELCANCEL: same lock as emit_state's status/event writes.
        with self._lock:
            self.last_run = self._newest_run()
            ev = self._last_event or {}
            self._write_status(ev.get("state", "idle"), ev.get("action"),
                               ev.get("progress"))
            try:
                self.client.post_event(catalog_mod.LAST_RUNS_EVENT,
                                       self._last_runs_data())
            except SteveError:
                pass

    def _last_runs_data(self):
        """The newest <= LAST_RUNS_MAX recorded runs, newest first, always
        under 8 kB of JSON (fields are length-capped; entries are dropped
        from the end if it were ever not enough). "state" is a snapshot of
        the engine being idle when the run history is posted, so every
        event's data carries a state."""
        root = os.path.join(self.home, "runs")
        entries = []
        try:
            names = os.listdir(root)
        except OSError:
            names = []
        for n in names:
            try:
                with open(os.path.join(root, n, "run_meta.json")) as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(m, dict):
                continue
            entries.append({"run_id": str(m.get("run_id", n))[:64],
                            "action": str(m.get("action", ""))[:64],
                            "document_id": str(m.get("document_id", ""))[:128],
                            "at": str(m.get("at", ""))[:32],
                            "has_view": bool(m.get("has_view"))})
        entries.sort(key=lambda e: (e["at"], e["run_id"]), reverse=True)
        runs = entries[:LAST_RUNS_MAX]
        data = {"state": "idle", "runs": runs}
        while runs and len(json.dumps(data).encode("utf-8")) \
                >= LAST_RUNS_MAX_BYTES:
            runs.pop()
            data = {"state": "idle", "runs": runs}
        return data

    def _run_tool_action(self, run_id, env, action):
        try:
            self._report(run_id, "received")
        except SteveError:
            pass
        ok, values = catalog_mod.validate(env.get("inputs", {}), action)
        try:
            if not ok:
                self._report(run_id, "rejected", error=values)
                return
            self._report(run_id, "running", progress=0.5,
                                   message=action)
            if action == catalog_mod.VIEW_ACTION:
                return self._run_view_load(run_id, values)
            try:
                result = self.tool_action(action, values)
            except toollib.ToolLibError as e:
                err = e.as_dict()
            except Exception as e:  # never a raw traceback to the caller
                self._log_exception(run_id)
                err = errors.make_error("library_error", type(e).__name__)
            else:
                result = dict(result, **envelope.for_tool_action(action,
                                                                 result))
                self._report(run_id, "succeeded", result=result,
                                       message="done")
                return
            self._report(run_id, "failed", error=err,
                                   result=envelope.for_failure(action, err))
        except SteveError:
            pass

    def _log_exception(self, run_id):
        """Full traceback server-side only: <home>/runs/<id>/connector_error.log."""
        import traceback
        try:
            d = os.path.join(self.home, "runs", str(run_id))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "connector_error.log"), "a") as fh:
                fh.write(traceback.format_exc())
        except OSError:
            pass

    def _safe_reject(self, run_id, code):
        try:
            self._report(run_id, "rejected",
                                  error=errors.make_error(code, code))
        except SteveError:
            pass

    def _reject_queued(self):
        """PANELCANCEL3 (supervisor review of 6e9c2ca): handle_message
        _remember_run's a run BEFORE queueing and the loop saves the cursor
        past its message, but the worker exits on shutdown WITHOUT running
        what is still queued - those runs were never run, never reported
        and never redelivered. At shutdown every job/tool item still in
        self._queue gets exactly ONE terminal "rejected" report (code
        "connector_stopping", _safe_reject-style). Nothing queued is
        executed."""
        while True:
            try:
                _kind, run_id, _env, _action = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._report(
                    run_id, "rejected",
                    error=errors.make_error(
                        "connector_stopping",
                        "connector shut down before this run started"))
            except SteveError:
                pass

    def _run_job(self, run_id, env, action):
        self.current_run = run_id
        work = os.path.join(self.home, "runs", str(run_id))
        # SHOW3D: what the last_runs event needs once this run ends
        doc_id = (env.get("inputs") or {}).get("document_id")
        rejected = False

        def end_run():
            """SHOW3D: this run ended - post last_runs first, then the
            engine_state idle (engine_state stays the latest event)."""
            if action in catalog_mod.ACTIONS and not rejected:
                self.record_run_end(run_id, action, doc_id)
            self.emit_state("idle")

        self.emit_state("busy", action, 0.0)
        try:
            self._report(run_id, "received")
        except SteveError:
            pass
        engine = EngineRun(self.cfg, work)
        self.running = engine
        last = [-1.0, None]

        def on_progress(p, m):
            if p - last[0] >= 0.02 or m != last[1]:
                last[0], last[1] = p, m
                try:
                    self._report(run_id, "running", progress=round(p, 3),
                                         message=m)
                except SteveError:
                    pass
                self.emit_state("busy", action, round(p, 2))

        try:
            # download + verify inputs (files and posted programs)
            step_path = None
            program_path = None
            for name, spec in catalog_mod.get_action(action)["inputs"] \
                    ["properties"].items():
                kind = spec.get("x-steve")
                if kind not in ("file", "program"):
                    continue
                inp = env.get("inputs", {}).get(name)
                if inp is None:
                    if kind == "program":
                        # a reused run dir must never judge a program this
                        # run did not send (runner picks up program_N.nc)
                        try:
                            os.remove(os.path.join(work, name + ".nc"))
                        except FileNotFoundError:
                            pass
                    continue
                data = self.client.download(inp["url"], inp.get("headers"))
                digest = hashlib.sha256(data).hexdigest()
                if digest != inp.get("sha256") or len(data) != inp.get("bytes"):
                    self._report(
                        run_id, "rejected",
                        error=errors.make_error(
                            "input_digest_mismatch",
                            "download failed sha256/bytes check", field=name))
                    rejected = True
                    end_run()
                    return
                os.makedirs(work, exist_ok=True)
                # each program field keeps its own file (program.nc,
                # program_2.nc, program_3.nc) - never overwrite another input
                dest = (os.path.join(work, name + ".nc") if kind == "program"
                        else os.path.join(work, "input.step"))
                if kind == "program":
                    if name == "program":
                        program_path = dest
                    # program_2/program_3 sit next to it in the run dir; the
                    # runner picks them up from there in order
                else:
                    step_path = dest
                with open(dest, "wb") as fh:
                    fh.write(data)
            ok, code, values = prepare_values(env.get("inputs", {}), action)
            if not ok:
                self._report(run_id, "rejected", error=values)
                rejected = True
                end_run()
                return
            doc_id = values.get("document_id") or doc_id

            if action == catalog_mod.ACTION:
                result, files = engine.run(step_path, values, on_progress)
            elif action == catalog_mod.MEASURE_ACTION:
                result, files = engine.run_measure(step_path, values,
                                                   on_progress)
            elif action == catalog_mod.CHECK_ACTION:
                # task CP: judge a posted program; no .nc is uploaded or
                # copied (the program came FROM STEVE and goes nowhere else)
                result, files = engine.run_check_program(
                    program_path, step_path, values, on_progress)
            else:
                result, files = engine.run_slope_split_finish(
                    step_path, values, on_progress)
            # task f: the envelope joins the result and check.json
            check = None
            if "check.json" in files:
                with open(files["check.json"][0]) as fh:
                    check = json.load(fh)
            env_ = envelope.for_result(action, check)
            result = dict(result, **env_)
            if check is not None:
                check.update(env_)
                check["setup"] = {"origin": values.get("origin")}
                with open(files["check.json"][0], "w") as fh:
                    json.dump(check, fh, indent=2)
            for fname, (path, media) in files.items():
                with open(path, "rb") as fh:
                    self.client.put_file(run_id, fname, fh.read(), media)
            for fname, (path, _media) in files.items():
                if fname.endswith(".nc"):
                    self._copy_program(path, values["program_number"],
                                       fname[:-3])
            self._report(run_id, "succeeded", result=result,
                                 message="done")
            end_run()
        except Cancelled:
            try:
                self._report(run_id, "cancelled",
                                     message="cancelled")
            except SteveError:
                pass
            end_run()
        except Exception as e:  # noqa: BLE001 - every path reports
            if isinstance(e, EngineError):
                err = e.as_error()
            else:  # never a raw traceback to the caller: logged here
                self._log_exception(run_id)
                err = errors.make_error(
                    "internal_error", "%s: %s" % (type(e).__name__,
                                                  str(e)[:200]))
            try:
                self._report(
                    run_id, "failed", error=err,
                    result=envelope.for_failure(action, err))
            except SteveError:
                pass
            end_run()
        finally:
            self.running = None
            self.current_run = None

    def _copy_program(self, path_nc, program_number, stem="rough"):
        try:
            os.makedirs(self.cfg["programs_dir"], exist_ok=True)
            dest = os.path.join(self.cfg["programs_dir"],
                               "O%d_%s.nc" % (int(program_number), stem))
            with open(path_nc, "rb") as src, open(dest, "wb") as dst:
                dst.write(src.read())
        except OSError:
            pass

    # ---------------------------------------------------------------- loop --
    def _handle_signal(self, *_):
        """PANELCANCEL3: the SIGTERM/SIGINT handler. A Python signal handler
        runs on the MAIN thread between bytecodes - possibly exactly while
        that thread is inside EngineRun._spawn's `with self._lock:` (the
        same non-reentrant lock cancel() takes: calling it here deadlocks),
        and the other thread's teardown can keep cancel() busy for seconds.
        So the handler ONLY sets the Event: no cancel, no join, no I/O, no
        status write. run_forever's tail performs the shutdown outside
        signal context."""
        self._stop.set()

    def stop(self, *_):
        """Programmatic shutdown request (same as a signal): ONLY sets the
        Event; the loop's tail cancels the active job and stops the worker.
        Safe to call from any thread; never does work itself."""
        self._stop.set()

    # PANELCANCEL4 (supervisor review of 7f89867): 1.0 s made an idle
    # connector GET /messages once a second (30x the old rate); 10.0 s
    # keeps shutdown bounded well inside launchd's default 20 s
    # ExitTimeOut (our plist sets none).
    POLL_INTERRUPT = 10.0  # s: longest single GET /messages wait while idle

    def _poll_messages(self):
        """PANELCANCEL3: one poll_wait-long fetch taken in slices of at most
        POLL_INTERRUPT seconds, so a shutdown request is seen within
        ~POLL_INTERRUPT s of idle wait instead of a full poll_wait (default
        30 s). Chosen over a watcher thread: the loop thread is the one
        that must run the shutdown tail anyway (no second thread racing the
        message handling / cursor save), and a watcher could not interrupt
        an in-flight HTTP read either - slicing bounds it instead. Returns
        the first response that carries messages, else the last (empty) one
        once poll_wait elapsed or shutdown was requested. SteveError and
        OSError propagate to the loop's unchanged handlers."""
        wait_total = int(self.cfg["poll_wait"])
        deadline = time.time() + wait_total
        while True:
            if self._stop.is_set():
                wait = 0                      # asked to stop: a 0 s poll is
            else:                             # a plain immediate fetch
                remaining = deadline - time.time()
                if remaining <= 0:
                    wait = 0
                else:
                    wait = min(wait_total, int(self.POLL_INTERRUPT))
                    if remaining < wait:
                        wait = max(1, int(remaining))  # final short slice
            out = self.client.messages(self.state.get("cursor", 0), wait)
            if out.get("messages") or self._stop.is_set():
                return out
            if wait == 0 or time.time() >= deadline:
                return out

    def run_forever(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        self._write_status("starting")
        # PANELCANCEL: the long-lived FIFO worker (jobs + tool actions) so
        # the loop below keeps polling and can read a cancel mid-job.
        self._worker = threading.Thread(target=self._worker_loop,
                                        daemon=True)
        self._worker.start()
        self.enroll()
        self.get_token_blocking()
        self.publish_catalog_and_panel()
        self.emit_state("idle")
        while not self._stop.is_set():
            if time.time() - self._last_keys_refresh >= 60:
                self.refresh_steve_keys()
                self._last_keys_refresh = time.time()
            try:
                out = self._poll_messages()
            except SteveError as e:
                if e.code == "token_invalid":
                    self.get_token_blocking()
                    continue
                time.sleep(1)
                continue
            except OSError:
                time.sleep(1)
                continue
            # PANELCANCEL3: the WHOLE fetched batch is handled (no mid-
            # batch break on shutdown): every message is remembered and
            # queued here, so the tail below can give every item that
            # never ran a terminal report instead of the saved cursor
            # silently swallowing it.
            for msg in out.get("messages", []):
                try:
                    self.handle_message(msg)
                except Exception:
                    pass  # one bad message must not kill the loop
            cursor = out.get("cursor", self.state.get("cursor", 0))
            if cursor != self.state.get("cursor"):
                self.state["cursor"] = cursor
                self._save()
        # PANELCANCEL3: the signal handler only set the Event; everything
        # from here on runs OUTSIDE signal context: cancel the active job,
        # let the worker finish it (it drains NOTHING new: the get() poll
        # sees the Event and exits, an item taken in flight goes back
        # unrun), join it bounded, reject every still-queued item, then
        # "off" - main() releases the pidfile and exits 0.
        if self.running:
            self.running.cancel()
        if self._worker is not None:
            self._worker.join(timeout=60)
        self._reject_queued()
        self._write_status("off")


def main(argv=None):
    home = None
    args = argv if argv is not None else sys.argv[1:]
    if "--home" in args:
        home = args[args.index("--home") + 1]
    ok, other = acquire_pidfile(home)
    if not ok:
        print("connector already running (pid %s); not starting a "
              "second one" % other, flush=True)
        return 0
    try:
        c = Connector(home)
        print("connector fingerprint %s" % c.fingerprint, flush=True)
        c.run_forever()
    finally:
        release_pidfile(home)
    return 0


if __name__ == "__main__":
    sys.exit(main())
