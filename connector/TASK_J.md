# Task J (round 9b, track A): STEVE connector v1, roughing only
Read docs/steve_connector_protocol.md (the protocol, authoritative) and docs/steve_panel_bridge.md (panel bridge).
Rules: no MCP, no questions, do not commit, probes in connector/probe_*.py, do not edit engine/finish.py or spike/.
NEVER contact stevecad.studio and never pair: everything is tested against a local mock server.
Python: /opt/homebrew/bin/python3 (3.14, has `cryptography` 46 and tomllib). Do NOT install anything. Keep all
crypto in ONE small module, connector/crypto.py (cryptography's Ed25519; sha256/base64 from stdlib).

## Design
- connector/ is a separate light process (stdlib + cryptography). It shells out to the engine with subprocess
  list args (never shell=True): /Applications/VibeCAD.app/Contents/Resources/bin/python -m engine.cli ...
  with env ENGINE_WORKERS=4, cwd = repo root. Each run gets its own work dir ~/.stevecam/runs/<run_id>/.
- Key file and config live in ~/.stevecam/ (key file mode 0600, config.toml read with tomllib), never in the repo.
  Tests must use a temporary HOME/state dir, never the real ~/.stevecam. Never log tokens, keys or signatures.
- Base URL configurable (default https://stevecad.studio/connect/v1). Ed25519 key; fingerprint = "SHA256:" +
  unpadded base64(sha256(raw 32-byte public key)).
- POST /enroll {code, public_key, name, version, catalog} -> pending; POST /token 403 pending_confirmation until
  confirmed (retry ~60 s), then a 900 s token, refreshed before expiry; Authorization: Bearer after enrollment.
- Every request except GET /keys is RFC 9421 signed exactly as the protocol doc shows: Content-Digest
  (empty body hashed too), Signature-Input with created/nonce (fresh 16-64 chars per request, retries too)/keyid/
  alg/tag, Signature; base = 5 lines joined by \n, no trailing newline, "@query" is "?" when empty.
- Receive by polling GET /messages?after=<cursor>&wait=30 (stdlib urllib only; no websocket). Persist the cursor.
  For each message verify sig (canonical JSON: sort_keys, separators (',',':'), ensure_ascii False, UTF-8) with a
  kid from steve_keys pinned at enroll (accept newer GET /keys lists only if signed by an already-trusted key);
  envelope.connector == our fingerprint; action in our catalog; not expired; nonce unseen. Persistent ledger of
  handled run ids: never act twice. Download file inputs with url+headers; check sha256 and bytes.
  Handle `cancel` messages (stop the subprocess, report cancelled).
- POST /runs/{id}: received at once, running with progress/message, then succeeded/failed with result/error;
  rejected (with error) for runs failing checks. States forward only. PUT /runs/{id}/files/{name} before the final
  state. PUT /panels/{name} at start. POST /events only on change. Errors are {"detail":{code,message}}.

## Catalog v1
Action adaptive_rough, confirm false (never touches the machine). Inputs (each with sane minimum/maximum/default):
model {"x-steve":"file","format":"step"} (required); orientation enum as_modeled|flip_x_180|flip_y_180|flip_z_180;
stock_xy, stock_top, stock_bottom offsets mm (origin = stock bottom centre, as James's Fusion WCS);
tool_type enum flat|bull|ball, tool_diameter, corner_radius, flute_length; stepdown, optimal_load, stock_to_leave,
rest_stepup; rpm, feed, ramp_feed; tool_number (optional, else tools/x7_tools.json); units enum inch|mm default
inch; program_number. Result: JSON summary (estimated time, cut length, zmap gouges, rapid collisions,
over-flute, leftover mean/p95/within_0p5mm). Files: the LNC .nc, check.json (zmap), preview.png (leftover
heightmap; matplotlib is in VibeCAD python). Also copy the .nc to a configured programs folder, default
~/ai-sandbox/stevecam/out/steve/. Orientation + stock offsets need an engine step (orient STEP, derive stock box)
- add what the engine CLI lacks (e.g. `engine.cli prepare`), and make engine.cli emit JSON progress lines
({"progress":0.4,"message":"level 3/7"}) that the connector maps to run progress.
Event engine_state {state idle|busy, action, progress}, sent only on change.

## Panel connector/panel/ (index.html, panel.js, panel.css; bundled, no network)
Bridge on load: context -> events -> actions. Roughing form + "Rough the open document" button that sends
context().document ({document_id, revision}) from the click handler itself; button disabled until the run ends
(incl. awaiting_confirmation, shown plainly). Then progress, then summary + preview.png via run.file
(URL.createObjectURL). Follow context.theme, fit 300-600 px. panel/dev.html = a harness faking the bridge
(posts context/events/actions answers and run pushes) so it can be opened and screenshotted locally.

## Tests (connector/test_connector.py, /opt/homebrew/bin/python3 -m pytest connector -q)
a. Unit: exact signature-base string for a fixed request (match the doc's example layout), empty-body digest
   (sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:), fingerprint format, canonical JSON, Ed25519 against
   RFC 8032 test vector 1 (secret 9d61b19d...7f60, public d75a9801...511a, empty message, signature e5564300...100b).
b. A stdlib mock STEVE server (http.server, threads) that VERIFIES every request's signature/digest/nonce/clock,
   enforces state order, signs envelopes with its own Ed25519 key, and serves a small synthetic STEP (generate
   one with freecadcmd once, or check one into connector/testdata/ if < 50 kB) with its sha256. End to end:
   enroll -> pending -> confirm -> token -> signed run -> download -> rough (real engine) -> received/running/
   progress/succeeded -> files uploaded -> panel published -> events.
c. Negative: bad envelope sig -> rejected, not run; replayed run id -> not run twice; sha mismatch -> failed or
   rejected before running; expired -> rejected; input out of range -> rejected.
Print the test summary and the end-to-end run's result JSON at the end.
