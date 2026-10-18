# Task K (connector follow-ups, small). Same rules as Task J (no MCP, no questions, no commit, never contact
stevecad.studio, probes in connector/probe_*.py). Run /opt/homebrew/bin/python3 -m pytest connector -q at the end.
1. Timestamps: issued_at/expires_at format is not specified. Accept numeric Unix seconds (int or float) OR an
   ISO 8601 string with Z or an offset (datetime.fromisoformat after replacing a trailing "Z" with "+00:00").
   Reject anything unparseable and naive times without a zone (run rejected, error code e.g. envelope_bad_time).
   Tests: numeric, ISO with Z, ISO with offset, naive ISO (rejected), garbage (rejected), expired ISO (rejected).
2. STEVE keys (supervisor found a bug): crypto.verify_signed_list requires signatures[].kid == fingerprint(pub).
   STEVE's kid is its own key id from the list (any string), NOT our fingerprint format. Change it to take
   (trusted: {kid: public_key_b64}, signed) and accept iff some signature entry's kid is in trusted and verifies
   (Ed25519 over canonical JSON of signed["list"]) with that kid's key. Use it in refresh_steve_keys. Also at enroll:
   pin steve_keys["list"]["keys"] but require that the enroll list carries at least one valid signature by a key
   in that same list (self-consistency); else fail enrollment with a clear error. Make the mock use non-fingerprint
   kids (e.g. "steve-2026-a"). Tests: rotation signed by a trusted kid -> accepted; signed only by an untrusted/new
   key -> rejected (old keys kept); tampered list -> rejected.
3. Persisted token: the token is saved in the state file. Keep it only in memory (re-fetch on start); confirm no
   token, key or signature is written to logs or state files (grep the state dir in a test).
