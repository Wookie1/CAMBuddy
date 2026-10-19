"""Task J tests: connector v1 against a local mock STEVE server.

Run: /opt/homebrew/bin/python3 -m pytest connector -q
NEVER contacts stevecad.studio: everything runs against connector/mock_steve.py.
"""
import base64
import datetime
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
import catalog as catalog_mod  # noqa: E402
import connector as connector_mod  # noqa: E402
from client import SteveError  # noqa: E402
from mock_steve import MockSteve  # noqa: E402
from runner import EngineError  # noqa: E402

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

    def test_verify_signed_list_uses_trusted_kids(self):
        """STEVE kids are its own key ids (any string), not fingerprints."""
        sk = crypto.new_key()
        pub = crypto.b64(crypto.public_raw(sk))
        keys = [{"kid": "steve-2026-a", "public_key": pub}]
        listing = crypto.sign_keys_list(sk, keys, kid="steve-2026-a")
        # signed by a kid present in the trusted map -> accepted
        assert crypto.verify_signed_list({"steve-2026-a": pub}, listing)
        # same key but kid not in trusted -> rejected
        assert not crypto.verify_signed_list(
            {crypto.fingerprint(crypto.public_raw(sk)): pub}, listing)
        # kid trusted but the key does not verify the sig -> rejected
        assert not crypto.verify_signed_list(
            {"steve-2026-a": crypto.b64(crypto.public_raw(crypto.new_key()))},
            listing)
        # tampered list -> rejected
        listing["list"]["keys"].append(
            {"kid": "evil", "public_key": crypto.b64(
                crypto.public_raw(crypto.new_key()))})
        assert not crypto.verify_signed_list({"steve-2026-a": pub}, listing)
        # malformed inputs -> rejected, no crash
        assert not crypto.verify_signed_list({}, listing)
        assert not crypto.verify_signed_list({"a": "b"}, {"list": {}})


class TestTimestamps:
    def test_numeric_unix_seconds(self):
        assert crypto.parse_time(1760000000) == 1760000000.0
        assert crypto.parse_time(1760000000.5) == 1760000000.5

    def test_iso_with_z(self):
        got = crypto.parse_time("2026-10-17T12:00:00Z")
        want = datetime.datetime(2026, 10, 17, 12, 0, 0,
                                tzinfo=datetime.timezone.utc).timestamp()
        assert got == want

    def test_iso_with_offset(self):
        z = crypto.parse_time("2026-10-17T12:00:00Z")
        off = crypto.parse_time("2026-10-17T14:00:00+02:00")
        assert off == z  # same instant

    def test_naive_rejected(self):
        assert crypto.parse_time("2026-10-17T12:00:00") is None
        assert crypto.parse_time("2026-10-17 12:00:00") is None

    def test_garbage_rejected(self):
        for bad in ("soon", "", "1760000000.5x", None, True, [], {}):
            assert crypto.parse_time(bad) is None

    def test_expired_iso_detected(self):
        past = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(seconds=60))
        assert crypto.parse_time(
            past.strftime("%Y-%m-%dT%H:%M:%SZ")) <= time.time()


# =========================================================== fixtures =====

STEP = os.path.join(HERE, "testdata", "synth_pocket.step")

GOOD_INPUTS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 4.0, "tool_type": "flat",
    # T13 flat 12.686: a real X7 table tool whose holder (BT30-ER32-70) is
    # known - the connector gate fails any run with an unknown holder
    "tool_diameter": 12.686, "corner_radius": 0.0, "flute_length": 50.8,
    "stepdown": 4.0, "optimal_load": 2.0, "stock_to_leave": 0.381,
    "rest_stepup": 1.905, "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 13, "units": "mm", "program_number": 1001,
}

# slope_split_finish: finishing with the T20 3/8in ball 9.525 (real table
# diameter, holder BT30-ER20-60 known), roughing with the T13 flat 12.686
# (the engine's bull 12.7 skips every level on this pocketed block and
# crashes: engine-track bug, see TASK_M).
# floor_z 5.0 -> floor = stock zmin (-1.0) + 5.0 = 4.0 = the pocket floor.
SLOPE_GOOD_INPUTS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 5.0, "tool_diameter": 9.525,
    "stepover": 0.3, "stepdown": 0.3, "slope_threshold": 40.0,
    "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 20, "units": "mm", "program_number": 1002,
    "rough_tool_type": "flat", "rough_tool_diameter": 12.686,
    "rough_corner_radius": 0.0, "rough_flute_length": 50.8,
    "rough_stepdown": 4.0, "rough_optimal_load": 2.0,
    "rough_stock_to_leave": 0.381, "rough_rest_stepup": 1.905,
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
        # (the trailing idle is posted AFTER the succeeded report: wait for it)
        deadline = time.time() + 30
        while True:
            names = [(e["name"], e["data"]["state"]) for e in mock.events]
            if names[-1] == ("engine_state", "idle") or time.time() > deadline:
                break
            time.sleep(0.1)
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


# ================================================ (d) timestamps end-to-end ==

def _wait_rejected(mock, run_id, code):
    assert mock.wait_state(run_id, "rejected", 30), \
        "run %s not rejected: %s" % (run_id, mock.states_for(run_id))
    rep = [r["body"] for r in mock.reports
           if str(r["run_id"]) == str(run_id)][-1]
    assert rep["state"] == "rejected"
    assert rep.get("error", {}).get("code") == code, rep
    assert "running" not in mock.states_for(run_id)


def _iso(seconds_ahead):
    dt = datetime.datetime.now(datetime.timezone.utc) + \
        datetime.timedelta(seconds=seconds_ahead)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestTimestampsE2E:
    """issued_at/expires_at: numeric or ISO with Z/offset accepted;
    naive, garbage or expired rejected."""

    def test_iso_z_and_offset_accepted(self, live):
        mock, _, _ = live
        # out-of-range input => rejection with input_out_of_range, which can
        # only happen if the ISO timestamps passed validation
        mock.enqueue_run(701, inputs=dict(GOOD_INPUTS, model=model_input(mock),
                                         tool_diameter=100.0),
                         envelope_over={"issued_at": _iso(-5),
                                      "expires_at": _iso(600)})
        _wait_rejected(mock, 701, "input_out_of_range")
        mock.enqueue_run(702, inputs=dict(GOOD_INPUTS, model=model_input(mock),
                                         tool_diameter=100.0),
                         envelope_over={
                             "issued_at": "2026-01-01T00:00:00+02:00",
                             "expires_at": "2999-01-01T00:00:00+05:45"})
        _wait_rejected(mock, 702, "input_out_of_range")

    def test_naive_iso_rejected(self, live):
        mock, _, _ = live
        mock.enqueue_run(703, inputs=dict(GOOD_INPUTS, model=model_input(mock)),
                         envelope_over={"issued_at": "2026-10-17T12:00:00",
                                      "expires_at": "2999-01-01T00:00:00"})
        _wait_rejected(mock, 703, "envelope_bad_time")
        mock.enqueue_run(704, inputs=dict(GOOD_INPUTS, model=model_input(mock)),
                         envelope_over={"issued_at": int(time.time()),
                                      "expires_at": "2999-01-01T00:00:00"})
        _wait_rejected(mock, 704, "envelope_bad_time")

    def test_garbage_time_rejected(self, live):
        mock, _, _ = live
        mock.enqueue_run(705, inputs=dict(GOOD_INPUTS, model=model_input(mock)),
                         envelope_over={"issued_at": "soon",
                                      "expires_at": "2999-01-01T00:00:00Z"})
        _wait_rejected(mock, 705, "envelope_bad_time")

    def test_expired_iso_rejected(self, live):
        mock, _, _ = live
        mock.enqueue_run(706, inputs=dict(GOOD_INPUTS, model=model_input(mock)),
                         envelope_over={"issued_at": _iso(-700),
                                      "expires_at": _iso(-10)})
        _wait_rejected(mock, 706, "envelope_expired")


# ================================================= (e) STEVE key trust ====

def _inproc_connector(tmp_path, mock, code="PAIR-1234"):
    home = tmp_path / "home"
    os.makedirs(home, exist_ok=True)
    with open(home / "config.toml", "w") as fh:
        fh.write('base_url = "%s"\npairing_code = "%s"\npoll_wait = 1\n'
                 'token_retry = 1\nprograms_dir = "%s"\nrepo_root = "%s"\n'
                 % (mock.base_url, code, home / "programs", REPO))
    return connector_mod.Connector(str(home))


class TestSteveKeys:
    def test_enroll_requires_self_consistent_keys(self, tmp_path):
        """Enroll list signed only by a key NOT in the list -> fail."""
        mock = MockSteve(code="PAIR-K1")
        base = mock.serve_forever()
        try:
            keys = [{"kid": "steve-2026-a",
                     "public_key": crypto.b64(crypto.public_raw(mock.key))}]
            evil = crypto.new_key()
            mock.enroll_keys_override = {
                "list": {"keys": keys},
                "signatures": [{"kid": "evil-kid",
                              "sig": crypto.b64(evil.sign(
                                  crypto.canonical_json({"keys": keys})))}]}
            c = _inproc_connector(tmp_path, mock, "PAIR-K1")
            with pytest.raises(SteveError) as ei:
                c.enroll()
            assert ei.value.code == "keys_untrusted"
            assert not c.state.get("enrolled")
        finally:
            mock.stop()

    def test_rotation_signed_by_trusted_kid_accepted(self, tmp_path):
        mock = MockSteve(code="PAIR-K2")
        base = mock.serve_forever()
        try:
            mock.confirm()
            c = _inproc_connector(tmp_path, mock, "PAIR-K2")
            c.enroll()
            assert set(c.state["steve_keys"]) == {"steve-2026-a"}
            # rotate to a new key, signed by the trusted kid "steve-2026-a"
            k2 = crypto.new_key()
            new_keys = [{"kid": "steve-2026-b",
                        "public_key": crypto.b64(crypto.public_raw(k2))}]
            mock.keys_override = crypto.sign_keys_list(mock.key, new_keys,
                                                      kid="steve-2026-a")
            c.refresh_steve_keys()
            assert set(c.state["steve_keys"]) == {"steve-2026-b"}
            # envelopes signed by the new key under the new kid verify now
            env = {"id": 801, "action": "adaptive_rough", "inputs": {},
                   "connector": c.fingerprint, "issued_at": int(time.time()),
                   "expires_at": int(time.time()) + 600, "nonce": "rot-1"}
            msg = {"kind": "run", "envelope": env, "kid": "steve-2026-b",
                   "sig": crypto.b64(k2.sign(crypto.canonical_json(env)))}
            ok, code = c.verify_envelope(msg)
            assert ok, code
        finally:
            mock.stop()

    def test_rotation_by_untrusted_key_rejected_keeps_old(self, tmp_path):
        mock = MockSteve(code="PAIR-K3")
        base = mock.serve_forever()
        try:
            mock.confirm()
            c = _inproc_connector(tmp_path, mock, "PAIR-K3")
            c.enroll()
            k3 = crypto.new_key()
            new_keys = [{"kid": "steve-2026-c",
                        "public_key": crypto.b64(crypto.public_raw(k3))}]
            # signed by the NEW key itself, which is not trusted yet
            mock.keys_override = crypto.sign_keys_list(k3, new_keys,
                                                      kid="steve-2026-c")
            c.refresh_steve_keys()
            assert set(c.state["steve_keys"]) == {"steve-2026-a"}
        finally:
            mock.stop()

    def test_tampered_keys_list_rejected(self, tmp_path):
        mock = MockSteve(code="PAIR-K4")
        base = mock.serve_forever()
        try:
            mock.confirm()
            c = _inproc_connector(tmp_path, mock, "PAIR-K4")
            c.enroll()
            new_keys = [{"kid": "steve-2026-b",
                        "public_key": crypto.b64(
                            crypto.public_raw(crypto.new_key()))}]
            listing = crypto.sign_keys_list(mock.key, new_keys,
                                           kid="steve-2026-a")
            # tamper after signing: inject an extra key
            listing["list"]["keys"].append(
                {"kid": "evil", "public_key": crypto.b64(
                    crypto.public_raw(crypto.new_key()))})
            mock.keys_override = listing
            c.refresh_steve_keys()
            assert set(c.state["steve_keys"]) == {"steve-2026-a"}
        finally:
            mock.stop()


