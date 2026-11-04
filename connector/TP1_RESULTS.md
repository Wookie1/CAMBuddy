# TP1 results: adaptive_rough_toolpath (mock STEVE only)

Branch `tp1` off main. Nothing published and the live connector was not restarted (TP1b needs James's OK).

## What was built

- `docs/steve_toolpath_actions.md`: the ToolpathRequest / stock.glb / toolpath.json schema from the STEVE connector docs (Toolpath actions section, 2026-11-04), plus the table of GUESSES the reader relies on.
- `connector/toolpath_action.py` (new):
  - the catalog spec: `x-steve.toolpath`, cutters `["flat"]`, value-only settings. The settings are `stepdown_mm` (default 1 x D, refused above the flute length), `optimal_load_mm` (titled "Stepover / optimal load", default 0.16 x D, allowed 0.02-0.5 x D, checked against the request's tool), `stock_to_leave_mm` (default 0.381) and `load_limit` (default true). The settings are mm only; the inch conversion is never applied.
  - the request reader (`parse_request`).
  - a one-tool T1 table built from `request.tool`, so our library is never used.
  - the run, which calls `engine.cli rough` with the neutral G21 post and no prepare/origin logic: the part STEP and every coordinate stay in the request's work frame. The stock is `setup.stock_mm`, the floor is `limits.bottom_mm`, the cut feed is min(op feed, machine max), the ramp feed is min(plunge, cut feed) and the spindle is the op's.
  - the gates, the same as adaptive_rough: zmap gouge / rapid / entry-stock / over-flute / holder / axial (`runner._check_zmap_gates`), plus the rough's own `clcheck_violations`.
  - the G0/G1 -> moves converter. It starts from `start_tip_mm` (rapid over at the start height, then down), clamps a straight plunge to the plunge feed (only ever slower) and closes with a rapid to `retract_z_mm`.
  - the validator `violations()`, which checks every documented toolpath.json rule:
    - format/version/units/space;
    - no extra fields;
    - `request_sha256`;
    - at most 200k moves and 50 MB;
    - every end inside `margin_box` and `tip_envelope` by one 0.001 mm step;
    - feeds at or below min(op, machine);
    - a straight plunge at or below the plunge feed;
    - no arc unless `posts_arcs`;
    - the last move at or above `retract_z_mm`.
  - Any violation fails the run (`toolpath_limit`, naming the field/move/limit) and nothing is uploaded.
- `connector/connector.py`: `_run_toolpath` (download and digest-check `part`, read `request`, validate the settings minus STEVE's inputs, run, then upload ONLY `toolpath.json` and report the result plus the verdict/summary/attention envelope). The existing actions' code paths are unchanged.
- `catalog.py` (the action is registered in `ENGINE_ACTIONS` and the catalog), `errors.py` (4 codes), `envelope.py` (summary noun).
- `engine/cli.py` (+1 line): rough's stats.json now records the load limiter's `{windows_slowed, mm_slowed, min_feed, floor_bound}`, so a run can report `reduced_feed_windows`.
- `mock_steve.py`: `toolpath_inputs()` (part file input, request with `settings`, fingerprint), and the uploaded `toolpath.json` body is kept for the tests to judge.

## Tests: `connector/test_toolpath_action.py` (16 passed, 18.6 s)

- Catalog shape (x-steve block, no reserved names, defaults, published minimums not inch-scaled), tool-relative defaults and ranges, request refusals (ball cutter, missing flute length).
- Validator mutants. Each one passes just inside its limit and fails by a measured amount just outside:
  - margin_box: +0.0005 mm past the inner step;
  - op feed: 3000.1 vs 3000;
  - plunge: 800.1 vs 800;
  - retract: 19.999 vs 20.0;
  - wrong request_sha256;
  - an arc while `posts_arcs` is false;
  - also: an extra field, more than 200k moves, and the converter's plunge clamp and retract.
- Code mutation check (a scratch copy of the connector with each check weakened): every mutant was killed by exactly its own test (margin_box, op_feed, plunge, retract, sha, arcs, converter plunge clamp); the unmutated copy passes 13/13.
- End to end on mock STEVE with `synth_pocket.step`, the 12.686 flat (T13 geometry/holder fed in as request geometry), stepdown 4 and load 2.0:
  - `succeeded`, and `toolpath.json` is the only uploaded file (954,833 bytes, 13,674 moves, lines only).
  - The output is valid against the validator and against independent asserts.
  - Every zmap gate is 0 and clcheck is 0.
  - Estimated 5.51 min, leftover mean 0.676 / p95 0.400 mm.
  - Verdict `needs_review`: max engagement 12.686 mm, 2,538 moves over 1.2 x load. These are the helix entries, the same as an adaptive_rough run on this part.
  - `reduced_feed_windows` was 0.
- Limit-violation run: a margin box topped at 14.0 is below the engine's link plane (14.4), so the run fails `toolpath_limit` (allowed `margin_box`) and nothing is uploaded.
- A bad part digest fails `input_digest_mismatch` and nothing is uploaded.

Full connector suite (once, 22.5 min): 288 passed, 1 skipped, 1 failed - `test_track2::test_f_codes_table_and_guide_in_sync` (docs/agent_guide.md lacked the new error codes). Fixed by regenerating the table (`python3 connector/errors.py`) and dropping an unused code; that test plus the TP1 file re-run green, and the TP1 file re-run green again from a clean detached worktree at the final commit.

## Cannot satisfy / open (needs TP1b or STEVE's maintainer)

1. The nested request shapes are guessed (see the docs table): the tool and holder geometry, the limits key names, the box shapes, how the request input arrives, and how `steve_request_sha256` is computed. One real request settles all of them; only `parse_request()` changes.
2. The engine's own link/rapid plane is stock top + 2 mm. It ignores `clearance_mm`, `retract_z_mm` and the margin-box top, so a tight margin box fails the run rather than being honoured. That is safe, but the engine should take a clearance cap (a small engine change; out of TP1).
3. The engine only clears enclosed stock: an exterior box part posts nothing (`nothing_to_cut`). The STEVE test block needs a face op first, or a part with pockets.
4. Arcs are never emitted. The engine posts lines, so `posts_arcs` is honoured trivially and arc fitting is not used. File size is about 70 bytes per move, so roughly 700k-move parts would hit the 50 MB / 200k-move caps first, at 200k moves.
5. The `stock` GLB is ignored. TP1 is for the first op in a setup only. A later op would rough the blank: safe, but wasteful.
6. `top_mm` is not used. The rough always starts at the stock top (the brief: top = stock top).
7. Only flat cutters are supported, matching the catalog. Bull is refused by STEVE (not offered yet), and the engine cannot rough with a ball.

## What the STEVE GLB stock lacks for our rest/finish engines

- It is a voxel staircase at `cell_mm` (STEVE's `verification_cell_mm`, default 1 mm) and is limited to 1,000,000 faces. Our rest-rough and finish engines work from 0.1-0.5 mm heightfields and a 0.5 mm `min_rest`, so at 1 mm cells, rest decisions under about 1 mm cannot be trusted from it.
- The `uncertain_material` node has to be treated as material, so the stock is an upper bound. Bounds can pass the blank by up to one cell.
- It has no normals, no exact surfaces and no record of which op left what, and no undercut information beyond the mesh itself.
- Asks for the maintainer:
  - offer a finer cell, or a heightfield (Z-max per XY cell) form of the stock for 2.5D engines;
  - state the cell size and what makes material "uncertain";
  - publish the nested ToolpathRequest schema (or a JSON Schema);
  - say how `steve_request_sha256` is computed.

## TP1b (needs James's OK)

Restart the connector on merged main, republish the catalog, allow `adaptive_rough_toolpath` (confirm ON), and on the "SteveCAM test block" build face, then a connector rough. Then generate the program, then the toolpath, then the program again, and compare STEVE's verdict and checks with our zmap.
