# STEVE toolpath actions: request and toolpath.json schema

Source: https://stevecad.studio/docs/developers/connectors/ , section "Toolpath actions", fetched 2026-11-04.
Paraphrased field-by-field; JSON examples are copied from the page. Where the page names a field but not its
nested shape, this file says **unspecified** - do not invent it, read it off a real request (TP1b).

## Catalog: action-level `x-steve.toolpath`

```json
{
  "name": "trochoidal_slot",
  "title": "Trochoidal slotting",
  "inputs": {"type": "object", "properties": {
    "stepover_pct": {"type": "number", "minimum": 5, "maximum": 40, "default": 15, "title": "Stepover (% of the cutter)"}}},
  "x-steve": {"toolpath": {"title": "Trochoidal slot",
    "description": "Slots with constant engagement, from my own CAM engine.", "cutters": ["flat"]}}
}
```

- `title` <= 80 chars (defaults to the action title); `description` <= 1000 chars. Too long is refused, not cut.
- `cutters`: non-empty subset of `flat`, `ball`, `bull_nose` (`bull_nose` declarable, not offered yet).
- Inputs are plain values only: no `x-steve` inputs; no input named `part`, `setup`, `tool`, `stock`, `request`,
  or `steve_*`.
- `toolpath` is the only allowed action-level `x-steve` key, else `catalog_invalid`.
- Never run standalone: app/API/agent/panel runs -> `409 toolpath_generate_only`.
- Becoming a toolpath action or changing its cutters removes its permission until re-allowed (steve-connectors skill).

## Run inputs

| input | contents |
|---|---|
| `part` | STEP file of the linked part at the program's revision (one-time download, file input) |
| `stock` | only when an earlier op cut material: `stock.glb`, work frame (below) |
| `request` | the `ToolpathRequest` |
| `steve_request_sha256` | request fingerprint; must be echoed in `toolpath.json` |
| own inputs | the op's settings; also in `request.settings` |

Nothing else (no credentials/tokens/other docs). Setup must have **box stock**.

## `ToolpathRequest`

Lengths mm, positions in the setup's **work frame**. Named fields:

- `action`, `settings`
- the part's pin (field name **unspecified**), the operation id (field name **unspecified**)
- `setup`: `stock_mm`, `work_offset`, `model_to_work`, `work_to_machine` (shapes **unspecified**; transforms
  presumably 4x4)
- `tool`: `assembly_sha256`, `cutter_type`, tool and holder `geometry` (shape **unspecified**)
- `predecessor_stock_sha256`: `null` for a setup's first op, else id of the stock the previous op left
- `limits`: spindle, feed, plunge, machine fastest feed, top, bottom, clearance, tolerance (key names **unspecified**)
- `start_tip_mm`, `retract_z_mm`, `margin_box`, `tip_envelope`, `posts_arcs`

First op cuts the blank `setup.stock_mm`. Later op: generatable once the program has run up to it;
`stock_mm` and `margin_box` still describe the blank. Ignoring `stock` is allowed.

## `stock` input (`stock.glb`)

File-input fields plus: `format: "glb"`, `name: "stock.glb"`, `sha256`, `bytes` (check as any file input),
`snapshot_sha256` (== `request.predecessor_stock_sha256`; not the file hash), `frame: "work"`, `units: "m"`,
`bounds_mm: {"minimum_mm", "maximum_mm"}` or `null` (no material, no triangles), `cell_mm`.

- Z up; no Y-up conversion. Apply node `translation`s.
- Staircase voxel surface at `cell_mm`; bounds may exceed blank by one cell.
- Nodes `definite_material` and `uncertain_material`: treat both as material.
- <= 1,000,000 faces. Fingerprint excludes the file; staleness keyed on `predecessor_stock_sha256`.

## Output: `toolpath.json`

`PUT /connect/v1/runs/{id}/files/toolpath.json`, then report `succeeded`.

