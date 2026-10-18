"""Task J tests: connector v1 against a local mock STEVE server.

Run: /opt/homebrew/bin/python3 -m pytest connector -q
NEVER contacts stevecad.studio: everything runs against connector/mock_steve.py.
"""
import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import crypto  # noqa: E402
from mock_steve import MockSteve  # noqa: E402

PY = "/opt/homebrew/bin/python3"
VIBE_PY = "/Applications/VibeCAD.app/Contents/Resources/bin/python"


# ================================================================ (a) unit ==

class TestCryptoUnit:
    def test_signature_base_exact(self):
        """Exact signature-base string, matching the protocol doc example."""
        base = crypto.signature_base(
            "GET", "/connect/v1/messages", "after=41&wait=30",
            "sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:",
            1760500000, "q2V9w0k3Xc7bYp1uZt5aLm", "SHA256:3b1W")
        expected = "\n".join([
            '"@method": GET',
            '"@path": /connect/v1/messages',
            '"@query": ?after=41&wait=30',
            '"content-digest": sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:',
            '"@signature-params": ("@method" "@path" "@query" "content-digest")'
            ';created=1760500000;nonce="q2V9w0k3Xc7bYp1uZt5aLm"'
            ';keyid="SHA256:3b1W";alg="ed25519";tag="steve-connect-v1"',
        ])
        assert base == expected.encode("utf-8")
        assert not base.endswith(b"\n")
        assert base.count(b"\n") == 4

    def test_signature_base_empty_query_is_question_mark(self):
        base = crypto.signature_base("POST", "/connect/v1/token", "",
                                    "sha-256=:abc:", 1, "n", "SHA256:k"
                                    ).decode()
        assert '"@query": ?\n' in base + "\n"
        assert '"@query": ?' in base

    def test_empty_body_digest(self):
        assert crypto.content_digest(b"") == \
            "sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:"

    def test_fingerprint_format(self):
        sk = crypto.new_key()
        raw = crypto.public_raw(sk)
        assert len(raw) == 32
        fp = crypto.fingerprint(raw)
        assert fp.startswith("SHA256:")
        body = fp[len("SHA256:"):]
        assert len(body) == 43 and not body.endswith("=")
        # matches an independent computation
        want = base64.b64encode(hashlib.sha256(raw).digest()).decode()
        assert body == want.rstrip("=")

    def test_canonical_json(self):
        obj = {"b": 1, "a": "\u00e9", "z": {"y": [1, 2], "x": None}}
        got = crypto.canonical_json(obj)
        assert got == '{"a":"\u00e9","b":1,"z":{"x":null,"y":[1,2]}}'.encode(
            "utf-8")
        assert b" " not in got and b"\xc3\xa9" in got  # sorted, compact, UTF-8

    def test_rfc8032_ed25519_vector1(self):
        """RFC 8032 test vector 1: empty message."""
        seed = bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        want_pub = bytes.fromhex(
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        want_sig = ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873"
                    "e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0"
                    "595bbe24655141438e7a100b")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
        sk = Ed25519PrivateKey.from_private_bytes(seed)
        assert crypto.public_raw(sk) == want_pub
        sig = sk.sign(b"")
        assert sig.hex() == want_sig
        sig_b64 = base64.b64encode(sig).decode()
        assert crypto.verify_signature(want_pub, b"", sig_b64)
        assert not crypto.verify_signature(want_pub, b"x", sig_b64)

    def test_sign_verify_roundtrip_and_keyfile(self, tmp_path):
        keyfile = tmp_path / "stevecam" / "identity.key"
        sk = crypto.load_or_create_key(str(keyfile))
        mode = stat.S_IMODE(os.stat(keyfile).st_mode)
        assert mode == 0o600
        sk2 = crypto.load_or_create_key(str(keyfile))
        assert crypto.public_raw(sk) == crypto.public_raw(sk2)
        headers = crypto.sign_request(sk, "POST", "/connect/v1/catalog", "",
                                     b'{"a":1}')
        assert headers["Content-Digest"] == crypto.content_digest(b'{"a":1}')
        assert headers["Signature-Input"].startswith("steve=(\"@method\"")
        # nonce 16-64 chars, fresh per call
        h2 = crypto.sign_request(sk, "POST", "/connect/v1/catalog", "",
                                 b'{"a":1}')
        n1 = headers["Signature-Input"].split('nonce="')[1].split('"')[0]
        n2 = h2["Signature-Input"].split('nonce="')[1].split('"')[0]
        assert 16 <= len(n1) <= 64 and n1 != n2

    def test_envelope_and_keys_list_verify(self):
        sk = crypto.new_key()
        pub = crypto.public_raw(sk)
        kid = crypto.fingerprint(pub)
        env = {"id": 7, "action": "adaptive_rough", "nonce": "n"}
        sig = crypto.b64(sk.sign(crypto.canonical_json(env)))
        assert crypto.verify_envelope(pub, env, sig)
        tampered = dict(env, action="cycle_start")
        assert not crypto.verify_envelope(pub, tampered, sig)
        listing = crypto.sign_keys_list(sk, [{"kid": kid,
                                             "public_key": crypto.b64(pub)}])
        assert crypto.verify_signed_list(pub, listing)
        other = crypto.new_key()
        assert not crypto.verify_signed_list(crypto.public_raw(other), listing)


