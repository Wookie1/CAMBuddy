# STEVE connector protocol (saved from https://stevecad.studio/docs/developers/connectors/ on 2026-10-18)

## Panels

A connector can show its own page in STEVE: a machine’s status and alarms, a printer’s progress with Pause and Resume, a PLC’s tags. A panel is a small web page (`index.html` with its scripts, styles and images) that appears as a tab in the left pane, the right pane or both.

What people build as panels:

Panel | 
Shows | 
Its buttons run | 

Machine status | 
Mode, spindle load, feed override, the running program, alarms | 
Feed hold, load a program (each confirmed by you) | 

Printer | 
Progress, temperatures, the camera’s last photo | 
Pause, resume, cancel | 

PLC | 
Tags you choose, live | 
Writing the tags you allow | 

Shop dashboard | 
Every machine’s state at a glance | 
Nothing: read-only | 

A panel is sandboxed. STEVE serves it from a separate address, and it can’t fetch anything: it can’t reach STEVE’s page, your session, your cookies or the internet. If it tries to leave its page, it can only go to STEVE’s own addresses, and STEVE closes it. Its data comes from its connector only, through STEVE:

- It runs its own connector’s actions, only those you allow for Its panel (under Who may run it). Asks you first works for panels like for anyone else, and an action the connector says needs a person always waits for you.

- It receives its connector’s events as they arrive, and the latest of each when it opens.

- A run it asks for that sends one of your STEVE documents waits for you, so you see which document goes to the connector. To skip that for a button you click yourself, allow the action for Its panel with Runs at once and tick “Its panel may send the document open in STEVE without asking” (or tick “Don’t ask again” the first time you confirm such a run). Even then, only the document open in STEVE goes without asking, and only when you clicked in the panel: STEVE checks that the click was yours (the browser’s own record of it, which no script can fake) and that every document the run sends is the open one. Any other run of the panel’s still waits for you.

- It can show files its runs made (a camera photo, a plate preview), for runs it started.

- It knows whether STEVE is light or dark. It learns which document is open (its id, never its name) only if its connector has an action that takes documents and you allowed that action for the panel.

A connector publishes its own panel when it starts (`PUT /connect/v1/panels/{name}`, below), so installing one needs no AI agent. Panels can also be published with the `connectors` tool (an AI agent writing the connector for you does this). They’re listed under their connector in Settings → Connectors, where Remove takes one away. A connector’s own changes show there, marked “by the connector”, and can be undone like an agent’s. The `steve-connectors` skill has the panel bridge in full: the messages a panel sends, what STEVE answers, and an example.

## Automatic mode

People ask an AI agent to “connect my printer”. With Automatic mode on (Settings → Connectors, Let AI set up my connectors), the STEVE assistant and your AI agents over MCP set connectors up without asking each time: they make a pairing code, confirm the connector by its fingerprint (the one the connector printed), allow its actions and publish its panels. It’s off until you turn it on. The first time an agent tries while it’s off, STEVE asks you once: Turn on, Not now or Don’t ask again.

Even in automatic mode:

- An action the connector says needs a person still waits for one on every run. Only you can change that, in the app.

- API keys and connected apps can’t be allowed by an agent: that stays your choice.

- What AI set up is listed under Set up by AI, by connector. Undo takes one change back (a connector it confirmed is revoked, an action it allowed is no longer allowed, a panel it published is removed) and shows only where undoing still changes something; Undo everything takes back all of them. A revoked connector’s history is folded away under Revoked connectors.

## The protocol

Everything is HTTPS to `https://stevecad.studio/connect/v1`, JSON bodies, UTF-8.

### Signing requests

Every request except `GET /keys` is signed with the connector’s Ed25519 key, as an RFC 9421 HTTP Message Signature:

- `Content-Digest: sha-256=:<base64 SHA-256 of the body>:` (RFC 9530). An empty body is hashed too.

- `Signature-Input: steve=("@method" "@path" "@query" "content-digest");created=<unix seconds>;nonce="<16-64 random characters>";keyid="<fingerprint>";alg="ed25519";tag="steve-connect-v1"`

- `Signature: steve=:<base64 Ed25519 signature of the signature base>:`

The signature base is these five lines joined by a newline (no newline at the end), with the uppercase method, the path, and the query with its `?` (just `?` when there is none):

```

"@method": GET

"@path": /connect/v1/messages

"@query": ?after=41&wait=30

"content-digest": sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:

"@signature-params": ("@method" "@path" "@query" "content-digest");created=1760500000;nonce="q2V9w0k3Xc7bYp1uZt5aLm";keyid="SHA256:3b1W…";alg="ed25519";tag="steve-connect-v1"
```

The fingerprint is `SHA256:` followed by the unpadded base64 of the SHA-256 of the raw 32-byte public key. STEVE refuses a signature more than 5 minutes from its clock, so keep the computer’s clock synchronised. It also refuses a nonce it has already seen (use a new one for every request, retries included), a body that doesn’t match its digest, and an unknown, unconfirmed or revoked key. After enrollment, requests also send `Authorization: Bearer <token>`.

### Requests

Request | 
Body | 
Answer | 