```json
{"format": "steve_connector_toolpath", "version": 1, "units": "mm", "coordinate_space": "work",
 "request_sha256": "<steve_request_sha256>",
 "moves": [{"kind": "rapid", "end_mm": [10, 10, 5]},
           {"kind": "feed", "end_mm": [10, 10, -1], "feed_mm_min": 300},
           {"kind": "arc", "end_mm": [30, 10, -1], "center_mm": [25, 10], "direction": "cw", "turns": 0, "feed_mm_min": 800},
           {"kind": "rapid", "end_mm": [30, 10, 20]}]}
```

- Moves are tool-**tip** positions, work frame, starting at `start_tip_mm`.
- `arc` only when `posts_arcs` is true (`direction` values beyond `cw` - presumably `ccw` - not listed).
- Every move inside `tip_envelope` and `margin_box`; feeds <= op feed and <= machine max; a straight plunge
  <= plunge feed; last move ends at Z >= `retract_z_mm`.
- <= 50 MB, <= 200,000 moves, strict UTF-8 JSON, **no extra fields**.
- Refused -> run `failed`, `toolpath_refused` names field/move/limit. `succeeded` without the file is refused too.
- Posted coordinates are rounded: keep one control resolution step inside each limit.
- Stale when part revision, stock, tool, settings or limits change.

## The real request (TP1b, confirmed 2026-11-04)

STEVE's first live request is kept as `connector/testdata/steve_toolpath_request.json` (run
run_2574c56fce3257b62d26, CAMBuddy test block, T13 flat). What it showed, against the TP1 guesses:

| field | real shape | TP1 guess |
|---|---|---|
| top level | `format: "steve_connector_toolpath"`, `version: 1`, `action` (the action **id**, `act_…`), `operation` (op id), `design` `{program_id, revision, branch, revision_sha256}`, `settings` | `part`, `operation_id`: wrong names |
| `setup.stock_mm`, `margin_box`, `tip_envelope` | `{minimum_mm, maximum_mm}` | right |
| `setup.model_to_work`, `work_to_machine` | frames `{x, y, z, origin_mm}` | not read |
| `tool.cutter_type` | `"flat_end_mill"` | `"flat"`: wrong (first run refused the tool) |
| `tool.geometry` | `cutter_diameter_mm`, `stickout_mm`, `gauge_length_mm`, `engagement_mm`, `max_rpm`, `regions[]` (each `{role: cutter/shank/holder, segment: {shape: frustum, z_start_mm, z_end_mm, radius_start_mm, radius_end_mm, corner_radius_mm}}`, z from the tip) | `geometry.tool.*` / `geometry.holder.segments`: wrong |
| `limits` | `spindle_rpm, feed_mm_min, plunge_mm_min, maximum_feed_mm_min, top_mm, bottom_mm, clearance_mm, tolerance_mm` | `machine_max_feed_mm_min`: wrong |
| `start_tip_mm` | machine home in the work frame, e.g. `[-200, -150, 78.4]`, **outside `margin_box`** at its top Z | inside the box |
| `request` input | a JSON value | right |
| `steve_request_sha256` | sha256 of the request as canonical JSON (sorted keys, no spaces, UTF-8) - verified on the real request | unknown |
| `stock` input | file input `stock.glb`, `cell_mm: 1.0`, `bounds_mm`, `snapshot_sha256` = `predecessor_stock_sha256`; 5.4 MB for the faced test block | right |

Reader mapping (`parse_request`): diameter = `cutter_diameter_mm`; flute = top of the `cutter` region;
shank = 2 x `shank` radius; holder outline = `holder` regions shifted down by `stickout_mm` (our
`[z_lo, z_hi, r_lo, r_hi]` above the nose); a `cutter` region with a corner radius is refused.
The first move leaves `start_tip_mm` over the first point at `retract_z_mm` (inside the box): the
start height can equal the box top, which is not one step inside.