# ============================================ (f) token not persisted ======

class TestTokenNotPersisted:
    def test_no_token_key_or_signature_in_state_dir(self, live):
        mock, home, _ = live
        assert mock.token, "mock never issued a token"
        with open(home / "identity.key") as fh:
            seed = fh.read().strip()
        blob = {}
        for root, _dirs, files in os.walk(home):
            for name in files:
                if name == "identity.key":  # the key file itself is allowed
                    continue
                with open(os.path.join(root, name), "rb") as fh:
                    blob[name] = fh.read().decode("utf-8", errors="ignore")
        all_text = "\n".join(blob.values())
        # the bearer token and the private seed appear nowhere in the state dir
        assert mock.token not in all_text
        assert seed not in all_text
        # and the JSON state files carry no token/signature fields at all
        st = json.loads(blob["state.json"])
        assert "token" not in st and "token_exp" not in st
        led = json.loads(blob["ledger.json"])
        assert not any("sig" in k for k in led)
        for name, text in blob.items():
            if name.endswith(".json"):
                assert '"signatures"' not in text, name


# ============================================ (g) slope_split_finish ======

class TestSlopeCatalog:
    """Catalog shape for the new action (no live mock needed)."""

    def test_action_shape(self):
        a = catalog_mod.get_action(catalog_mod.SLOPE_ACTION)
        assert a is not None
        assert a["name"] == "slope_split_finish"
        assert a["title"] == "Slope-split finishing"
        assert a["confirm"] is False
        # name rules: lowercase letters/digits/_, starts with a letter, <= 40
        assert len(a["name"]) <= 40
        assert a["name"][0].isalpha() and a["name"] == a["name"].lower()
        props = a["inputs"]["properties"]
        assert len(props) <= 30, "more than 30 inputs"
        assert a["inputs"]["required"] == ["model"]
        assert props["model"].get("x-steve") == "file"
        assert props["model"]["format"] == "step"
        for n in props:
            assert len(n) <= 40 and n == n.lower()

    def test_limits_and_defaults(self):
        a = catalog_mod.get_action(catalog_mod.SLOPE_ACTION)
        p = a["inputs"]["properties"]
        assert p["tool_diameter"]["minimum"] == 1.0
        assert p["tool_diameter"]["maximum"] == 25.0
        assert p["tool_diameter"]["default"] == 6.0
        for k in ("stepover", "stepdown"):
            assert p[k]["minimum"] == 0.05 and p[k]["maximum"] == 2.0
            assert p[k]["default"] == 0.3
        assert p["slope_threshold"]["minimum"] == 10.0
        assert p["slope_threshold"]["maximum"] == 80.0
        assert p["slope_threshold"]["default"] == 40.0
        assert p["units"]["enum"] == ["inch", "mm"]
        assert p["units"]["default"] == "inch"
        # same orientation enum + stock inputs as adaptive_rough
        r = catalog_mod.get_action(catalog_mod.ACTION)["inputs"]["properties"]
        assert p["orientation"] == r["orientation"]
        for k in ("stock_xy", "stock_top", "stock_bottom", "floor_z"):
            assert p[k] == r[k], k

    def test_roughing_inputs_mirror_adaptive_rough_defaults(self):
        a = catalog_mod.get_action(catalog_mod.SLOPE_ACTION)
        p = a["inputs"]["properties"]
        r = catalog_mod.get_action(catalog_mod.ACTION)["inputs"]["properties"]
        for k in ("tool_type", "tool_diameter", "corner_radius",
                  "flute_length", "stepdown", "optimal_load",
                  "stock_to_leave", "rest_stepup"):
            assert p["rough_" + k]["default"] == r[k]["default"], k
        # description says run after roughing
        assert "run after roughing" in a["description"].lower()

    def test_validate_rejects(self):
        ok, code, v = catalog_mod.validate_inputs(
            {"model": "m", "slope_threshold": 90.0},
            catalog_mod.SLOPE_ACTION)
        assert not ok and code == "input_out_of_range"
        ok, code, v = catalog_mod.validate_inputs(
            {"model": "m", "tool_diameter": 0.5}, catalog_mod.SLOPE_ACTION)
        assert not ok and code == "input_out_of_range"
        ok, code, v = catalog_mod.validate_inputs(
            {"model": "m", "rough_stepdown": 100.0},
            catalog_mod.SLOPE_ACTION)
        assert not ok and code == "input_out_of_range"
        ok, code, v = catalog_mod.validate_inputs(
            {}, catalog_mod.SLOPE_ACTION)
        assert not ok and code == "input_missing"


class TestSlopeSplitFinish:
    def test_e2e_chain_rough_then_finish(self, live):
        mock, home, programs = live
        mock.enqueue_run(801, action=catalog_mod.SLOPE_ACTION,
                         inputs=dict(SLOPE_GOOD_INPUTS,
                                     model=model_input(mock)))
        assert mock.wait_state(801, "received", 30), \
            "run never received: %s" % mock.states_for(801)
        final = mock.wait_terminal(801, timeout=600)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(801))

        reps = {r["body"]["state"]: r["body"] for r in mock.reports
                if str(r["run_id"]) == "801"}
        result = reps["succeeded"].get("result") or {}
        for key in ("estimated_time_min", "cut_length_mm", "probe_clcheck",
                    "zmap", "programs"):
            assert key in result, "missing %s in result" % key
        # clcheck on the posted finish output must be 0
        assert result["probe_clcheck"]["below_cl"] == 0
        assert result["probe_clcheck"]["points"] > 0
        # chained zmap judgement: roughing from full stock, finish with the
        # roughed stock as stock-in (never a finish judged from raw stock)
        zmap = result["zmap"]
        assert zmap["stock_in"] == "roughing"
        assert zmap["gouges"]["rough"] == 0
        assert zmap["gouges"]["finish"] == 0
        assert zmap["rapid_collisions"]["rough"] == 0
        assert zmap["rapid_collisions"]["finish"] == 0
        assert result["cut_length_mm"] > 100

        # BOTH programs uploaded (never a finish-only program)
        names = mock.file_names(801)
        for f in ("rough.nc", "finish.nc", "check.json", "preview.png"):
            assert f in names, "missing upload %s: %s" % (f, names)
        assert mock.file_info(801, "preview.png")["media"] == "image/png"

        # the finish header carries the run-after-roughing comment
        with open(home / "runs" / "801" / "finish.nc") as fh:
            head = fh.read(4000).lower()
        assert "run after roughing" in head

        # both programs copied to the configured programs folder
        assert (programs / "O1002_rough.nc").exists()
        assert (programs / "O1002_finish.nc").exists()

    def test_out_of_range_input_rejected(self, live):
        mock, _, _ = live
        mock.enqueue_run(802, action=catalog_mod.SLOPE_ACTION,
                         inputs=dict(SLOPE_GOOD_INPUTS,
                                     model=model_input(mock),
                                     slope_threshold=90.0))
        _wait_rejected(mock, 802, "input_out_of_range")

    def test_missing_tool_fails_with_clear_message(self, live):
        mock, _, _ = live
        # a 6 mm ball is not in the X7 table: without a tool_number the
        # connector must refuse instead of silently posting T1
        inputs = dict(SLOPE_GOOD_INPUTS, model=model_input(mock),
                      tool_diameter=6.0)
        del inputs["tool_number"]
        mock.enqueue_run(803, action=catalog_mod.SLOPE_ACTION, inputs=inputs)
        final = mock.wait_terminal(803, timeout=120)
        assert final == "failed", mock.states_for(803)
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == "803"
               and r["body"]["state"] == "failed"][-1]
        msg = rep.get("error", {}).get("message", "")
        assert "x7_tools" in msg and "tool_number" in msg, msg
        # nothing was posted: no finish-only (or any) program uploaded
        assert mock.file_names(803) == []