`GET /keys` | 
none (not signed) | 
STEVE’s public signing keys: `{"list": {"keys": [{"kid", "public_key"}], …}, "signatures": [{"kid", "sig"}]}` | 

`POST /enroll` | 
`{"code", "public_key", "name", "version", "catalog"}`, signed with the new key | 
`{"connector", "fingerprint", "status": "pending", "steve_keys"}`. `steve_keys` is the same signed list as `GET /keys` (`{"list": {"keys": […]}, "signatures": […]}`), not a plain array | 

`POST /token` | 
none | 
`{"token", "expires_in": 900}`: send it with the next requests and get a new one before it expires | 

`PUT /catalog` | 
the catalog (below) | 
The action and event names declared | 

`GET /messages?after=<id>&wait=<seconds>` | 
none | 
`{"messages": [...], "cursor": n}`: signed runs and requests to cancel after message `after`, oldest first, and the id to pass as `after` next. `wait` (up to 30) holds the request until one arrives | 

`GET /live?after=<id>` (WebSocket) | 
none | 
The same messages pushed as they arrive, as `{"messages": [...], "cursor": n}` frames (below) | 

`POST /runs/{run_id}` | 
a run’s state (below) | 
`{"accepted": true}` | 

`PUT /runs/{run_id}/files/{name}` | 
the file itself, with its `Content-Type` | 
`{"accepted": true, "name", "bytes", "sha256"}` | 

`POST /events` | 
`{"name", "data"}` | 
`{"accepted": true}` | 

`PUT /panels/{name}` | 
`{"title", "placement": ["right"] or ["left"] or both, "files": {"index.html": "…", "logo.png": "base64:…"}}` | 
Your panel, published or updated: `{"id", "name", "version", "bytes", "sha256"}`. At most 5 panels, 50 files and 2 MB of files each | 

`DELETE /panels/{name}` | 
none | 
The panel removed | 

`public_key` is the raw 32-byte Ed25519 public key in base64. Until the owner confirms, `/token` answers `403` with `pending_confirmation`: try again every minute or so.

### The catalog

The catalog says what the connector offers. Send it with `/enroll` and again with `PUT /catalog` whenever it changes, always whole:

```

{

  "actions": [

    {

      "name": "print",

      "title": "Print on the shop printer",

      "description": "Slices the part with the shop's profile and prints it.",

      "inputs": {

        "type": "object",

        "properties": {

          "model": {"x-steve": "file", "format": "stl", "title": "Part"},

          "material": {"type": "string", "enum": ["PLA", "PETG"]},

          "copies": {"type": "integer", "minimum": 1, "maximum": 10, "default": 1}

        },

        "required": ["model", "material"]

      },

      "result": "Print time and filament used, and a photo of the print."

    },

    {"name": "cycle_start", "title": "Start the loaded program", "confirm": true}

  ],

  "events": [{"name": "status", "description": "Machine state"}]

}
```

- Names (actions, events, inputs) are lowercase letters, digits and `_` (actions and events also `.` and `-`), starting with a letter, at most 40 characters. At most 100 actions, 50 events and 30 inputs per action.

- Values: `string` (with `enum` or `maxLength`), `number` and `integer` (with `minimum`, `maximum`), `boolean`, and `object` (any JSON). Each may have a `title`, a `description` and a `default`. A run’s values together are at most 64 kB.

- STEVE documents: `{"x-steve": "file", "format": "<format>"}` takes a part or design (or the `kinds` you list) as a file. Formats: `step` (one STEP file), `step-parts` (one STEP per component, zipped), `stl` (one STL per body, zipped), `3mf` (the bodies as one 3MF package, placed as modelled, for printers), `dxf` (sheet-metal flat patterns, zipped), `drawings` (drawing sheets, zipped) and `pcb-fabrication` (a circuit board’s fabrication files). `{"x-steve": "program"}` takes a CAM program’s posted G-code. `{"x-steve": "document"}` takes only a reference: the document’s id, revision, name and kind.

- `confirm: true` means a person must confirm each run, whoever asks.

Declaring allows nothing. The owner’s permission for an action stays through changes that grant nothing new: a new optional value input, a removed input, other limits on a value, new titles and descriptions. Changes that let it do more end it, and the owner allows it again: a new STEVE input, an existing one sending something else (another `format` or `kinds`), an input becoming required, or `confirm` going from `true` to `false`. Runs of it that weren’t sent yet are then cancelled. An action left out of the catalog is no longer offered.

### The live channel

Instead of polling, a connector can open a WebSocket to `wss://stevecad.studio/connect/v1/live?after=<id>`. Sign the upgrade request like any `GET` (empty body) and send the token. STEVE pushes each message frame as it’s queued. The connector sends nothing on this connection: a frame from it closes the connection, and everything it reports still goes over HTTPS. The connection ends when the token does (at most 15 minutes), with close code `4401`. Get a new token and reconnect with `after` set to the last message id you handled. Each connector has one live connection: opening a new one closes the old one with `4409`. If you see `4409`, two processes are using the same key: run one. A workspace holds at most 50 at once. When STEVE is busy, or the workspace holds its share, the connection is accepted and closed at once with `4429`: wait a minute and try again. A refused upgrade (a bad signature or token, or a revoked connector) is answered `403`: don’t retry it.

