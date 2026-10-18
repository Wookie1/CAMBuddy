# Task M: add slope_split_finish to the STEVE connector (connector/ only)
Rules: no MCP, no questions, do not commit, never contact stevecad.studio (mock only), probes in connector/probe_*.py.
Read docs/steve_connector_protocol.md for catalog rules. Do not edit engine/finish.py (another track owns it); call
the engine CLI only: `python -m engine.cli finish --stl ... --tool ball:<dia> --out ... --stats-json ... --floor ...`
(run `/Applications/VibeCAD.app/Contents/Resources/bin/python -m engine.cli finish --help` for the flags).
1. Catalog: new action slope_split_finish, confirm false, title "Slope-split finishing". Inputs: model
   {"x-steve":"file","format":"step"} (required); orientation enum (same as adaptive_rough); stock offsets (same);
   tool_diameter (ball, mm, 1-25, default 6), stepover (0.05-2, default 0.3), stepdown (0.05-2, default 0.3),
   slope_threshold (10-80 deg, default 40), floor_z (optional), rpm/feed/ramp_feed, units inch|mm default inch,
   program_number, tool_number (optional, else tools/x7_tools.json; refuse if the tool is not in the table and no
   number is given, with a clear error the run reports as failed).
   Optional input rough_run_id is NOT supported in v1; instead the action takes the model and does
   prepare -> finish in its own work dir (no roughing stock): note this in the action description.
2. Result JSON: estimated time, cut length, probe_clcheck count (run engine/probe_clcheck.py on the output; must
   be 0 or the run fails), zmap gouges / rapid collisions / leftover (zmap on a fresh 0.01-tess heightfield from
   verify/heightfield.py, full stock, no stock-in). Files: .nc (LNC post), check.json, preview.png.
3. Tests in connector/test_connector.py with the mock STEVE: catalog validates (names, limits, <= 30 inputs),
   e2e slope_split_finish run on the small synthetic STEP succeeds with clcheck 0, out-of-range input rejected,
   missing tool -> failed with a clear message. Keep all existing tests passing.

## CHANGE (supervisor, overrides item 1's "no roughing stock" and item 2's zmap setup)
A finish that assumes raw stock is dangerous: a 6 mm ball run into an un-roughed block breaks the tool. In v1 the
slope_split_finish action MUST run adaptive_rough first (same model/orientation/stock inputs; roughing tool and
cutting data inputs as in adaptive_rough, with their defaults) and return BOTH programs (rough .nc and finish .nc,
plus a combined summary). zmap judges the chain: roughing first (--stock-out), then the finish with --stock-in.
Put "run after roughing" in the action description and as a comment line in the finish G-code header.
Test (mock STEVE): the action can never return a finish-only program judged from raw stock - assert both files are
uploaded, the finish header carries the run-after-roughing comment, and the result's zmap block reports the chained
judgement (e.g. a "stock_in": "roughing" field).

## Supervisor note (relaunch on another model)
The previous session (81 steps) was moved to a faster machine mid-task. Its work is in the tree: check git diff and
connector/probe_*.py first, finish the remaining items, run the connector tests, and print the summary.