class TestRestPass:
    """Task CR: optional corner rest pass in slope_split_finish, reachable
    from STEVE through the catalog (rest_tool_number + min_rest)."""

    def test_catalog_rest_inputs(self):
        a = catalog_mod.get_action(catalog_mod.SLOPE_ACTION)
        p = a["inputs"]["properties"]
        assert p["rest_tool_number"]["type"] == "integer"
        assert p["rest_tool_number"]["minimum"] == 1
        assert "default" not in p["rest_tool_number"]
        assert p["min_rest"]["type"] == "number"
        assert p["min_rest"]["minimum"] == 0.1
        assert p["min_rest"]["default"] == 0.5
        # absent rest_tool_number = today's behaviour exactly
        ok, _, v = catalog_mod.validate_inputs(
            {"model": "m"}, catalog_mod.SLOPE_ACTION)
        assert ok and v["rest_tool_number"] is None
        assert v["min_rest"] == 0.5
        # rest_tool_number accepted, min_rest below 0.1 rejected
        ok, _, v = catalog_mod.validate_inputs(
            {"model": "m", "rest_tool_number": 31}, catalog_mod.SLOPE_ACTION)
        assert ok and v["rest_tool_number"] == 31
        ok, code, _ = catalog_mod.validate_inputs(
            {"model": "m", "rest_tool_number": 31, "min_rest": 0.05},
            catalog_mod.SLOPE_ACTION)
        assert not ok and code == "input_out_of_range"

    def test_rest_chain_argv(self, tmp_path, monkeypatch):
        """Unit (no engine): with rest_tool_number the runner chains a third
        program - rough exports its stock for --stock-from, the finish zmap
        exports the stock after finishing, the rest finish runs --rest-from
        that stock, rest.nc posts with program number +2 and the rest tool
        number, clcheck runs with the rest ball diameter, and the rest zmap
        is chained with --stock-in = the finish's --stock-out."""
        import numpy as np
        import runner as runner_mod

        calls = []

        def fake_spawn(self, argv, lo, hi, on_progress, json_out=None,
                       extra_env=None):
            a = list(argv)
            calls.append(a)

            def opt(flag):
                return a[a.index(flag) + 1] if flag in a else None

            if "verify.zmap" in a:
                so = opt("--stock-out")
                if so:
                    np.save(so, np.full((8, 8), -1.0))
                report = {
                    "gouges": {"count": 0, "max_depth": 0.0,
                              "worst_xy": None},
                    "rapid_collisions": {"count": 0, "first_line": None},
                    "outside_grid": {"count": 0, "first_line": None},
                    "over_flute": {"count": 0, "max_depth": 0.0,
                                   "worst_xy": None, "first_line": None},
                    "holder": {"status": "checked", "name": "BT30-ER20-60",
                              "stickout_mm": 60.0,
                              "dimension_source": "drawing"},
                    "holder_hits": {"count": 0, "max_intrusion": 0.0,
                                    "worst_xy": None, "first_line": None},
                    "leftover": {"max": 0.0, "mean": 0.0, "p95": 0.0},
                    "within_0p5mm_fraction": 1.0,
                    "cycle_time_s": 1.0,
                    "cutting_length_mm": 100.0,
                    "rapid_length_mm": 10.0,
                    "engagement": {"threshold_mm": 0.45, "count": 0,
                                   "max_mm": 0.0, "spikes": []},
                    "plunge": {"ramp_angle_deg": 3.0, "count": 0,
                               "flags": []},
                }
                with open(opt("--out-json"), "w") as fh:
                    json.dump(report, fh)
            elif any(tok.endswith("heightfield.py") for tok in a):
                np.save(extra_env["HF_OUT"], np.full((8, 8), 0.4))
                with open(os.path.splitext(extra_env["HF_OUT"])[0] + ".json",
                          "w") as fh:
                    json.dump({
                        "step_sha256": hashlib.sha256(
                            open(extra_env["STEP_IN"], "rb").read()
                        ).hexdigest(),
                        "x0": -12.0, "y0": -12.0,
                        "cell": float(extra_env["CELL"]),
                        "tess_tol": float(extra_env.get("TESS_TOL", 0.01)),
                    }, fh)
            elif any(tok.endswith("_tessellate.py") for tok in a):
                with open(extra_env["STL_OUT"], "wb") as fh:
                    fh.write(b"solid fake\nendsolid fake\n")
            elif any(tok.endswith("probe_clcheck.py") for tok in a):
                if json_out is not None:
                    json_out.append({"below_cl": 0, "points": 42,
                                     "max_depth_mm": 0.0})
            elif "engine.cli" in a:
                sub = a[a.index("engine.cli") + 1]
                if sub == "prepare":
                    with open(os.path.join(self.work, "o.step"), "w") as fh:
                        fh.write("ISO-10303-21; fake oriented step\nEND;")
                    with open(os.path.join(self.work, "prepare.json"),
                             "w") as fh:
                        json.dump({"step": os.path.join(self.work, "o.step"),
                                   "hf": os.path.join(self.work, "hf.npz"),
                                   "stock": [-10.0, 10.0, -10.0, 10.0,
                                           -1.0, 0.4]}, fh)
                else:
                    out = opt("--out")
                    if out:
                        with open(out, "w") as fh:
                            fh.write("G21 G90\nG0 X0. Y0. Z5.\n")
                    sj = opt("--stats-json")
                    if sj:
                        with open(sj, "w") as fh:
                            json.dump({"levels": [{"skipped": False}],
                                       "n_moves": 10}, fh)
            return None

        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake_spawn)
        cfg = {"engine_python": PY, "repo_root": REPO}
        run = runner_mod.EngineRun(cfg, str(tmp_path))
        values = dict(SLOPE_GOOD_INPUTS, rest_tool_number=31)
        result, files = run.run_slope_split_finish(
            os.path.join(HERE, "unused.step"), values)

        # roughing exports its own stock for the rest pass's --stock-from
        rough_call = [a for a in calls
                      if "engine.cli" in a and "rough" in a[
                          a.index("engine.cli") + 1]][0]
        assert "--stock-out" in rough_call
        # the finish pass itself is unchanged: no rest flags
        fin_call = [a for a in calls
                   if "engine.cli" in a and a[
                       a.index("engine.cli") + 1] == "finish"][0]
        assert "--rest-from" not in fin_call
        # the finish plans its rapids/holder against the roughing stock
        rough_out = rough_call[rough_call.index("--stock-out") + 1]
        assert fin_call[fin_call.index("--stock-from") + 1] == rough_out

        # three zmap calls, chained: rough -> finish -> rest
        zmaps = [a for a in calls if "verify.zmap" in a]
        assert len(zmaps) == 3, zmaps
        zf, zr = zmaps[1], zmaps[2]
        assert "--stock-out" in zf
        assert zf[zf.index("--stock-out") + 1].endswith(
            "stock_after_finish.npy")
        assert "--png" not in zf, "preview.png moves to the last program"
        assert zr[zr.index("--stock-in") + 1].endswith(
            "stock_after_finish.npy")
        assert zr[zr.index("--dia") + 1] == "5.9580"
        assert zr[zr.index("--tool-number") + 1] == "31"
        assert zr[zr.index("--flute") + 1] == "12.0000"
        assert zr[zr.index("--shank-dia") + 1] == "5.9580"
        assert "--png" in zr

        # the rest finish: rest-from the post-finish stock, rest-tool the
        # smaller ball from the table, min_rest default 0.5, and it carries
        # the rest tool's table geometry for the shank/holder rules
        rest_fin = [a for a in calls
                    if "engine.cli" in a and a[
                        a.index("engine.cli") + 1] == "finish"
                    and "--rest-from" in a][0]
        assert rest_fin[rest_fin.index("--tool") + 1] == "ball:9.5250"
        assert rest_fin[rest_fin.index("--out") + 1].endswith(
            "rest_neutral.ngc")
        assert rest_fin[rest_fin.index("--rest-tool") + 1] == "ball:5.9580"
        assert rest_fin[rest_fin.index("--min-rest") + 1] == "0.5000"
        assert rest_fin[rest_fin.index("--stock-from") + 1].endswith(
            "stock_after_rough_engine.npy")
        assert rest_fin[rest_fin.index("--flute") + 1] == "12.0000"
        assert rest_fin[rest_fin.index("--holder") + 1] == "BT30-ER20-60"

        # posted as rest.nc: program number +2, T = rest tool
        post = [a for a in calls
                if "engine.cli" in a and a[
                    a.index("engine.cli") + 1] == "post"
                and "--out" in a
                and a[a.index("--out") + 1].endswith("rest.nc")][0]
        assert post[post.index("--program") + 1] == \
            str(SLOPE_GOOD_INPUTS["program_number"] + 2)
        assert post[post.index("--tool-number") + 1] == "31"

        # clcheck on rest.nc with the rest ball diameter
        cls = [a for a in calls if any(t.endswith("probe_clcheck.py")
                                       for t in a)]
        assert len(cls) == 2
        assert cls[1][2].endswith("rest.nc")
        assert cls[1][4] == "5.9580"

        # check.json: rest section alongside rough/finish
        with open(os.path.join(str(tmp_path), "check.json")) as fh:
            check = json.load(fh)
        assert check["chain"] == ["rough", "finish", "rest"]
        for k in ("gouges", "rapid_collisions", "over_flute", "holder_hits"):
            assert k in check["rest"], "rest gate %s missing" % k
        assert check["warnings"]["engagement"]["rest"] is not None
        assert check["probe_clcheck_rest"]["gcode"] == "rest.nc"

        # summary: rest cut length/time and the combined cycle time
        assert result["programs"]["rest"]["file"] == "rest.nc"
        assert result["programs"]["rest"]["tool"]["number"] == 31
        assert result["programs"]["rest"]["cut_length_mm"] == 100.0
        assert result["zmap"]["gouges"]["rest"] == 0
        assert result["files"] == ["rough.nc", "finish.nc", "rest.nc",
                                  "check.json", "preview.png"]
        assert "rest.nc" in files
        # combined = rough + finish + rest (each fake reports 1.0 s / 100 mm)
        assert result["estimated_time_min"] == pytest.approx(3.0 / 60.0,
                                                            abs=0.01)
        assert result["cut_length_mm"] == pytest.approx(300.0)

        # without a rest pass the finish still gets the roughing stock
        # (regression: rapids were planned against the part + 1 mm only and
        # crossed T13 roughing terraces on Core Front)
        calls.clear()
        run2 = runner_mod.EngineRun(cfg, str(tmp_path / "norest"))
        run2.run_slope_split_finish(os.path.join(HERE, "unused.step"),
                                    dict(SLOPE_GOOD_INPUTS))
        r2 = [a for a in calls if "engine.cli" in a
              and a[a.index("engine.cli") + 1] == "rough"][0]
        f2 = [a for a in calls if "engine.cli" in a
              and a[a.index("engine.cli") + 1] == "finish"][0]
        assert f2[f2.index("--stock-from") + 1] == \
            r2[r2.index("--stock-out") + 1]

    def test_rest_tool_unknown_fails_before_engine(self, tmp_path,
                                                   monkeypatch):
        import runner as runner_mod
        spawned = []
        monkeypatch.setattr(
            runner_mod.EngineRun, "_spawn",
            lambda self, argv, lo, hi, on_progress, json_out=None,
            extra_env=None: spawned.append(list(argv)))
        cfg = {"engine_python": PY, "repo_root": REPO}
        run = runner_mod.EngineRun(cfg, str(tmp_path))
        with pytest.raises(runner_mod.EngineError) as e:
            run.run_slope_split_finish(
                os.path.join(HERE, "unused.step"),
                dict(SLOPE_GOOD_INPUTS, rest_tool_number=999))
        assert "x7_tools" in str(e.value)
        assert spawned == [], "unknown rest tool must fail before any engine"

    def test_rest_tool_without_holder_fails_before_engine(self, tmp_path,
                                                           monkeypatch):
        """T3 (bull 12.7) is in the table but has no holder: a rest pass is
        never judged without the holder clearance check."""
        import runner as runner_mod
        spawned = []
        monkeypatch.setattr(
            runner_mod.EngineRun, "_spawn",
            lambda self, argv, lo, hi, on_progress, json_out=None,
            extra_env=None: spawned.append(list(argv)))
        cfg = {"engine_python": PY, "repo_root": REPO}
        run = runner_mod.EngineRun(cfg, str(tmp_path))
        with pytest.raises(runner_mod.EngineError) as e:
            run.run_slope_split_finish(
                os.path.join(HERE, "unused.step"),
                dict(SLOPE_GOOD_INPUTS, rest_tool_number=3))
        assert "holder" in str(e.value)
        assert spawned == []

    def test_e2e_rest_pass(self, live):
        """STEVE -> catalog -> three posted programs: rough.nc, finish.nc and
        rest.nc, with the rest gates in check.json."""
        mock, home, programs = live
        mock.enqueue_run(920, action=catalog_mod.SLOPE_ACTION,
                         inputs=dict(SLOPE_GOOD_INPUTS,
                                     model=model_input(mock),
                                     rest_tool_number=31))
        assert mock.wait_state(920, "received", 30), \
            "run never received: %s" % mock.states_for(920)
        final = mock.wait_terminal(920, timeout=900)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(920))

        # all three programs uploaded
        names = mock.file_names(920)
        for f in ("rough.nc", "finish.nc", "rest.nc", "check.json",
                  "preview.png"):
            assert f in names, "missing upload %s: %s" % (f, names)

        reps = {r["body"]["state"]: r["body"] for r in mock.reports
                if str(r["run_id"]) == "920"}
        result = reps["succeeded"].get("result") or {}
        assert result["programs"]["rest"]["tool"]["number"] == 31
        assert result["programs"]["rest"]["cut_length_mm"] > 0
        assert result["zmap"]["gouges"]["rest"] == 0
        assert result["zmap"]["rapid_collisions"]["rest"] == 0
        assert result["probe_clcheck_rest"]["below_cl"] == 0
        # combined cycle time covers all three programs
        p = result["programs"]
        assert result["estimated_time_min"] >= \
            p["rough"]["estimated_time_min"] + \
            p["finish"]["estimated_time_min"]

        with open(home / "runs" / "920" / "check.json") as fh:
            check = json.load(fh)
        assert check["chain"] == ["rough", "finish", "rest"]
        for k in ("gouges", "rapid_collisions", "over_flute", "holder_hits"):
            assert k in check["rest"], "rest gate %s missing" % k
        assert check["rest"]["gouges"]["count"] == 0
        assert check["rest"]["rapid_collisions"]["count"] == 0
        assert check["rest"]["over_flute"]["count"] == 0
        assert check["rest"]["holder_hits"]["count"] == 0

        # rest.nc: program number +2, T31, metric
        with open(home / "runs" / "920" / "rest.nc") as fh:
            text = fh.read()
        assert "O%d" % (SLOPE_GOOD_INPUTS["program_number"] + 2) in text
        assert "T31 M06" in text

        # the rest program is copied to the programs folder too
        assert list(programs.glob("*_rest.nc"))

    def test_e2e_unknown_rest_tool_fails(self, live):
        mock, _, programs = live
        mock.enqueue_run(921, action=catalog_mod.SLOPE_ACTION,
                         inputs=dict(SLOPE_GOOD_INPUTS,
                                     model=model_input(mock),
                                     rest_tool_number=999))
        assert mock.wait_state(921, "received", 30)
        final = mock.wait_terminal(921, timeout=120)
        assert final == "failed", mock.states_for(921)
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == "921"
               and r["body"]["state"] == "failed"][-1]
        assert "x7_tools" in rep.get("error", {}).get("message", "")
        assert mock.file_names(921) == []
        assert not list(programs.glob("O1004*"))

    def test_e2e_rest_tool_without_holder_fails(self, live):
        mock, _, programs = live
        mock.enqueue_run(922, action=catalog_mod.SLOPE_ACTION,
                         inputs=dict(SLOPE_GOOD_INPUTS,
                                     model=model_input(mock),
                                     rest_tool_number=3))
        assert mock.wait_state(922, "received", 30)
        final = mock.wait_terminal(922, timeout=120)
        assert final == "failed", mock.states_for(922)
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == "922"
               and r["body"]["state"] == "failed"][-1]
        assert "holder" in rep.get("error", {}).get("message", "")
        assert mock.file_names(922) == []


