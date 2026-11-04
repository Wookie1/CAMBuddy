"""Local mock STEVE server (stdlib http.server, threaded).

VERIFIES every request per docs/steve_connector_protocol.md: Content-Digest,
RFC 9421 signature base, nonce uniqueness, clock skew <= 300 s, keyid,
Bearer token, run-state order. Signs message envelopes with its own Ed25519
key. NEVER talks to stevecad.studio; used only by connector tests.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import crypto

STATES = ("received", "running", "succeeded", "failed", "rejected",
          "cancelled")
TERMINAL = ("succeeded", "failed", "rejected", "cancelled")
NEXT_OK = {
    None: ("received", "rejected"),
    "received": ("running", "rejected", "failed", "cancelled"),
    # "running may be sent as often as you like" (progress updates)
    "running": ("running", "succeeded", "failed", "cancelled"),
}
SIG_INPUT_RE = re.compile(
    r'^steve=\("@method" "@path" "@query" "content-digest"\);'
    r'created=(\d+);nonce="([^"]+)";keyid="([^"]+)";alg="ed25519"'
    r';tag="steve-connect-v1"$')


class MockSteve:
    def __init__(self, code="PAIR-1234", serve_dir=None, strict_files=True):
        self.key = crypto.new_key()
        # STEVE's kid is its own key id (any string), NOT our fingerprint
        self.kid = "steve-2026-a"
        self.code = code
        self.serve_dir = serve_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "testdata")
        self.strict_files = strict_files

        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.enrolled = None          # {fingerprint, public_key(b64), name}
        self.confirmed = False
        self.token = None
        self.messages = []           # [{id, kind, envelope, kid, sig}]
        self.next_id = 1
        self.reports = []            # [{run_id, body}]
        self.files = {}              # run_id -> {name: {bytes, sha256, media}}
        self.events = []             # {name, data}
        self.panels = {}            # name -> body
        self.catalog = None
        self.rejected_requests = []  # (path, code)
        self._seen_nonces = set()
        self.keys_override = None    # GET /keys response (rotation tests)
        self.enroll_keys_override = None  # enroll steve_keys (tests)

    # ----------------------------------------------------------- helpers --
    def keys_list(self):
        if self.keys_override is not None:
            return self.keys_override
        return crypto.sign_keys_list(self.key, [{
            "kid": self.kid,
            "public_key": crypto.b64(crypto.public_raw(self.key))}],
            kid=self.kid)

    def enqueue_run(self, run_id, action="adaptive_rough", inputs=None,
                   note="", ttl=900, expires_at=None, requested_by=None,
           bad_sig=False, envelope_over=None):
        env = {
            "id": run_id,
            "action": action,
            "inputs": inputs if inputs is not None else {},
            "note": note,
            "requested_by": requested_by or {"kind": "person"},
            "confirmed_by": None,
            "connector": self.enrolled["fingerprint"] if self.enrolled else "",
            "issued_at": int(time.time()),
            "expires_at": expires_at or int(time.time() + ttl),
            "nonce": crypto.b64(os.urandom(12)).rstrip("="),
        }
        if envelope_over:
            env.update(envelope_over)
        sig = crypto.b64(self.key.sign(crypto.canonical_json(env)))
        if bad_sig:
            sig = crypto.b64(os.urandom(64))
        msg = {"id": None, "kind": "run", "envelope": env, "kid": self.kid,
               "sig": sig}
        with self.cond:
            msg["id"] = self.next_id
            self.next_id += 1
            self.messages.append(msg)
            self.cond.notify_all()
        return msg

    def enqueue_cancel(self, run_id):
        env = {"id": None, "run": run_id,
               "connector": self.enrolled["fingerprint"] if self.enrolled else "",
               "issued_at": int(time.time()),
               "expires_at": int(time.time() + 900),
               "nonce": crypto.b64(os.urandom(12)).rstrip("=")}
        sig = crypto.b64(self.key.sign(crypto.canonical_json(env)))
        msg = {"id": None, "kind": "cancel", "envelope": env, "kid": self.kid,
               "sig": sig}
        with self.cond:
            msg["id"] = self.next_id
            self.next_id += 1
            self.messages.append(msg)
            self.cond.notify_all()
        return msg

    def toolpath_inputs(self, step_path, request, settings=None,
                        sha_over=None):
        """TP1: the inputs STEVE sends a toolpath action (docs, Toolpath
        actions): part (STEP file input served from serve_dir), request,
        steve_request_sha256 and the settings, also in request.settings.
        GUESS: the docs do not say how the fingerprint is computed; here it
        is sha256 of the canonical request JSON."""
        with open(step_path, "rb") as fh:
            data = fh.read()
        name = os.path.basename(step_path)
        request = dict(request, settings=dict(settings or {}))
        return dict(settings or {}, part={
            "kind": "file", "format": "step", "name": name,
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "url": self.base_url + "/files/" + name,
            "headers": {"X-Steve-Ticket": "tp-%s" % os.urandom(4).hex()},
            "document": {"id": "doc-tp"}, "revision": 1},
            request=request,
            steve_request_sha256=sha_over or hashlib.sha256(
                crypto.canonical_json(request)).hexdigest())

    def confirm(self):
        with self.lock:
            self.confirmed = True

    def states_for(self, run_id):
        want = str(run_id)
        with self.lock:
            return [r["body"]["state"] for r in self.reports
                    if str(r["run_id"]) == want]

    def wait_state(self, run_id, state, timeout=60.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if state in self.states_for(run_id):
                return True
            time.sleep(0.1)
        return False

    def wait_enroll(self, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.enrolled:
                return True
            time.sleep(0.05)
        return False

    def wait_terminal(self, run_id, timeout=180.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.states_for(run_id)
            if st and st[-1] in TERMINAL:
                return st[-1]
            time.sleep(0.1)
        return None

    def file_names(self, run_id):
        with self.lock:
            return sorted(self.files.get(str(run_id), {}))

    def file_info(self, run_id, name):
        with self.lock:
            return self.files.get(str(run_id), {}).get(name)

    # ------------------------------------------------------------ HTTP --
    def serve_forever(self, port=0):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # silence
                pass

            def _send(self, code, obj=None, raw=None, media="application/json"):
                body = raw if raw is not None else (
                    json.dumps(obj).encode("utf-8") if obj is not None else b"")
                self.send_response(code)
                self.send_header("Content-Type", media)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _detail(self, code, msg, http=400):
                with mock.lock:
                    mock.rejected_requests.append(
                        (urllib.parse.urlparse(self.path).path, code))
                self._send(http, {"detail": {"code": code, "message": msg}})

            def _handle(self, method):
                u = urllib.parse.urlparse(self.path)
                path, query = u.path, u.query
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                try:
                    return mock.route(self, method, path, query, body)
                except Exception as exc:  # keep the server alive
                    try:
                        self._send(500, {"detail": {"code": "mock_error",
                                                   "message": str(exc)}})
                    except Exception:
                        pass

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_DELETE(self):
                self._handle("DELETE")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.base_path = "/connect/v1"
        self.base_url = "http://127.0.0.1:%d%s" % (self.port, self.base_path)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                      daemon=True)
        self.thread.start()
        return self.base_url

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------ routes --
    def route(self, h, method, path, query, body):
        pre = self.base_path
        if not path.startswith(pre):
            return h._detail("not_found", "unknown path", 404)
        ep = path[len(pre):]

        if method == "GET" and ep == "/keys":  # not signed
            return h._send(200, self.keys_list())
        if method == "GET" and ep.startswith("/files/"):
            # one-time ticket download: plain GET with headers, not signed
            name = os.path.basename(ep)
            fp = os.path.join(self.serve_dir, name)
            if not os.path.isfile(fp):
                return h._detail("not_found", "no such file", 404)
            ticket = h.headers.get("X-Steve-Ticket")
            if self.strict_files and not ticket:
                return h._detail("ticket_invalid", "missing ticket header", 403)
            with open(fp, "rb") as fh:
                data = fh.read()
            return h._send(200, raw=data, media="application/octet-stream")

        err = self._verify_signed(h, method, ep, query, body)
        if err:
            return err

        if method == "POST" and ep == "/enroll":
            return self._enroll(h, body)
        if method == "POST" and ep == "/token":
            return self._token(h)
        if method == "PUT" and ep == "/catalog":
            self.catalog = json.loads(body or b"{}")
            return h._send(200, {
                "actions": [a["name"] for a in self.catalog.get("actions", [])],
                "events": [e["name"] for e in self.catalog.get("events", [])]})
        if method == "GET" and ep == "/messages":
            return self._messages(h, query)
        m = re.match(r"^/runs/([A-Za-z0-9_-]+)$", ep)
        if m and method == "POST":
            return self._report(h, m.group(1), body)
        m = re.match(r"^/runs/([A-Za-z0-9_-]+)/files/([A-Za-z0-9._-]+)$", ep)
        if m and method == "PUT":
            return self._upload(h, m.group(1), m.group(2), body)
        if method == "POST" and ep == "/events":
            return self._event(h, body)
        if method == "PUT" and re.match(r"^/panels/[a-z0-9_-]+$", ep):
            return self._panel(h, ep[len("/panels/"):], body)
        if method == "DELETE" and ep.startswith("/panels/"):
            self.panels.pop(ep[len("/panels/"):], None)
            return h._send(200, {"removed": True})
        return h._detail("not_found", "unknown endpoint", 404)

    # ----------------------------------------------------- verification --
    def _verify_signed(self, h, method, ep, query, body):
        digest = h.headers.get("Content-Digest")
        sin = h.headers.get("Signature-Input")
        sig = h.headers.get("Signature")
        if not (digest and sin and sig):
            return h._detail("signature_missing", "missing signature headers",
                            401)
        if digest != crypto.content_digest(body):
            return h._detail("digest_mismatch", "body does not match digest",
                            400)
        m = SIG_INPUT_RE.match(sin)
        if not m:
            return h._detail("signature_invalid", "bad Signature-Input", 401)
        created, nonce, keyid = int(m.group(1)), m.group(2), m.group(3)
        if not (16 <= len(nonce) <= 64):
            return h._detail("signature_invalid", "nonce length", 401)
        if abs(time.time() - created) > 300:
            return h._detail("clock_skew", "created too far from clock", 401)
        with self.lock:
            replayed = nonce in self._seen_nonces
            self._seen_nonces.add(nonce)
        if replayed:
            return h._detail("nonce_replayed", "nonce seen before", 401)
        if self.enrolled and keyid != self.enrolled["fingerprint"]:
            return h._detail("key_unknown", "unknown keyid", 401)
        pub_b64 = (self.enrolled or {}).get("public_key")
        if pub_b64:
            pub = crypto.unb64(pub_b64)
        else:  # enroll: key arrives in the body
            try:
                pub = crypto.unb64(json.loads(body)["public_key"])
            except Exception:
                return h._detail("enroll_invalid", "bad enroll body", 400)
            if crypto.fingerprint(pub) != keyid:
                return h._detail("key_mismatch", "keyid != body key", 401)
        sig_b64 = sig.split("=:", 1)[-1].rstrip(":")
        base = crypto.signature_base(method, self.base_path + ep, query,
                                    digest, created, nonce, keyid)
        if not crypto.verify_signature(pub, base, sig_b64):
            return h._detail("signature_invalid", "signature check failed", 401)
        # token check (everything after enrollment except enroll/token)
        if self.enrolled and ep not in ("/enroll", "/token"):
            want = "Bearer %s" % self.token if self.token else None
            if h.headers.get("Authorization") != want:
                return h._detail("token_invalid", "missing/expired token", 401)
        return None

    # ------------------------------------------------------------ enroll --
    def _enroll(self, h, body):
        req = json.loads(body)
        if req.get("code") != self.code:
            return h._detail("code_invalid", "bad pairing code", 403)
        pub = crypto.unb64(req["public_key"])
        self.enrolled = {"fingerprint": crypto.fingerprint(pub),
                        "public_key": req["public_key"],
                        "name": req.get("name"),
                        "version": req.get("version")}
        return h._send(200, {"connector": req.get("name"),
                             "fingerprint": self.enrolled["fingerprint"],
                             "status": "pending",
                             "steve_keys": (self.enroll_keys_override
                                          or self.keys_list())})

    def _token(self, h):
        if not self.confirmed:
            return h._detail("pending_confirmation", "awaiting owner", 403)
        self.token = crypto.b64(os.urandom(24)).rstrip("=")
        return h._send(200, {"token": self.token, "expires_in": 900})

    # ---------------------------------------------------------- messages --
    def _messages(self, h, query):
        q = urllib.parse.parse_qs(query)
        after = int(q.get("after", ["0"])[0])
        wait = min(int(q.get("wait", ["0"])[0]), 30)
        deadline = time.time() + wait
        batch, cursor = [], after
        while True:
            with self.cond:
                batch = [m for m in self.messages if m["id"] > after]
                cursor = max([m["id"] for m in batch] or [after])
                if batch or time.time() >= deadline:
                    break
                self.cond.wait(min(0.1, max(0.01, deadline - time.time())))
        return h._send(200, {"messages": batch, "cursor": cursor})

    # ------------------------------------------------------------- runs --
    def _report(self, h, run_id, body):
        rep = json.loads(body)
        state = rep.get("state")
        if state not in STATES:
            return h._detail("state_invalid", "unknown state", 400)
        with self.lock:
            prior = [r["body"]["state"] for r in self.reports
                     if r["run_id"] == run_id]
            cur = prior[-1] if prior else None
            ok = state in NEXT_OK.get(cur, ())
            if ok:
                self.reports.append({"run_id": run_id, "body": rep})
        if os.environ.get("MOCK_DEBUG"):
            print("DBG report run_id=%r state=%r cur=%r ok=%s"
                  % (run_id, state, cur, ok), flush=True)
        if not ok:
            return h._detail("state_out_of_order", "%s -> %s" % (cur, state),
                            409)
        return h._send(200, {"accepted": True})

    def _upload(self, h, run_id, name, body):
        with self.lock:
            prior = [r["body"]["state"] for r in self.reports
                     if r["run_id"] == run_id]
        if self.strict_files and (not prior
                                 or prior[-1] not in ("received", "running")):
            return h._detail("state_out_of_order",
                            "files only while received/running", 409)
        if len(name) > 100 or not re.match(r"^[A-Za-z0-9._-]+$", name):
            return h._detail("name_invalid", "bad file name", 400)
        with self.lock:
            self.files.setdefault(run_id, {})[name] = {
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "media": h.headers.get("Content-Type"),
            }
            if name == "toolpath.json":   # TP1: kept for the tests to judge
                self.files[run_id][name]["body"] = body
        return h._send(200, {"accepted": True, "name": name,
                             "bytes": len(body),
                             "sha256": hashlib.sha256(body).hexdigest()})

    def _event(self, h, body):
        ev = json.loads(body)
        declared = [e["name"] for e in (self.catalog or {}).get("events", [])]
        if ev.get("name") not in declared:
            return h._detail("event_undeclared", "not in catalog", 400)
        with self.lock:
            self.events.append(ev)
        return h._send(200, {"accepted": True})

    def _panel(self, h, name, body):
        p = json.loads(body)
        blob = json.dumps(p).encode("utf-8")
        self.panels[name] = p
        return h._send(200, {"id": name, "name": name,
                             "version": hashlib.sha256(blob).hexdigest()[:8],
                             "bytes": len(blob),
                             "sha256": hashlib.sha256(blob).hexdigest()})
