"""STEVE connector v1 (roughing). Separate light process: stdlib + crypto.py.

Flow: enroll -> pending -> token (retry while pending_confirmation) ->
PUT /catalog -> PUT /panels -> long-poll GET /messages -> verify envelopes
(steve_keys pinned at enroll; newer /keys lists only if signed by a trusted
key) -> download+check inputs -> run engine -> upload files -> report states.
Persistent ledger: never act on a run id twice. Never contacts
stevecad.studio unless the configured base_url says so; tests point it at
the local mock.
"""
import hashlib
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog as catalog_mod  # noqa: E402
import config as config_mod    # noqa: E402
import crypto                  # noqa: E402
from client import SteveClient, SteveError  # noqa: E402
from runner import EngineRun, EngineError, Cancelled  # noqa: E402

VERSION = "1.0.0"
PANEL_NAME = catalog_mod.ACTION


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
        self._stop = False

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
                                catalog_mod.CATALOG)
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
        while not self._stop:
            try:
                return self.client.get_token()  # token stays in memory only
            except SteveError as e:
                if e.code != "pending_confirmation":
                    raise
                time.sleep(float(self.cfg["token_retry"]))

    def publish_catalog_and_panel(self):
        self.client.put_catalog(catalog_mod.CATALOG)
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
        if data == self._last_event:
            return
        self._last_event = data
        try:
            self.client.post_event(catalog_mod.EVENT, data)
        except SteveError:
            pass

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
            target = env.get("run")
            if self.running and self.current_run == target:
                self.running.cancel()
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
        if action not in catalog_mod.ACTIONS:
            self._remember_run(run_id)
            self._safe_reject(run_id, "action_unknown")
            return
        self._remember_run(run_id)
        self._run_job(run_id, env, action)

    def _safe_reject(self, run_id, code):
        try:
            self.client.report_run(run_id, "rejected",
                                  error={"code": code, "message": code})
        except SteveError:
            pass

    def _run_job(self, run_id, env, action):
        self.current_run = run_id
        work = os.path.join(self.home, "runs", str(run_id))
        self.emit_state("busy", action, 0.0)
        try:
            self.client.report_run(run_id, "received")
        except SteveError:
            pass
        engine = EngineRun(self.cfg, work)
        self.running = engine
        last = [-1.0, None]

        def on_progress(p, m):
            if p - last[0] >= 0.02 or m != last[1]:
                last[0], last[1] = p, m
                try:
                    self.client.report_run(run_id, "running", progress=round(p, 3),
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
                    self.client.report_run(
                        run_id, "rejected",
                        error={"code": "input_digest_mismatch",
                             "message": "download failed sha256/bytes check"})
                    self.emit_state("idle")
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
            values_in = env.get("inputs", {})
            # task UN: convert inch inputs to mm FIRST, then validate the
            # mm values against the catalog's mm ranges (unchanged) -- the
            # ranges are mm-valued, so validating raw inch numbers would
            # reject or misjudge sensible inch inputs
            values_in = catalog_mod.to_mm(values_in)
            ok, code, values = catalog_mod.validate_inputs(values_in, action)
            if not ok:
                self.client.report_run(run_id, "rejected",
                                     error={"code": code, "message": values})
                self.emit_state("idle")
                return

            if action == catalog_mod.ACTION:
                result, files = engine.run(step_path, values, on_progress)
            elif action == catalog_mod.CHECK_ACTION:
                # task CP: judge a posted program; no .nc is uploaded or
                # copied (the program came FROM STEVE and goes nowhere else)
                result, files = engine.run_check_program(
                    program_path, step_path, values, on_progress)
            else:
                result, files = engine.run_slope_split_finish(
                    step_path, values, on_progress)
            for fname, (path, media) in files.items():
                with open(path, "rb") as fh:
                    self.client.put_file(run_id, fname, fh.read(), media)
            for fname, (path, _media) in files.items():
                if fname.endswith(".nc"):
                    self._copy_program(path, values["program_number"],
                                       fname[:-3])
            self.client.report_run(run_id, "succeeded", result=result,
                                 message="done")
            self.emit_state("idle")
        except Cancelled:
            try:
                self.client.report_run(run_id, "cancelled",
                                     message="cancelled")
            except SteveError:
                pass
            self.emit_state("idle")
        except (EngineError, SteveError, OSError, KeyError) as e:
            try:
                self.client.report_run(
                    run_id, "failed",
                    error={"code": "engine_failed", "message": str(e)[:400]})
            except SteveError:
                pass
            self.emit_state("idle")
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
    def stop(self, *_):
        self._stop = True
        if self.running:
            self.running.cancel()

    def run_forever(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.enroll()
        self.get_token_blocking()
        self.publish_catalog_and_panel()
        self.emit_state("idle")
        while not self._stop:
            if time.time() - self._last_keys_refresh >= 60:
                self.refresh_steve_keys()
                self._last_keys_refresh = time.time()
            try:
                out = self.client.messages(self.state.get("cursor", 0),
                                         int(self.cfg["poll_wait"]))
            except SteveError as e:
                if e.code == "token_invalid":
                    self.get_token_blocking()
                    continue
                time.sleep(1)
                continue
            except OSError:
                time.sleep(1)
                continue
            for msg in out.get("messages", []):
                if self._stop:
                    break
                try:
                    self.handle_message(msg)
                except Exception:
                    pass  # one bad message must not kill the loop
            cursor = out.get("cursor", self.state.get("cursor", 0))
            if cursor != self.state.get("cursor"):
                self.state["cursor"] = cursor
                self._save()


def main(argv=None):
    home = None
    args = argv if argv is not None else sys.argv[1:]
    if "--home" in args:
        home = args[args.index("--home") + 1]
    c = Connector(home)
    print("connector fingerprint %s" % c.fingerprint, flush=True)
    c.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