class TestWarningsInCheckJson:
    """Review 2: check.json must contain warnings.engagement and warnings.plunge."""

    def test_rough_check_json_has_warnings(self, live):
        """adaptive_rough: check.json carries warnings.engagement + warnings.plunge."""
        mock, home, _ = live
        mock.enqueue_run(850, inputs=dict(GOOD_INPUTS,
                                         model=model_input(mock)))
        assert mock.wait_state(850, "received", 30)
        final = mock.wait_terminal(850, timeout=300)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(850))

        # check.json uploaded with the run
        names = mock.file_names(850)
        assert "check.json" in names, "missing check.json: %s" % names

        # Read the check.json from the work dir
        with open(home / "runs" / "850" / "check.json") as fh:
            check = json.load(fh)
        w = check.get("warnings", {})
        assert "engagement" in w, \
            "warnings.engagement missing from check.json"
        assert "plunge" in w, \
            "warnings.plunge missing from check.json"
        # No inf/NaN in the JSON (json.load already succeeded, but verify
        # numeric fields are finite)
        eng = w["engagement"]
        assert "max_mm" in eng
        # Z6: the roughing threshold is explicitly 1.2 x optimal load
        assert eng["threshold_mm"] == pytest.approx(
            1.2 * GOOD_INPUTS["optimal_load"]), \
            "rough check.json threshold %r != 1.2 x optimal load" \
            % eng["threshold_mm"]
        if eng["max_mm"] is not None:
            import math
            assert math.isfinite(eng["max_mm"]), \
                "engagement max_mm is not finite"

    def test_slope_check_json_has_warnings(self, live):
        """slope_split_finish: check.json carries warnings for both stages."""
        mock, home, _ = live
        mock.enqueue_run(851, action=catalog_mod.SLOPE_ACTION,
                         inputs=dict(SLOPE_GOOD_INPUTS,
                                     model=model_input(mock)))
        assert mock.wait_state(851, "received", 30), \
            "run never received: %s" % mock.states_for(851)
        final = mock.wait_terminal(851, timeout=600)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(851))

        with open(home / "runs" / "851" / "check.json") as fh:
            check = json.load(fh)
        w = check.get("warnings", {})
        assert "engagement" in w, \
            "warnings.engagement missing from check.json"
        assert "plunge" in w, \
            "warnings.plunge missing from check.json"
        # Both rough and finish stages present
        assert "rough" in w["engagement"], \
            "warnings.engagement.rough missing"
        assert "finish" in w["engagement"], \
            "warnings.engagement.finish missing"
        assert "rough" in w["plunge"], \
            "warnings.plunge.rough missing"
        assert "finish" in w["plunge"], \
            "warnings.plunge.finish missing"
        # Z6: rough threshold 1.2 x rough optimal load, finish 1.5 x stepover
        assert w["engagement"]["rough"]["threshold_mm"] == pytest.approx(
            1.2 * SLOPE_GOOD_INPUTS["rough_optimal_load"])
        assert w["engagement"]["finish"]["threshold_mm"] == pytest.approx(
            1.5 * SLOPE_GOOD_INPUTS["stepover"])