# =========================================================== fixtures =====

STEP = os.path.join(HERE, "testdata", "synth_pocket.step")

GOOD_INPUTS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
    "tool_diameter": 6.0, "corner_radius": 0.0, "flute_length": 30.0,
    "stepdown": 4.0, "optimal_load": 2.0, "stock_to_leave": 0.381,
    "rest_stepup": 1.905, "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 1, "units": "mm", "program_number": 1001,
}

E2E = {}  # captures the end-to-end run for the final printout


def model_input(mock, sha_over=None):
    with open(STEP, "rb") as fh:
        data = fh.read()
    return {
        "kind": "file", "format": "step", "name": os.path.basename(STEP),
        "sha256": sha_over or hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "url": mock.base_url + "/files/" + os.path.basename(STEP),
        "headers": {"X-Steve-Ticket": "ticket-%d" % (next(_tick),)},
        "document": {"id": "doc-1"}, "revision": 3,
    }


_tick = iter(range(1, 10 ** 6))


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """Mock STEVE + the connector subprocess on a temporary HOME."""
    home = tmp_path_factory.mktemp("stevecam-home")
    programs = home / "programs"
    mock = MockSteve(code="PAIR-1234")
    base = mock.serve_forever()
    with open(home / "config.toml", "w") as fh:
        fh.write('base_url = "%s"\npairing_code = "PAIR-1234"\n'
                 'poll_wait = 1\ntoken_retry = 1\n'
                 'programs_dir = "%s"\nrepo_root = "%s"\n'
                 % (base, programs, REPO))
    proc = subprocess.Popen([PY, os.path.join(HERE, "connector.py"),
                            "--home", str(home)], cwd=REPO,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    try:
        assert mock.wait_enroll(20), "connector never enrolled"
        assert mock.enrolled["fingerprint"].startswith("SHA256:")
        mock.confirm()
        deadline = time.time() + 30
        while time.time() < deadline and mock.catalog is None:
            if proc.poll() is not None:
                raise AssertionError("connector died at startup: %s"
                                   % proc.stdout.read())
            time.sleep(0.1)
        assert mock.catalog is not None, "catalog never published"
        yield mock, home, programs
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock.stop()


# ==================================================== (b) end-to-end ======

class TestEndToEnd:
    def test_enroll_confirm_run(self, live):
        mock, home, programs = live
        # panel published at startup
        assert "adaptive_rough" in mock.panels
        panel = mock.panels["adaptive_rough"]
        assert set(["index.html", "panel.js", "panel.css"]) \
            <= set(panel["files"])
        assert panel["placement"] == ["right"]

        mock.enqueue_run(501, inputs=dict(GOOD_INPUTS,
                                         model=model_input(mock)))
        assert mock.wait_state(501, "received", 30), \
            "run never received"
        final = mock.wait_terminal(501, timeout=300)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(501))

        states = mock.states_for(501)
        assert states[0] == "received"
        assert states[-1] == "succeeded"
        assert "running" in states
        reps = {r["body"]["state"]: r["body"] for r in mock.reports
                if str(r["run_id"]) == "501"}
        progresses = [r["body"].get("progress") for r in mock.reports
                     if str(r["run_id"]) == "501" and "progress" in r["body"]]
        assert progresses and all(0.0 <= p <= 1.0 for p in progresses)
        assert progresses == sorted(progresses)

        result = reps["succeeded"].get("result") or {}
        for key in ("estimated_time_min", "cut_length_mm", "zmap_gouges",
                    "rapid_collisions", "over_flute", "leftover"):
            assert key in result, "missing %s in result" % key
        assert result["zmap_gouges"]["count"] == 0
        assert result["rapid_collisions"]["count"] == 0
        assert result["cut_length_mm"] > 100
        E2E["result"] = result

        # files uploaded before the final state, correct digests recorded
        assert mock.file_names(501) == ["check.json", "preview.png",
                                       "rough.nc"]
        files = {n: mock.file_info(501, n) for n in mock.file_names(501)}
        assert files["preview.png"]["bytes"] > 1000
        assert files["preview.png"]["media"] == "image/png"
        order = [r["body"]["state"] for r in mock.reports
                 if str(r["run_id"]) == "501"]
        assert order.index("succeeded") == len(order) - 1

        # engine_state events on change: idle at start, busy, idle again
        names = [(e["name"], e["data"]["state"]) for e in mock.events]
        assert ("engine_state", "idle") in names
        assert ("engine_state", "busy") in names
        assert names[-1] == ("engine_state", "idle")

        # program copied to the configured programs folder
        assert (programs / "O1001_rough.nc").exists()

        # cursor persisted in the state dir
        with open(home / "state.json") as fh:
            st = json.load(fh)
        assert st["cursor"] >= 1 and st["enrolled"]
        with open(home / "ledger.json") as fh:
            led = json.load(fh)
        assert 501 in led["runs"]


