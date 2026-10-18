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
    "tool_diameter": 6.0, "corner_radius": 0.0, "flute_length": 30.0,
    "stepdown": 4.0, "optimal_load": 2.0, "stock_to_leave": 0.381,
    "rest_stepup": 1.905, "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 1, "units": "mm", "program_number": 1001,
}

# slope_split_finish: finishing ball 6 (tool_number given - the X7 table has
# no ball), roughing with a flat 6 (the engine's bull 12.7 skips every level
# on this small pocketed block and crashes: engine-track bug, see TASK_M).
# floor_z 5.0 -> floor = stock zmin (-1.0) + 5.0 = 4.0 = the pocket floor.
SLOPE_GOOD_INPUTS = {
    "orientation": "as_modeled", "stock_xy": 1.0, "stock_top": 0.4,
    "stock_bottom": 1.0, "floor_z": 5.0, "tool_diameter": 6.0,
    "stepover": 0.3, "stepdown": 0.3, "slope_threshold": 40.0,
    "rpm": 7500, "feed": 3429.0, "ramp_feed": 1270.0,
    "tool_number": 5, "units": "mm", "program_number": 1002,
    "rough_tool_type": "flat", "rough_tool_diameter": 6.0,
    "rough_corner_radius": 0.0, "rough_flute_length": 30.0,
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
        inputs = dict(SLOPE_GOOD_INPUTS, model=model_input(mock))
        del inputs["tool_number"]  # a 6 mm ball is not in the X7 table
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

def test_zz_print_e2e_result(live):
    mock, _, _ = live
    print("\n==== end-to-end run result JSON ====")
    print(json.dumps(E2E.get("result", {}), indent=2))
    print("==== states:", mock.states_for(501), "====")