class TestEngageThresholdArgs:
    """Z6 (unit, no engine): every roughing zmap call carries an explicit
    --engage-max of 1.2 x rough optimal load (ROUGH_ENGAGE_FACTOR); the
    finishing call keeps 1.5 x stepover (FINISH_ENGAGE_FACTOR); the combined
    check.json carries both thresholds."""

    def test_module_constants(self):
        import runner as runner_mod
        assert runner_mod.ROUGH_ENGAGE_FACTOR == 1.2
        assert runner_mod.FINISH_ENGAGE_FACTOR == 1.5

    def test_slope_zmap_calls_and_check_json_thresholds(self, tmp_path,
                                                          monkeypatch):
        import numpy as np
        import runner as runner_mod

        calls = []

        def fake_spawn(self, argv, lo, hi, on_progress, json_out=None,
                       extra_env=None):
            a = list(argv)
            calls.append(a)

            def opt(flag):
                return a[a.index(flag) + 1] if flag in a else None

            if "verify.zmap" in a:
                engage, optimal = opt("--engage-max"), opt("--optimal-load")
                thr = float(engage) if engage is not None else (
                    1.2 * float(optimal) if optimal is not None else None)
                so = opt("--stock-out")
                if so:
                    np.save(so, np.full((8, 8), -1.0))
                report = {
                    "gouges": {"count": 0, "max_depth": 0.0,
                              "worst_xy": None},
                    "rapid_collisions": {"count": 0, "first_line": None},
                    "outside_grid": {"count": 0, "first_line": None},
                    "over_flute": {"count": 0, "max_depth": 0.0,
                                   "worst_xy": None, "first_line": None},
                    "holder": {"status": "checked", "name": "BT30-ER20-60",
                              "stickout_mm": 60.0,
                              "dimension_source": "drawing"},
                    "holder_hits": {"count": 0, "max_intrusion": 0.0,
                                    "worst_xy": None, "first_line": None},
                    "leftover": {"max": 0.0, "mean": 0.0, "p95": 0.0},
                    "within_0p5mm_fraction": 1.0,
                    "cycle_time_s": 1.0,
                    "cutting_length_mm": 100.0,
                    "rapid_length_mm": 10.0,
                    "engagement": {"threshold_mm": thr, "count": 0,
                                   "max_mm": 0.0, "spikes": []},
                    "plunge": {"ramp_angle_deg": 3.0, "count": 0,
                               "flags": []},
                }
                with open(opt("--out-json"), "w") as fh:
                    json.dump(report, fh)
            elif any(tok.endswith("heightfield.py") for tok in a):
                np.save(extra_env["HF_OUT"], np.full((8, 8), 0.4))
                # well-behaved build under task HC: sidecar pins the STEP,
                # cell and tess tolerance of THIS build
                with open(os.path.splitext(extra_env["HF_OUT"])[0] + ".json",
                          "w") as fh:
                    json.dump({
                        "step_sha256": hashlib.sha256(
                            open(extra_env["STEP_IN"], "rb").read()
                        ).hexdigest(),
                        "cell": float(extra_env["CELL"]),
                        "tess_tol": float(extra_env.get("TESS_TOL", 0.01)),
                    }, fh)
            elif any(tok.endswith("_tessellate.py") for tok in a):
                with open(extra_env["STL_OUT"], "wb") as fh:
                    fh.write(b"solid fake\nendsolid fake\n")
            elif any(tok.endswith("probe_clcheck.py") for tok in a):
                if json_out is not None:
                    json_out.append({"below_cl": 0, "points": 42,
                                     "max_depth_mm": 0.0})
            elif "engine.cli" in a:
                sub = a[a.index("engine.cli") + 1]
                if sub == "prepare":
                    with open(os.path.join(self.work, "o.step"), "w") as fh:
                        fh.write("ISO-10303-21; fake oriented step\nEND;")
                    with open(os.path.join(self.work, "prepare.json"),
                             "w") as fh:
                        json.dump({"step": os.path.join(self.work, "o.step"),
                                   "hf": os.path.join(self.work, "hf.npz"),
                                   "stock": [-10.0, 10.0, -10.0, 10.0,
                                           -1.0, 0.4]}, fh)
                else:
                    out = opt("--out")
                    if out:
                        with open(out, "w") as fh:
                            fh.write("G21 G90\nG0 X0. Y0. Z5.\n")
                    sj = opt("--stats-json")
                    if sj:
                        with open(sj, "w") as fh:
                            json.dump({"levels": [{"skipped": False}],
                                       "n_moves": 10}, fh)
            return None

        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake_spawn)
        cfg = {"engine_python": PY, "repo_root": REPO}
        run = runner_mod.EngineRun(cfg, str(tmp_path))
        values = dict(SLOPE_GOOD_INPUTS)
        run.run_slope_split_finish(os.path.join(HERE, "unused.step"),
                                    values)

        zmap_calls = [a for a in calls if "verify.zmap" in a]
        assert len(zmap_calls) == 2, "expected 2 zmap calls: %r" % (
            zmap_calls,)
        rough_call, finish_call = zmap_calls  # rough runs first
        assert "--engage-max" in rough_call
        assert float(rough_call[rough_call.index("--engage-max") + 1]) \
            == pytest.approx(1.2 * values["rough_optimal_load"]), \
            "rough zmap threshold is not 1.2 x rough optimal load"
        assert "--engage-max" in finish_call
        assert float(finish_call[finish_call.index("--engage-max") + 1]) \
            == pytest.approx(1.5 * values["stepover"]), \
            "finish zmap threshold is not 1.5 x stepover"

        with open(os.path.join(str(tmp_path), "check.json")) as fh:
            check = json.load(fh)
        w = check["warnings"]["engagement"]
        assert w["rough"]["threshold_mm"] == pytest.approx(
            1.2 * values["rough_optimal_load"]), \
            "check.json rough threshold is not 1.2x"
        assert w["finish"]["threshold_mm"] == pytest.approx(
            1.5 * values["stepover"]), \
            "check.json finish threshold is not 1.5x"


class TestStaleArtifactsRejected:
    """HC (unit, no FreeCAD): a reused run dir can never accept a stale
    heightfield or STL. The runner removes the .npy + sidecar (and STL)
    before each build, then requires both to exist and the sidecar to carry
    step_sha256 / tess_tol / cell matching what was requested."""

    @staticmethod
    def _fake_spawn(hf_writes=True, hf_sidecar="ok", stl_writes=True):
        """A fake EngineRun._spawn for the slope-split chain.

        hf_sidecar: "ok" pins this build's STEP, "wrong" plants a bogus
        step_sha256. hf_writes/stl_writes=False simulate a build that
        fails silently (rc 0, no output)."""
        import hashlib

        import numpy as np

        def fake_spawn(self, argv, lo, hi, on_progress, json_out=None,
                       extra_env=None):
            a = list(argv)

            def opt(flag):
                return a[a.index(flag) + 1] if flag in a else None

            if any(tok.endswith("heightfield.py") for tok in a):
                if hf_writes:
                    np.save(extra_env["HF_OUT"], np.full((8, 8), 0.4))
                    sha = ("deadbeef" * 8 if hf_sidecar == "wrong"
                          else hashlib.sha256(
                              open(extra_env["STEP_IN"], "rb").read()
                          ).hexdigest())
                    with open(os.path.splitext(extra_env["HF_OUT"])[0]
                              + ".json", "w") as fh:
                        json.dump({"step_sha256": sha,
                                   "cell": float(extra_env["CELL"]),
                                   "tess_tol": float(
                                       extra_env.get("TESS_TOL", 0.01))}, fh)
            elif any(tok.endswith("_tessellate.py") for tok in a):
                if stl_writes:
                    with open(extra_env["STL_OUT"], "wb") as fh:
                        fh.write(b"solid fake\nendsolid fake\n")
            elif "engine.cli" in a:
                sub = a[a.index("engine.cli") + 1]
                if sub == "prepare":
                    with open(os.path.join(self.work, "o.step"), "w") as fh:
                        fh.write("ISO-10303-21; fake oriented step\nEND;")
                    with open(os.path.join(self.work, "prepare.json"),
                             "w") as fh:
                        json.dump({"step": os.path.join(self.work, "o.step"),
                                   "hf": os.path.join(self.work, "hf.npz"),
                                   "stock": [-10.0, 10.0, -10.0, 10.0,
                                           -1.0, 0.4]}, fh)
                else:
                    out = opt("--out")
                    if out:
                        with open(out, "w") as fh:
                            fh.write("G21 G90\nG0 X0. Y0. Z5.\n")
                    sj = opt("--stats-json")
                    if sj:
                        with open(sj, "w") as fh:
                            json.dump({"levels": [{"skipped": False}],
                                       "n_moves": 10}, fh)
            return None

        return fake_spawn

    def _run_expect_fail(self, tmp_path, monkeypatch, fake_spawn):
        import runner as runner_mod
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake_spawn)
        cfg = {"engine_python": PY, "repo_root": REPO}
        run = runner_mod.EngineRun(cfg, str(tmp_path))
        with pytest.raises(runner_mod.EngineError):
            run.run_slope_split_finish(os.path.join(HERE, "unused.step"),
                                        dict(SLOPE_GOOD_INPUTS))
        return run

    def test_stale_hf01_wrong_step_sha_rejected(self, tmp_path,
                                                  monkeypatch):
        """A planted part_hf01.json whose step_sha256 is not this run's
        STEP fails the run even when the .npy rebuild 'succeeds'."""
        import numpy as np
        # plant stale outputs (a redelivered run id reuses this dir)
        np.save(str(tmp_path / "part_hf01.npy"), np.full((8, 8), 9.9))
        with open(str(tmp_path / "part_hf01.json"), "w") as fh:
            json.dump({"step_sha256": "0" * 64, "cell": 0.1,
                      "tess_tol": 0.01}, fh)
        self._run_expect_fail(
            tmp_path, monkeypatch, self._fake_spawn(hf_sidecar="wrong"))

    def test_failing_hf_build_with_stale_file_fails_run(self, tmp_path,
                                                          monkeypatch):
        """The stale part_hf01.npy is removed BEFORE the build, so a build
        that writes nothing cannot leave the old file to be accepted."""
        import numpy as np
        seen = []

        def fake_spawn(self, argv, lo, hi, on_progress, json_out=None,
                       extra_env=None):
            a = list(argv)
            if any(tok.endswith("heightfield.py") for tok in a):
                # stale file must already be gone when the build starts
                seen.append(os.path.exists(extra_env["HF_OUT"]))
                return None  # build fails silently (rc 0, no output)
            return TestStaleArtifactsRejected._fake_spawn(
                hf_writes=False)(self, argv, lo, hi, on_progress,
                                 json_out, extra_env)

        np.save(str(tmp_path / "part_hf01.npy"), np.full((8, 8), 9.9))
        with open(str(tmp_path / "part_hf01.json"), "w") as fh:
            json.dump({"step_sha256": "0" * 64, "cell": 0.1,
                      "tess_tol": 0.01}, fh)
        self._run_expect_fail(tmp_path, monkeypatch, fake_spawn)
        assert seen and all(gone is False for gone in seen), \
            "stale part_hf01.npy was still present when the build ran"
        assert not os.path.exists(str(tmp_path / "part_hf01.npy")), \
            "stale part_hf01.npy survived the run"

    def test_stale_model_stl_fails_run(self, tmp_path, monkeypatch):
        """A planted model.stl cannot stand in for a failed tessellation."""
        with open(str(tmp_path / "model.stl"), "wb") as fh:
            fh.write(b"solid stale\nendsolid stale\n")
        self._run_expect_fail(
            tmp_path, monkeypatch, self._fake_spawn(stl_writes=False))


class TestHolderUnknownGate:
    """H1: the connector FAILS a run unless zmap's check.json reports
    holder.status == "checked"; an unknown holder never uploads a .nc."""

    def test_holder_unknown_fails_run_no_nc(self, live):
        mock, _, _ = live
        # T99 is not in tools/x7_tools.json: no holder outline, no stick-out
        mock.enqueue_run(860, inputs=dict(GOOD_INPUTS, model=model_input(mock),
                                           tool_number=99))
        assert mock.wait_state(860, "received", 30), \
            "run never received: %s" % mock.states_for(860)
        final = mock.wait_terminal(860, timeout=300)
        assert final == "failed", \
            "run ended %s: %s" % (final, mock.states_for(860))
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == "860"
               and r["body"]["state"] == "failed"][-1]
        msg = rep.get("error", {}).get("message", "")
        assert "holder unknown" in msg, msg
        assert not any(n.endswith(".nc") for n in mock.file_names(860)), \
            "holder-unknown run uploaded .nc: %s" % mock.file_names(860)

    def test_check_json_holder_estimated_for_t13(self, live):
        mock, home, _ = live
        mock.enqueue_run(861, inputs=dict(GOOD_INPUTS,
                                           model=model_input(mock)))
        assert mock.wait_state(861, "received", 30), \
            "run never received: %s" % mock.states_for(861)
        final = mock.wait_terminal(861, timeout=300)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(861))
        with open(home / "runs" / "861" / "check.json") as fh:
            check = json.load(fh)
        # T13's holder outline is estimated from the Steve catalogue item
        assert check["holder"] == {"status": "checked",
                                    "name": "BT30-ER32-70",
                                    "stickout_mm": 71.6,
                                    "dimension_source": "estimated"}


