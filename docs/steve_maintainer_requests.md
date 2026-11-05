# Requests to STEVE's maintainer (from SteveCAM, TP1, 2026-11-04)

**Status 2026-11-05:** James submitted these requests and the `artifact_unavailable` bug report (run
1376db35-1181-4abd-b56f-9a4e35221f45) to STEVE's maintainer. R2 was answered by the first live request
before submission: the fingerprint is sha256 of the canonical request JSON (docs/steve_toolpath_actions.md).

These come from building SteveCAM's toolpath action, `adaptive_rough_toolpath`, against the "Toolpath actions" section of the connector docs. Each request covers one feature.

---

## R1. A published schema for `ToolpathRequest`

**What we want:** a JSON Schema for the `request` input, or one complete example request in the docs. It should give every field's nested shape and units. The fields we need most:
- `setup.stock_mm`, `margin_box` and `tip_envelope` (are they `{minimum_mm, maximum_mm}` boxes?);
- the key names inside `limits`, including the machine's fastest feed;
- `tool.geometry`: the cutter's diameter, corner radius, flute length, shank diameter and stick-out, and the holder outline and its reference point;
- the field names for the part pin and the operation id;
- whether `request` arrives as a JSON value or as a file input.

**Why it helps:** today the docs name these fields but not what is inside them, so a connector has to guess and find out on the first live run. A wrong guess means the toolpath run fails, or worse, a field gets read as the wrong limit. With a schema, a connector can validate the request before it starts several minutes of computation. Test servers (our mock STEVE) can also send exactly what STEVE sends.

---

## R2. How `steve_request_sha256` is computed

**What we want:** one sentence in the docs saying how the fingerprint is made. For example: "SHA-256 of the request as canonical JSON (keys sorted, no spaces, UTF-8)", or "opaque: only echo it".

**Why it helps:** if it is canonical JSON, a connector can recompute it and refuse a request that doesn't match, the same way it checks every file's sha256. It can also use the fingerprint as a cache key, so the same request never runs twice. If it is opaque, we know not to try. Today we can only echo it.

---

## R3. A finer stock option for a later operation's `stock.glb`

**What we want:** a way for the connector, or the operation, to ask for the `stock` input at a finer cell than the 1 mm default `verification_cell_mm`. It could be a toolpath-action catalog field such as `"stock_cell_mm": 0.25`, or an operation setting. A 2.5D heightfield form would also serve: the top Z of material per XY cell, as a compact array alongside the mesh.

**Why it helps:** our rest-roughing and finishing engines decide what to cut from leftover stock at 0.1-0.5 mm resolution. They treat 0.5 mm of material above the part as worth a pass. At 1 mm cells, stock thinner than about 1 mm can't be told apart from the cell staircase. We would then either re-cut air or miss real leftover, and the 1,000,000-face cap pushes cells coarser still on larger parts. Most of our engines are 2.5D, so a heightfield would be both smaller than the mesh and exact for them.

---

## R4. A definition of `uncertain_material` in `stock.glb`

**What we want:** the docs to say what puts a cell in `uncertain_material` rather than `definite_material`. For example: a cell the tool only partly swept, or a cell within one cell of a cut boundary. They should also say how thick that band can be.

**Why it helps:** today we must treat uncertain material as solid, so every rest or finish pass plans around the worst case. If we know it is at most one cell on cut boundaries, we can budget for it: start a pass one cell higher, or use a lighter first cut, instead of planning full-depth engagement where there may be none. That makes later operations both safer and faster.

---

## R5. A check-only call for `toolpath.json`

**What we want:** a way to have STEVE check a toolpath file against a run's request without storing it. For example, `POST /connect/v1/runs/{id}/files/toolpath.json:check`, which answers with `toolpath_refused` details or "acceptable" while the run stays `running`.

**Why it helps:** we check our own file against every documented rule before uploading. But STEVE's checks are the ones that count, and any difference between the two only shows up as a failed run, after the full rough has been computed. A check-only answer would let the connector fix what it can (for example, move a retract inside `margin_box`) and upload once, instead of failing the run and making the person generate again.
