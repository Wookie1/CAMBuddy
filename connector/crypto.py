"""All connector crypto in ONE small module.

Ed25519 via `cryptography`; sha256/base64/json/secrets from stdlib.
Implements the STEVE connect protocol signing (docs/steve_connector_protocol.md):
RFC 9421 HTTP message signatures with Content-Digest (RFC 9530).

Never logs tokens, keys or signatures.
"""
import base64
import hashlib
import json
import os
import secrets
import stat
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.exceptions import InvalidSignature

ALG = "ed25519"
TAG = "steve-connect-v1"
LABEL = "steve"
COMPONENTS = ('("@method" "@path" "@query" "content-digest")')


# ---------------------------------------------------------------- base64 ----

def b64(raw: bytes) -> str:
    """Standard padded base64 (digests, signatures, public keys)."""
    return base64.b64encode(raw).decode("ascii")


def b64_nopad(raw: bytes) -> str:
    """Unpadded base64 (fingerprints)."""
    return base64.b64encode(raw).decode("ascii").rstrip("=")


def unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.b64decode(text + pad)


# ----------------------------------------------------------------- keys -----

def new_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_raw(sk_or_pk) -> bytes:
    """Raw 32-byte Ed25519 public key."""
    if isinstance(sk_or_pk, Ed25519PrivateKey):
        sk_or_pk = sk_or_pk.public_key()
    return sk_or_pk.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)


def fingerprint(raw_pub: bytes) -> str:
    """'SHA256:' + unpadded base64(sha256(raw 32-byte public key))."""
    return "SHA256:" + b64_nopad(hashlib.sha256(raw_pub).digest())


def load_or_create_key(path: str):
    """Load the connector Ed25519 key from `path` (base64 seed), or create
    it with mode 0600. Never in the repo; caller decides location."""
    if os.path.exists(path):
        with open(path) as fh:
            seed = unb64(fh.read().strip())
        return Ed25519PrivateKey.from_private_bytes(seed)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sk = new_key()
    seed = sk.private_bytes_raw()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(b64(seed) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return sk


def public_key_from_raw(raw: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(raw)


# ------------------------------------------------------- canonical JSON ----

def canonical_json(obj) -> bytes:
    """JSON with keys sorted, no spaces, ensure_ascii False, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")


# ------------------------------------------------------------ signing -----

def content_digest(body: bytes) -> str:
    """RFC 9530 Content-Digest header value; an empty body is hashed too."""
    return "sha-256=:%s:" % b64(hashlib.sha256(body or b"").digest())


def make_nonce() -> str:
    """Fresh 16-64 random characters, unique per request (retries too)."""
    return secrets.token_urlsafe(24)  # 32 chars, URL-safe alphabet


def normalize_query(query: str) -> str:
    """'@query' is the query with its '?'; just '?' when there is none."""
    if not query:
        return "?"
    return query if query.startswith("?") else "?" + query


def signature_params(created: int, nonce: str, keyid: str) -> str:
    return ("%s;created=%d;nonce=\"%s\";keyid=\"%s\";alg=\"%s\";tag=\"%s\""
            % (COMPONENTS, created, nonce, keyid, ALG, TAG))


def signature_base(method: str, path: str, query: str, digest: str,
                  created: int, nonce: str, keyid: str) -> bytes:
    """The five lines joined by \\n, no trailing newline (UTF-8)."""
    params = signature_params(created, nonce, keyid)
    lines = [
        '"@method": %s' % method.upper(),
        '"@path": %s' % path,
        '"@query": %s' % normalize_query(query),
        '"content-digest": %s' % digest,
        '"@signature-params": %s' % params,
    ]
    return "\n".join(lines).encode("utf-8")


def sign_request(sk: Ed25519PrivateKey, method: str, path: str, query: str,
                 body: bytes = b"", created: int = None, nonce: str = None):
    """Return the headers for a signed request: Content-Digest,
    Signature-Input, Signature. Caller adds Authorization."""
    body = body or b""
    digest = content_digest(body)
    keyid = fingerprint(public_raw(sk))
    if created is None:
        created = int(time.time())
    if nonce is None:
        nonce = make_nonce()
    base = signature_base(method, path, query, digest, created, nonce, keyid)
    params = signature_params(created, nonce, keyid)
    sig = sk.sign(base)
    return {
        "Content-Digest": digest,
        "Signature-Input": "%s=%s" % (LABEL, params),
        "Signature": "%s=:%s:" % (LABEL, b64(sig)),
    }


def verify_signature(raw_pub: bytes, message: bytes, sig_b64: str) -> bool:
    try:
        public_key_from_raw(raw_pub).verify(unb64(sig_b64), message)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


def verify_envelope(raw_pub: bytes, envelope: dict, sig_b64: str) -> bool:
    """STEVE's signature over the envelope in canonical JSON form."""
    return verify_signature(raw_pub, canonical_json(envelope), sig_b64)


def verify_signed_list(raw_pub: bytes, signed: dict) -> bool:
    """Verify a {"list": {...}, "signatures": [...]} structure (keys lists):
    at least one signature by `raw_pub` over the canonical form of `list`."""
    if not isinstance(signed, dict) or "list" not in signed:
        return False
    want = fingerprint(raw_pub)
    for entry in signed.get("signatures", []):
        if entry.get("kid") == want and verify_signature(
                raw_pub, canonical_json(signed["list"]), entry.get("sig", "")):
            return True
    return False


def sign_keys_list(sk: Ed25519PrivateKey, keys: list) -> dict:
    """Build {"list": {"keys": [...]}, "signatures": [...]} for our mock."""
    listing = {"keys": keys}
    return {"list": listing,
            "signatures": [{"kid": fingerprint(public_raw(sk)),
                           "sig": b64(sk.sign(canonical_json(listing)))}]}