# ======================================================== final printout ==


class TestGateFail:
    """Task M4: connector runs must FAIL on any failed zmap gate.
    A failed run must never upload a .nc file."""

    def _fake_run_gouges(self, step_path, values, on_progress=None):
        """Fake EngineRun.run that simulates a gate failure (gouges)."""
        if on_progress:
            on_progress(0.02, "checking")
        raise EngineError("zmap gate: 5 gouges (max 0.300 mm)")

    def _fake_run_over_flute(self, step_path, values, on_progress=None):
        """Fake EngineRun.run that simulates a gate failure (over-flute)."""
        if on_progress:
            on_progress(0.02, "checking")
        raise EngineError("zmap gate: 3 over-flute/shank hits (max 0.500 mm)")

    def _fake_run_rapid(self, step_path, values, on_progress=None):
        """Fake EngineRun.run that simulates a gate failure (rapid collisions)."""
        if on_progress:
            on_progress(0.02, "checking")
        raise EngineError("zmap gate: 2 rapid collisions (first line 30)")

    def test_gouging_run_failed_no_nc(self, tmp_path):
        """Monkeypatched EngineRun raises EngineError for gouges ->
        run reports failed, no .nc uploaded."""
        mock = MockSteve(code="PAIR-G1")
        base = mock.serve_forever()
        try:
            mock.confirm()
            c = _inproc_connector(tmp_path, mock, "PAIR-G1")
            c.enroll()

            from runner import EngineRun
            orig_run = EngineRun.run
            EngineRun.run = self._fake_run_gouges
            try:
                env = {
                    "id": 901, "action": catalog_mod.ACTION,
                    "inputs": dict(GOOD_INPUTS, model=model_input(mock)),
                    "connector": c.fingerprint,
                    "issued_at": int(time.time()),
                    "expires_at": int(time.time()) + 600,
                    "nonce": "gate-fail-1",
                }
                msg = {
                    "kind": "run", "envelope": env,
                    "kid": "steve-2026-a",
                    "sig": crypto.b64(mock.key.sign(
                        crypto.canonical_json(env))),
                }
                c.handle_message(msg)

                reports = [r for r in mock.reports
                           if str(r["run_id"]) == "901"]
                assert len(reports) >= 1
                final = reports[-1]["body"]
                assert final["state"] == "failed", final
                assert "gouge" in final.get("error", {}).get(
                    "message", "").lower()

                uploaded = mock.file_names(901)
                assert "rough.nc" not in uploaded, \
                    "gate-fail run uploaded .nc: %s" % uploaded
            finally:
                EngineRun.run = orig_run
        finally:
            mock.stop()

    def test_over_flute_run_failed_no_nc(self, tmp_path):
        """Monkeypatched EngineRun raises EngineError for over-flute -> failed."""
        mock = MockSteve(code="PAIR-G2")
        base = mock.serve_forever()
        try:
            mock.confirm()
            c = _inproc_connector(tmp_path, mock, "PAIR-G2")
            c.enroll()

            from runner import EngineRun
            orig_run = EngineRun.run
            EngineRun.run = self._fake_run_over_flute
            try:
                env = {
                    "id": 902, "action": catalog_mod.ACTION,
                    "inputs": dict(GOOD_INPUTS, model=model_input(mock)),
                    "connector": c.fingerprint,
                    "issued_at": int(time.time()),
                    "expires_at": int(time.time()) + 600,
                    "nonce": "gate-fail-2",
                }
                msg = {
                    "kind": "run", "envelope": env,
                    "kid": "steve-2026-a",
                    "sig": crypto.b64(mock.key.sign(
                        crypto.canonical_json(env))),
                }
                c.handle_message(msg)

                reports = [r for r in mock.reports
                           if str(r["run_id"]) == "902"]
                assert len(reports) >= 1
                final = reports[-1]["body"]
                assert final["state"] == "failed", final
                assert "over-flute" in final.get("error", {}).get(
                    "message", "").lower()

                uploaded = mock.file_names(902)
                assert "rough.nc" not in uploaded, \
                    "over-flute run uploaded .nc: %s" % uploaded
            finally:
                EngineRun.run = orig_run
        finally:
            mock.stop()

    def test_rapid_collision_run_failed_no_nc(self, tmp_path):
        """Monkeypatched EngineRun raises EngineError for rapid collisions."""
        mock = MockSteve(code="PAIR-G3")
        base = mock.serve_forever()
        try:
            mock.confirm()
            c = _inproc_connector(tmp_path, mock, "PAIR-G3")
            c.enroll()

            from runner import EngineRun
            orig_run = EngineRun.run
            EngineRun.run = self._fake_run_rapid
            try:
                env = {
                    "id": 903, "action": catalog_mod.ACTION,
                    "inputs": dict(GOOD_INPUTS, model=model_input(mock)),
                    "connector": c.fingerprint,
                    "issued_at": int(time.time()),
                    "expires_at": int(time.time()) + 600,
                    "nonce": "gate-fail-3",
                }
                msg = {
                    "kind": "run", "envelope": env,
                    "kid": "steve-2026-a",
                    "sig": crypto.b64(mock.key.sign(
                        crypto.canonical_json(env))),
                }
                c.handle_message(msg)

                reports = [r for r in mock.reports
                           if str(r["run_id"]) == "903"]
                assert len(reports) >= 1
                final = reports[-1]["body"]
                assert final["state"] == "failed", final
                assert "rapid" in final.get("error", {}).get(
                    "message", "").lower()

                uploaded = mock.file_names(903)
                assert "rough.nc" not in uploaded, \
                    "rapid-collision run uploaded .nc: %s" % uploaded
            finally:
                EngineRun.run = orig_run
        finally:
            mock.stop()

    def _fake_run_holder(self, step_path, values, on_progress=None):
        """Fake EngineRun.run that simulates a gate failure (S5 holder
        hits: the holder stack cannot keep 1.0 mm clearance)."""
        if on_progress:
            on_progress(0.02, "checking")
        raise EngineError("zmap gate: 2 holder hits (max intrusion 4.000 mm, "
                          "first line 30) - the holder cannot keep 1.0 mm "
                          "clearance")

    def test_holder_hit_run_failed_no_nc(self, tmp_path):
        """S5: a deliberate holder hit (zmap gate) fails the run and no .nc
        is uploaded."""
        mock = MockSteve(code="PAIR-G4")
        base = mock.serve_forever()
        try:
            mock.confirm()
            c = _inproc_connector(tmp_path, mock, "PAIR-G4")
            c.enroll()

            from runner import EngineRun
            orig_run = EngineRun.run
            EngineRun.run = self._fake_run_holder
            try:
                env = {
                    "id": 904, "action": catalog_mod.ACTION,
                    "inputs": dict(GOOD_INPUTS, model=model_input(mock)),
                    "connector": c.fingerprint,
                    "issued_at": int(time.time()),
                    "expires_at": int(time.time()) + 600,
                    "nonce": "gate-fail-4",
                }
                msg = {
                    "kind": "run", "envelope": env,
                    "kid": "steve-2026-a",
                    "sig": crypto.b64(mock.key.sign(
                        crypto.canonical_json(env))),
                }
                c.handle_message(msg)

                reports = [r for r in mock.reports
                           if str(r["run_id"]) == "904"]
                assert len(reports) >= 1
                final = reports[-1]["body"]
                assert final["state"] == "failed", final
                msg_l = final.get("error", {}).get("message", "").lower()
                assert "holder" in msg_l, msg_l

                uploaded = mock.file_names(904)
                assert not any(n.endswith(".nc") for n in uploaded), \
                    "holder-hit run uploaded .nc: %s" % uploaded
            finally:
                EngineRun.run = orig_run
        finally:
            mock.stop()

def test_zz_print_e2e_result(live):
    mock, _, _ = live
    print("\n==== end-to-end run result JSON ====")
    print(json.dumps(E2E.get("result", {}), indent=2))
    print("==== states:", mock.states_for(501), "====")



# ============================================ task CP: check_program ======

CHECK_INPUTS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0,
}


def program_input(mock, name="check_ok.nc"):
    with open(os.path.join(HERE, "testdata", name), "rb") as fh:
        data = fh.read()
    return {
        "kind": "program", "name": name,
        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
        "url": mock.base_url + "/files/" + name,
        "headers": {"X-Steve-Ticket": "ticket-%d" % (next(_tick),)},
        "document": {"id": "doc-1"}, "revision": 3,
    }


class TestCheckProgramCatalog:
    def test_action_shape(self):
        a = catalog_mod.get_action(catalog_mod.CHECK_ACTION)
        assert a is not None
        assert a["name"] == "check_program" and a["confirm"] is False
        props = a["inputs"]["properties"]
        assert props["program"].get("x-steve") == "program"
        assert props["model"]["x-steve"] == "file"
        assert props["model"]["format"] == "step"
        assert a["inputs"]["required"] == ["program", "model"]
        # stock box inputs identical to adaptive_rough (no floor_z: the
        # program defines its own depths)
        r = catalog_mod.get_action(catalog_mod.ACTION)["inputs"]["properties"]
        for k in ("orientation", "stock_xy", "stock_top", "stock_bottom"):
            assert props[k] == r[k], k
        assert "floor_z" not in props

    def test_validate_inputs(self):
        ok, code, v = catalog_mod.validate_inputs(
            {"program": {"url": "u"}, "model": {"url": "u"}},
            catalog_mod.CHECK_ACTION)
        assert ok, code
        ok, code, _ = catalog_mod.validate_inputs(
            {"model": {"url": "u"}}, catalog_mod.CHECK_ACTION)
        assert not ok and code == "input_missing"
        ok, code, _ = catalog_mod.validate_inputs(
            {"program": {"url": "u"}, "model": {"url": "u"},
             "floor_z": 4.0}, catalog_mod.CHECK_ACTION)
        assert not ok and code == "input_unknown"
        ok, code, _ = catalog_mod.validate_inputs(
            {"program": {"url": "u"}, "model": {"url": "u"},
             "tool_number": 5000}, catalog_mod.CHECK_ACTION)
        assert not ok and code == "input_out_of_range"