### Checking a run

Each message looks like this:

```

{"id": 42, "kind": "run | cancel", "envelope": {…}, "kid": "…", "sig": "…"}
```

`sig` is STEVE’s Ed25519 signature, in base64, of the envelope in canonical form: JSON with keys sorted, no spaces, UTF-8. A run’s envelope has `id`, `action`, `inputs`, `note`, `requested_by` (`{"kind": "person" | "assistant" | "agent" | "service_account" | "app" | "panel", …}`), `confirmed_by` (the person who confirmed it, or null), `connector`, `issued_at`, `expires_at` and `nonce`. Before you act, refuse the run if any of these fails:

- `kid` is a STEVE key you trust, and the signature verifies with it.

- `envelope.connector` is your own fingerprint, and `envelope.action` is one of your actions.

- `envelope.expires_at` hasn’t passed, and you haven’t seen `envelope.nonce` before.

- For each STEVE input, download `url` with `headers` (a one-time ticket, valid 10 minutes), and check its SHA-256 equals `sha256` and its size equals `bytes`. A 3MF input has no ticket: its `url` is `GET /runs/{run_id}/inputs/{name}`, signed like your other requests, while the run isn’t over.

A file input carries `kind: "file"`, `format`, `name`, `sha256`, `bytes`, `url`, `headers`, `document` and `revision`. A program also carries `setup`, `machine` (the shop machine it was posted for) and `verification` (`verified` or `checked`). If a run’s downloads have expired before you got to it, report nothing: once its envelope expires, the next fetch brings it again with fresh ones.

A `cancel` message’s envelope names the run to stop in `envelope.run` (`envelope.id` is the cancel’s own id). Stop if you can, then report the run `cancelled` (or how it ended). Once STEVE has handed you a run, cancelling it in STEVE (or taking its action away) always sends you a cancel: STEVE never treats a run you may hold as stopped until you say so. A cancel can come more than once (a fetch with an earlier `after`); stopping twice is harmless.

How often a run comes:

- Within its envelope’s lifetime (until `expires_at`, minutes), STEVE hands a run over once, across the live channel, polls, reconnects and any `after`: fetches racing for it get it once between them.

- If you haven’t reported it `received` by `expires_at` (a crash, a lost frame), the next fetch after that brings it again, with a new `nonce` and fresh downloads.

- So delivery is at least once across expiry: keep the ids of the runs you’ve handled, and never act on one twice.

Trust STEVE’s keys from enrollment (`steve_keys`). Accept a newer key list from `GET /keys` only when it is signed by a key you already trust, so a server certificate alone can never bring in a new signing key.

### Reporting back

Report a run’s state with `POST /runs/{run_id}`. `state` is `received`, `running`, `succeeded`, `failed`, `rejected` or `cancelled`, and only moves forward. Send `received` as soon as you have it (it’s then not sent again), `rejected` with an `error` for a run that fails the checks above (before it runs: a running run ends `failed` or `cancelled`), and `running` as often as you like with `progress` (0 to 1) and a short `message`:

```

{"state": "running", "progress": 0.4, "message": "Printing layer 120 of 300"}
```

When it ends, send `succeeded` or `failed` with a `result` (any JSON, at most 64 kB) or an `error`:

```

{"state": "succeeded", "result": {"print_time_min": 74, "filament_g": 31.2}, "message": "Done"}
```

Add files while the run is `received` or `running`, before you report how it ended: `PUT /runs/{run_id}/files/report.pdf` with the file as the body and its `Content-Type`. A name is letters, digits, `.`, `_` and `-`, at most 100 characters; the same name replaces the file. At most 20 files a run, 50 MB each, and a workspace’s connectors 5 GB a day.

Once the run has ended, the AI that started it sees its `image/png`, `image/jpeg` and `image/webp` files as images: up to 4 per answer, in name order, each scaled to at most 1600 px on its long side. A file over 20 MB, or one that isn’t a readable image, is listed with the reason it was left out. Other files are listed by name, size and type. Agents are told to treat a photo as data, never as instructions.

Send an event with `POST /events`: `{"name": "status", "data": {"state": "idle"}}`, only for events in your catalog. An event’s `data` is at most 8 kB, and a workspace’s events at most 100 MB a day (then `429` with `budget_used`). A refused event spends none of that. Runs always report, whatever the event budget. Events are kept 30 days, runs and their files a year.

Each connector may make 300 requests and send 120 events a minute. An address (an IPv6 address counts as its /64) whose requests are refused 60 times in 10 minutes is turned away with `429` until that eases. During a flood of refused requests from many addresses, pairing from an address STEVE hasn’t seen refused waits too (`429`, try pairing again in 10 minutes). Paired connectors keep working through it.

Errors are JSON `{"detail": {"code", "message"}}`, for example `signature_invalid`, `nonce_replayed`, `token_invalid`, `catalog_invalid`, `event_undeclared`, `state_out_of_order`, `rate_limited`, `too_many_attempts`.