# ======================================================= (c) negatives ====

class TestNegatives:
    def _wait_rejected(self, mock, run_id, code):
        assert mock.wait_state(run_id, "rejected", 30), \
            "run %s not rejected: %s" % (run_id, mock.states_for(run_id))
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == str(run_id)][-1]
        assert rep["state"] == "rejected"
        assert rep.get("error", {}).get("code") == code, rep
        assert "running" not in mock.states_for(run_id)

    def test_bad_envelope_sig_rejected(self, live):
        mock, _, _ = live
        mock.enqueue_run(601, inputs=dict(GOOD_INPUTS,
                                         model=model_input(mock)),
                         bad_sig=True)
        self._wait_rejected(mock, 601, "envelope_sig_invalid")

    def test_replayed_run_id_not_acted_twice(self, live):
        mock, _, _ = live
        inputs = dict(GOOD_INPUTS, model=model_input(mock), stepdown=500.0)
        mock.enqueue_run(602, inputs=inputs)
        self._wait_rejected(mock, 602, "input_out_of_range")
        n_before = len(mock.states_for(602))
        # redelivery of the same run id (fresh message + nonce) must not be
        # acted on again: no new reports
        mock.enqueue_run(602, inputs=inputs)
        time.sleep(2.5)  # past a poll cycle
        assert len(mock.states_for(602)) == n_before

    def test_sha_mismatch_rejected_before_running(self, live):
        mock, _, _ = live
        bad = hashlib.sha256(b"not the model").hexdigest()
        mock.enqueue_run(603, inputs=dict(GOOD_INPUTS,
                                         model=model_input(mock, sha_over=bad)))
        self._wait_rejected(mock, 603, "input_digest_mismatch")

    def test_expired_envelope_rejected(self, live):
        mock, _, _ = live
        mock.enqueue_run(604, inputs=dict(GOOD_INPUTS,
                                         model=model_input(mock)),
                         expires_at=int(time.time()) - 10)
        self._wait_rejected(mock, 604, "envelope_expired")

    def test_input_out_of_range_rejected(self, live):
        mock, _, _ = live
        mock.enqueue_run(605, inputs=dict(GOOD_INPUTS, model=model_input(mock),
                                         tool_diameter=100.0))
        self._wait_rejected(mock, 605, "input_out_of_range")

    def test_mock_verifies_request_signatures(self, live):
        """Sanity: the mock really refused something unauthenticated."""
        mock, _, _ = live
        import urllib.error
        import urllib.request
        try:
            urllib.request.urlopen(mock.base_url + "/messages?after=0&wait=0",
                                  timeout=5)
            assert False, "unsigned request was accepted"
        except urllib.error.HTTPError as e:
            assert e.code == 401


# ======================================================== final printout ==

def test_zz_print_e2e_result(live):
    mock, _, _ = live
    print("\n==== end-to-end run result JSON ====")
    print(json.dumps(E2E.get("result", {}), indent=2))
    print("==== states:", mock.states_for(501), "====")