class TestCheckProgramToolLookup:
    """Unit tests for the check_program tool resolution (no engine)."""

    def test_program_tool_numbers(self):
        from runner import program_tool_numbers
        assert program_tool_numbers("T13 M06\nG1 X1.\n") == [13]
        assert program_tool_numbers("( T99 in a comment )\nT3 M06\n"
                                    "T3\n") == [3]
        assert program_tool_numbers("T13\nG43 Z5. H13\nT20 M06\n") == \
            [13, 20]

    def test_check_tool_entry_t13(self):
        from runner import check_tool_entry
        t = check_tool_entry(13)
        assert t["type"] == "flat"
        assert abs(t["diameter_mm"] - 12.686) < 1e-9
        assert t["corner_radius_mm"] == 0.0
        assert t["flute_mm"] == 50.8
        assert t["shank_diameter_mm"] == 12.686
        assert t["holder"] == "BT30-ER32-70"
        assert t["stickout_mm"] == 71.6

    def test_check_tool_entry_unknown_fails(self):
        from runner import check_tool_entry, EngineError
        with pytest.raises(EngineError) as ei:
            check_tool_entry(99)
        assert "not in tools/x7_tools.json" in str(ei.value)

    def test_multi_tool_program_fails_before_engine(self, tmp_path,
                                                     monkeypatch):
        import runner as runner_mod

        def boom(*a, **k):
            raise AssertionError("engine ran for a multi-tool program")

        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", boom)
        run = runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                                    str(tmp_path))
        prog = tmp_path / "multi.nc"
        prog.write_text("G21 G90\nT13 M06\nG0 X0.\nT20 M06\n")
        with pytest.raises(runner_mod.EngineError) as ei:
            run.run_check_program(str(prog), "unused.step",
                                  dict(CHECK_INPUTS))
        assert "multi-tool" in str(ei.value)

    def test_no_t_word_fails(self, tmp_path, monkeypatch):
        import runner as runner_mod

        monkeypatch.setattr(runner_mod.EngineRun, "_spawn",
                            lambda *a, **k: None)
        run = runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                                    str(tmp_path))
        prog = tmp_path / "not.nc"
        prog.write_text("G21 G90\nG0 X0. Y0.\n")
        with pytest.raises(runner_mod.EngineError) as ei:
            run.run_check_program(str(prog), "unused.step",
                                  dict(CHECK_INPUTS))
        assert "T word" in str(ei.value)


class TestCheckProgramE2E:
    def test_check_program_ok(self, live):
        mock, _, programs = live
        mock.enqueue_run(910, action=catalog_mod.CHECK_ACTION,
                         inputs=dict(CHECK_INPUTS, model=model_input(mock),
                                    program=program_input(mock)))
        assert mock.wait_state(910, "received", 30), \
            "run never received: %s" % mock.states_for(910)
        final = mock.wait_terminal(910, timeout=600)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(910))
        reps = {r["body"]["state"]: r["body"] for r in mock.reports
                if str(r["run_id"]) == "910"}
        result = reps["succeeded"].get("result") or {}
        assert result["strict"] is True and result["unsupported"] == []
        assert result["zmap_gouges"]["count"] == 0
        assert result["rapid_collisions"]["count"] == 0
        assert result["over_flute"]["count"] == 0
        assert result["holder_hits"]["count"] == 0
        assert result["outside_grid"]["count"] == 0
        # tool came from the program's T word (T13, not an override)
        assert result["tool"]["number"] == 13
        assert result["tool"]["holder"] == "BT30-ER32-70"
        # engagement: report-only, no threshold
        assert result["engagement"]["threshold_mm"] is None
        # check.json + preview.png only: NO .nc upload, nothing new in the
        # programs folder (nothing is sent anywhere near the machine)
        assert mock.file_names(910) == ["check.json", "preview.png"]
        assert not list(programs.glob("O4501*"))

    def test_stale_program_2_in_reused_run_dir_is_not_judged(self, live):
        """A program_2.nc left in a reused run dir must be removed, not
        judged: the run sends only "program", so only it is checked."""
        mock, home, _ = live
        work = home / "runs" / "915"
        work.mkdir(parents=True, exist_ok=True)
        (work / "program_2.nc").write_text(
            open(os.path.join(HERE, "testdata", "check_g81.nc")).read())
        mock.enqueue_run(915, action=catalog_mod.CHECK_ACTION,
                         inputs=dict(CHECK_INPUTS, model=model_input(mock),
                                    program=program_input(mock)))
        final = mock.wait_terminal(915, timeout=600)
        assert final == "succeeded", mock.states_for(915)
        assert not (work / "program_2.nc").exists()

    def test_check_program_g81_fails_unsupported(self, live):
        mock, _, programs = live
        mock.enqueue_run(911, action=catalog_mod.CHECK_ACTION,
                         inputs=dict(CHECK_INPUTS, model=model_input(mock),
                                    program=program_input(mock,
                                                       "check_g81.nc")))
        assert mock.wait_state(911, "received", 30)
        final = mock.wait_terminal(911, timeout=600)
        assert final == "failed", \
            "G81 run must fail: %s" % mock.states_for(911)
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == "911"
               and r["body"]["state"] == "failed"][-1]
        msg = rep.get("error", {}).get("message", "")
        assert "unsupported" in msg and "G81" in msg, msg
        assert not any(n.endswith(".nc") for n in mock.file_names(911))
        assert not list(programs.glob("O4502*"))

    def test_check_program_unknown_tool_number_fails_fast(self, live):
        mock, _, _ = live
        mock.enqueue_run(912, action=catalog_mod.CHECK_ACTION,
                         inputs=dict(CHECK_INPUTS, model=model_input(mock),
                                    program=program_input(mock),
                                    tool_number=99))
        final = mock.wait_terminal(912, timeout=120)
        assert final == "failed", mock.states_for(912)
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == "912"
               and r["body"]["state"] == "failed"][-1]
        assert "x7_tools.json" in rep.get("error", {}).get("message", "")
        assert mock.file_names(912) == []


def test_check_program_tool_number_mismatch_refused(tmp_path):
    """A tool_number override that disagrees with the program's T word
    must fail, never judge with a different tool."""
    import runner as runner_mod
    prog = tmp_path / "p.nc"
    prog.write_text("%\nO1\nT20 M06\nG0 X0. Y0. Z10.\nM30\n%\n")
    eng = runner_mod.EngineRun.__new__(runner_mod.EngineRun)
    eng.cfg = {"repo_root": REPO, "engine_python": sys.executable}
    eng.work = str(tmp_path)
    with pytest.raises(runner_mod.EngineError, match="does not match"):
        eng.run_check_program(str(prog), str(tmp_path / "m.step"),
                              {"tool_number": 31, "orientation": "Z+",
                               "stock_xy": 1.0, "stock_top": 1.0,
                               "stock_bottom": 0.0}, None)


# ================= task CPc: check_program judges up to three programs ===

class TestCheckProgramSequenceCatalog:
    def test_optional_program_fields(self):
        a = catalog_mod.get_action(catalog_mod.CHECK_ACTION)
        props = a["inputs"]["properties"]
        assert props["program_2"].get("x-steve") == "program"
        assert props["program_3"].get("x-steve") == "program"
        # plain optional fields: required stays program + model
        assert a["inputs"]["required"] == ["program", "model"]

    def test_validate_accepts_program_2_and_3(self):
        ok, code, v = catalog_mod.validate_inputs(
            {"program": {"url": "u"}, "model": {"url": "u"},
             "program_2": {"url": "u"}, "program_3": {"url": "u"}},
            catalog_mod.CHECK_ACTION)
        assert ok, code
        assert v["program_2"] == {"url": "u"}


class TestCheckProgramSequenceE2E:
    def test_two_programs_stock_carries_forward(self, live, tmp_path):
        """rough-like program then a lighter pass: the second is judged on
        the first's stock (--stock-in), and judging it alone from raw stock
        gives a different leftover. Each program keeps its own tool, and
        every program field is downloaded to its own file."""
        mock, home, programs = live
        mock.enqueue_run(913, action=catalog_mod.CHECK_ACTION,
                         inputs=dict(CHECK_INPUTS, model=model_input(mock),
                                    program=program_input(mock,
                                                       "check_rough.nc"),
                                    program_2=program_input(mock,
                                                         "check_light.nc")))
        assert mock.wait_state(913, "received", 30), \
            "run never received: %s" % mock.states_for(913)
        final = mock.wait_terminal(913, timeout=900)
        assert final == "succeeded", \
            "run ended %s: %s" % (final, mock.states_for(913))
        reps = {r["body"]["state"]: r["body"] for r in mock.reports
                if str(r["run_id"]) == "913"}
        result = reps["succeeded"].get("result") or {}
        # judged in order, each program with its own tool from its own T
        assert [p["name"] for p in result["programs"]] == \
            ["program", "program_2"]
        assert result["programs"][0]["tool_number"] == 13
        assert result["programs"][1]["tool_number"] == 20
        # top-level keys unchanged for single-program callers: first program
        assert result["tool"]["number"] == 13
        assert result["strict"] is True and result["unsupported"] == []

        run_dir = home / "runs" / "913"
        # download loop: each program field saved to its own file, never
        # overwriting another input; the model stays input.step
        for dest, src in (("program.nc", "check_rough.nc"),
                          ("program_2.nc", "check_light.nc")):
            with open(os.path.join(HERE, "testdata", src), "rb") as fh:
                want = fh.read()
            with open(run_dir / dest, "rb") as fh:
                assert fh.read() == want, dest
        assert (run_dir / "input.step").stat().st_size > 0

        with open(run_dir / "check.json") as fh:
            cj = json.load(fh)
        assert [e["name"] for e in cj["programs"]] == ["program",
                                                        "program_2"]
        e1, e2 = cj["programs"][0], cj["programs"][1]
        assert e1["tool"]["number"] == 13 and e1["tool"]["holder"] == \
            "BT30-ER32-70"
        assert e2["tool"]["number"] == 20 and e2["tool"]["holder"] == \
            "BT30-ER20-60"
        # the second program was judged on the first program's stock-out
        assert e2["check"]["stock_in"] and \
            e2["check"]["stock_in"].endswith("stock_after_program.npy")
        assert abs(e2["check"]["stock_box"][5] - 12.1) < 0.05, \
            "second program must start from the roughed stock top (12.1)"
        assert e2["check"]["gouges"]["count"] == 0
        assert e2["check"]["rapid_collisions"]["count"] == 0
        assert e2["check"]["holder_hits"]["count"] == 0

        # judging program_2 alone from raw stock gives a DIFFERENT answer:
        # rerun the same zmap from the full stock box and compare leftover
        stock = e1["check"]["stock_box"]
        solo = tmp_path / "solo.json"
        subprocess.run([PY, "-m", "verify.zmap", str(run_dir /
                                                     "program_2.nc"),
                        "--part", str(run_dir / "part_hf_zmap.npy"),
                        "--tool", "ball", "--dia", "9.525",
                        "--corner", "4.7625",
                        "--stock", *[("%.4f" % v) for v in stock],
                        "--flute", "22.225", "--shank-dia", "9.525",
                        "--tool-number", "20", "--strict", "--engage-report",
                        "--out-json", str(solo)],
                       cwd=REPO, check=True)
        with open(solo) as fh:
            solo = json.load(fh)
        assert abs(solo["leftover"]["p95"] - e2["check"]["leftover"]
                   ["p95"]) > 0.05
        assert abs(solo["leftover"]["mean"] - e2["check"]["leftover"]
                   ["mean"]) > 0.01

        # no .nc upload, nothing to the programs folder
        assert mock.file_names(913) == ["check.json", "preview.png"]
        assert not list(programs.glob("O4510*"))
        assert not list(programs.glob("O4511*"))

    def test_failing_second_program_names_program_2(self, live):
        """The first failing program fails the run and is named: a
        gouging program_2 after a clean program must fail with program_2
        in the error."""
        mock, _, programs = live
        mock.enqueue_run(914, action=catalog_mod.CHECK_ACTION,
                         inputs=dict(CHECK_INPUTS, model=model_input(mock),
                                    program=program_input(mock),
                                    program_2=program_input(mock,
                                                         "check_gouge.nc")))
        assert mock.wait_state(914, "received", 30)
        final = mock.wait_terminal(914, timeout=900)
        assert final == "failed", \
            "gouging program_2 must fail the run: %s" % mock.states_for(914)
        rep = [r["body"] for r in mock.reports
               if str(r["run_id"]) == "914"
               and r["body"]["state"] == "failed"][-1]
        msg = rep.get("error", {}).get("message", "")
        assert "program_2" in msg, msg
        assert not any(n.endswith(".nc") for n in mock.file_names(914))
        assert not list(programs.glob("O4501*"))


# ============================================ task SX: per-axis stock ========

class TestPerAxisStockCatalog:
    """catalog: optional stock_x / stock_y (number, minimum 0) on all three
    actions; accepts >= 0, rejects negative."""

    def test_present_on_all_actions(self):
        for act in catalog_mod.ACTIONS:
            p = catalog_mod.get_action(act)["inputs"]["properties"]
            assert "stock_x" in p and "stock_y" in p, act
            assert p["stock_x"]["type"] == "number" and \
                p["stock_y"]["type"] == "number", act
            assert p["stock_x"]["minimum"] == 0 and \
                p["stock_y"]["minimum"] == 0, act
            assert "default" not in p["stock_x"], \
                "stock_x must be optional (no default)"
            assert "default" not in p["stock_y"], \
                "stock_y must be optional (no default)"
            assert "X" in p["stock_x"]["description"]
            assert "Y" in p["stock_y"]["description"]

    def test_accepts_per_axis(self):
        ok, code, v = catalog_mod.validate_inputs(
            {"model": "m", "stock_xy": 1.0, "stock_x": 2.286,
             "stock_y": 12.7}, catalog_mod.ACTION)
        assert ok, code
        assert v["stock_x"] == 2.286 and v["stock_y"] == 12.7

    def test_rejects_negative(self):
        for bad in ("stock_x", "stock_y"):
            ok, code, _ = catalog_mod.validate_inputs(
                {"model": "m", bad: -0.1}, catalog_mod.ACTION)
            assert not ok and code == "input_out_of_range", (bad, code)


class TestPerAxisStockRunner:
    """runner: passes --stock-x/--stock-y to prepare only when given, and
    every judge heightfield STOCK_BOX reflects the resulting per-axis box."""

    BBOX = [-10.0, 10.0, -20.0, 20.0, -1.0, 0.4]

    def _fake(self):
        import hashlib

        import numpy as np
        sys.path.insert(0, REPO)
        from engine.cli import stock_box

        rec = {"calls": [], "envs": []}
        bbox = self.BBOX

        def fake_spawn(self, argv, lo, hi, on_progress, json_out=None,
                       extra_env=None):
            a = list(argv)
            rec["calls"].append(a)
            if extra_env:
                rec["envs"].append(dict(extra_env))

            def opt(flag):
                return a[a.index(flag) + 1] if flag in a else None

            if "engine.cli" in a:
                sub = a[a.index("engine.cli") + 1]
                if sub == "prepare":
                    step_out = os.path.join(self.work, "o.step")
                    with open(step_out, "w") as fh:
                        fh.write("ISO-10303-21; fake oriented step\nEND;")
                    sx = float(opt("--stock-x")) \
                        if opt("--stock-x") is not None else \
                        float(opt("--stock-xy"))
                    sy = float(opt("--stock-y")) \
                        if opt("--stock-y") is not None else \
                        float(opt("--stock-xy"))
                    box = stock_box(bbox, sx, sy,
                                    float(opt("--stock-top")),
                                    float(opt("--stock-bottom")))
                    with open(os.path.join(self.work, "prepare.json"),
                             "w") as fh:
                        json.dump({"step": step_out,
                                   "hf": os.path.join(self.work, "hf.npz"),
                                   "stock": box}, fh)
                else:  # rough / post
                    out = opt("--out")
                    if out:
                        with open(out, "w") as fh:
                            fh.write("G21 G90\nG0 X0. Y0. Z5.\n")
                    sj = opt("--stats-json")
                    if sj:
                        with open(sj, "w") as fh:
                            json.dump({"levels": [{"skipped": False}],
                                       "n_moves": 10}, fh)
            elif any(tok.endswith("heightfield.py") for tok in a):
                np.save(extra_env["HF_OUT"], np.full((8, 8), 0.4))
                with open(os.path.splitext(extra_env["HF_OUT"])[0] + ".json",
                          "w") as fh:
                    json.dump({"step_sha256": hashlib.sha256(
                        open(extra_env["STEP_IN"], "rb").read()).hexdigest(),
                        "cell": float(extra_env["CELL"]),
                        "tess_tol": float(extra_env.get("TESS_TOL", 0.01))},
                        fh)
            elif "verify.zmap" in a:
                with open(opt("--out-json"), "w") as fh:
                    json.dump({
                        "gouges": {"count": 0, "max_depth": 0.0},
                        "rapid_collisions": {"count": 0, "first_line": None},
                        "outside_grid": {"count": 0},
                        "over_flute": {"count": 0, "max_depth": 0.0},
                        "holder": {"status": "checked"},
                        "holder_hits": {"count": 0, "max_intrusion": 0.0},
                        "leftover": {"mean": 0.0, "p95": 0.0, "max": 0.0},
                        "within_0p5mm_fraction": 1.0,
                        "cycle_time_s": 1.0,
                        "cutting_length_mm": 1.0,
                        "rapid_length_mm": 1.0,
                    }, fh)
            return None

        return fake_spawn, rec

    def _prepare_call(self, rec):
        return next(a for a in rec["calls"]
                    if "engine.cli" in a and "prepare" in a)

    def test_passes_flags_only_when_given(self, tmp_path, monkeypatch):
        import runner as runner_mod
        fake, rec = self._fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                                    str(tmp_path))
        values = dict(GOOD_INPUTS)
        values.update({"stock_xy": 1.0, "stock_x": 2.286, "stock_y": 12.7})
        run.run(os.path.join(HERE, "unused.step"), values)

        prep = self._prepare_call(rec)
        assert "--stock-x" in prep and "--stock-y" in prep
        assert float(prep[prep.index("--stock-x") + 1]) == \
            pytest.approx(2.286)
        assert float(prep[prep.index("--stock-y") + 1]) == \
            pytest.approx(12.7)

    def test_judge_heightfield_stock_box_is_per_axis(self, tmp_path,
                                                      monkeypatch):
        import runner as runner_mod
        fake, rec = self._fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                                    str(tmp_path))
        values = dict(GOOD_INPUTS)
        values.update({"stock_xy": 1.0, "stock_x": 2.286, "stock_y": 12.7})
        run.run(os.path.join(HERE, "unused.step"), values)

        boxes = [e["STOCK_BOX"] for e in rec["envs"] if "STOCK_BOX" in e]
        assert boxes, "no judge heightfield STOCK_BOX env was set"
        want = "-12.2860 12.2860 -32.7000 32.7000"
        for b in boxes:
            assert b == want, b

    def test_absent_flags_use_xy_only(self, tmp_path, monkeypatch):
        import runner as runner_mod
        fake, rec = self._fake()
        monkeypatch.setattr(runner_mod.EngineRun, "_spawn", fake)
        run = runner_mod.EngineRun({"engine_python": PY, "repo_root": REPO},
                                    str(tmp_path))
        values = dict(GOOD_INPUTS)
        values["stock_xy"] = 1.0
        run.run(os.path.join(HERE, "unused.step"), values)

        prep = self._prepare_call(rec)
        assert "--stock-x" not in prep and "--stock-y" not in prep
        boxes = [e["STOCK_BOX"] for e in rec["envs"] if "STOCK_BOX" in e]
        want = "-11.0000 11.0000 -21.0000 21.0000"
        for b in boxes:
            assert b == want, b


def test_token_refresh_near_expiry_does_not_recurse():
    """Regression: once the token was within 60 s of expiry, get_token ->
    _request -> _maybe_refresh -> get_token recursed until RecursionError,
    killing the connector ~12 min into any long run."""
    import client as client_mod
    sent = []

    class Stub(client_mod.SteveClient):
        def _send(self, req):
            sent.append(req.full_url)
            if req.full_url.endswith("/token"):
                return {"token": "tok-new", "expires_in": 900}
            return {"messages": []}

    c = Stub("http://127.0.0.1:1/connect/v1", crypto.new_key())
    c.token, c.token_exp = "tok-old", time.time() - 1   # already stale
    c.messages(0, wait=0)
    assert c.token == "tok-new"
    assert [u.rsplit("/", 1)[-1].split("?")[0] for u in sent] == \
        ["token", "messages"]
