# SteveCAM connector: guide for agents

The connector runs SteveCAM's engine on this Mac for STEVE. Nothing is ever
sent to a machine: every program still needs a graphics check and a dry
run above the part on the X7.

## Actions

| action | use it to | returns |
| --- | --- | --- |
| `adaptive_rough` | rough a STEP part with a flat or bull end mill | rough.nc, check.json, preview.png + envelope |
| `slope_split_finish` | rough, then finish with a ball nose (optional rest pass) | rough.nc, finish.nc (rest.nc), check.json, preview.png + envelope |
| `check_program` | judge up to three posted programs against the part | check.json, preview.png + envelope (no program posted) |
| `model.measure` | read the oriented model's size before choosing stock | `{size_mm, bbox_mm}` + envelope |
| `tools.list` | see the tool library (tool_id, T/H/D, geometry, holder) | `{tools, pockets}` + envelope |
| `tools.update` | edit one library tool or the pocket count | `{tool, pockets}` + envelope |
| `job.get` | read a document's renumbering, tools used and saved setup | `{document_id, renumber, tools_used, setup}` + envelope |
| `job.renumber` | post a tool under another T for one document | the job + envelope |
| `job.setup` | save a document's setup (orientation, origin, units, stock, blank) | the job + envelope |

None of them needs a confirmation. Every input's description in the
catalog states its unit, range and default.

**Units.** `units` (inch when omitted, or mm) sets the unit of every length
and feed input and of the posted program. Ranges are listed in both.

**Origin.** `origin` puts the program's X0 Y0 Z0 at the centre of the
stock box's bottom face (`stock_bottom_centre`, default for rough and
finish), its top face (`stock_top_centre`), or the STEP model's own origin
(`model_origin`, default for check_program: give the origin a program was
posted with to judge it in that frame).

## The result envelope

Every result carries, next to its own fields:

- `verdict`: `ready` | `needs_review` | `failed`
- `summary`: one plain sentence
- `attention`: list of `{code, severity: blocker|review|info, message,
  where?: {program, line, x, y, z}, next_step}`

`ready` only when nothing in `attention` is a blocker or review item. A
blocker means a gate failed: the run is `failed` and no `.nc` is uploaded.
check.json carries the same three fields.

## Errors

A refused or failed run reports `error = {code, message, field?, got?,
allowed?, next_step}`. `allowed` is in the units you sent (for example
`{"minimum": 0.0394, "maximum": 1.2598, "units": "inch"}`). Read
`allowed`, fix `field`, and run again.

## Codes

Generated from `connector/errors.py` (`python3 connector/errors.py`
rewrites this table; a test fails when it drifts).

<!-- codes:begin -->
| code | kind | next_step |
| --- | --- | --- |
| `input_missing` | error | Add the missing input named in `field`. |
| `input_unknown` | error | Remove or rename the input in `field`; `allowed` lists the closest valid names. |
| `input_out_of_range` | error | Use a value inside `allowed` (in the units you sent) for `field`, then run again. |
| `action_unknown` | error | Use one of the connector's actions (see the catalog). |
| `input_digest_mismatch` | error | Send the run again: the downloaded file did not match its sha256/size. |
| `connector_stopping` | error | The SteveCAM connector was shutting down; start it again (menu bar: Start) and re-run. |
| `unknown_tool` | error | Use a tool_id from tools.list. |
| `duplicate_t` | error | Pick a T no other tool uses in this job (job.get / tools.list show the T numbers in use), or renumber the other tool first. |
| `out_of_range` | error | Use a T inside `allowed` (job.renumber: 1..pockets; tools.update: 1..999); tools.update {pockets} changes the pocket count. |
| `invalid_field` | error | Fix the field named in `field` (see `allowed`). |
| `unknown_holder` | error | Use a holder name from `allowed`, or null. |
| `duplicate_tool` | error | Change the type, diameter or corner so the tool differs from the one named in the message. |
| `bad_document_id` | error | Pass the STEVE document id as sent by STEVE (letters, digits, '.', '_', '-', <= 128). |
| `no_library` | error | Run the connector with its state directory (~/.stevecam or --home). |
| `no_view` | error | Pick one of the last_runs event's recent cutting/check runs with has_view true (view.load shows a run's stored 3D view). |
| `library_error` | error | Check ~/.stevecam/tools.json is valid JSON; delete it to re-seed from the repo table. |
| `tool_not_in_table` | error | add this tool to tools/x7_tools.json (the table the engine and judges read), or pick a tool that is in it |
| `tool_table_unreadable` | error | Fix or re-seed the tool library file named in the message. |
| `tool_entry_incomplete` | error | Fill the missing field of that tool with tools.update. |
| `finish_tool_not_in_table` | error | Pass tool_number for the finish ball, or add the ball to the library. |
| `rest_tool_no_holder` | error | Set the rest tool's holder (and stick-out) in the library, or pick a rest tool that has one. |
| `rest_tool_not_ball` | error | Pick a ball nose for rest_tool_number. |
| `rest_tool_too_big` | error | Pick a rest ball smaller than the finishing ball. |
| `multi_tool_program` | error | Split the program into one program per tool (program, program_2, program_3). |
| `no_t_word` | error | Add a T word to the program or pass tool_number. |
| `tool_number_mismatch` | error | Leave tool_number empty or set it to the program's own T. |
| `tool_geometry_mismatch` | error | Set that library tool's field to the value tools/x7_tools.json shows. |
| `gouges` | blocker | Check orientation, tool size and stepdown at the spot in `where`, then run again. |
| `rapid_collisions` | blocker | Check floor_z and the stock sizes; the first offending line is in `where`. |
| `over_flute` | blocker | Use a longer-flute or necked tool, or split the depth. |
| `tool_holder_missing` | blocker | Add the tool's holder and stick-out with tools.update (holder, stickout_mm), then run again. |
| `holder_unknown` | blocker | Give the tool a holder and stick-out in the library (tools.update), or pick a tool that has one. |
| `holder_hits` | blocker | Use more stick-out or a slimmer holder; the first line is in `where`. |
| `axial_plunges` | blocker | Raise floor_z or use a ramp-capable entry; the first line is in `where`. |
| `clcheck` | blocker | Check the ball diameter and tool number against the library and run again. |
| `unsupported_code` | blocker | Remove the code named in the message (line in `where`) or post with the supported subset. |
| `outside_grid` | blocker | Make the stock box cover every move, or check the program's origin. |
| `posted_units_mismatch` | blocker | Report this: the post did not honour `units`. |
| `stale_artifact` | blocker | Run again; a stale intermediate file was refused. |
| `engine_failed` | blocker | Read the message; fix the inputs it names, or report it with the run id. |
| `nothing_to_cut` | blocker | Nothing was cleared: finish or rest the exterior instead, or check the orientation, stock and floor inputs. |
| `internal_error` | blocker | Report it with the run id; the details are in the connector's run log. |
| `engagement_overload` | review | Look at the listed lines; lower optimal_load or stepover if they chatter. |
| `steep_plunge` | review | Check the entries at the listed lines before running. |
| `reduced_feed_windows` | review | Check the slowed sections; they cost cycle time. |
| `credit_fallback` | review | Check the regions the engine cut with its fallback strategy. |
| `failed_region_emitted` | review | Inspect the region the engine could not plan cleanly before running. |
| `stock_bottom_unchecked` | review | Run again; if it repeats, report it with the run id (the judge got no stock box for this program). |
| `area_left_for_next_op` | info | Plan the next operation (finish or rest) for the stock left. |
| `leftover` | info | No action: leftover summary for the program. |
| `tool_without_holder` | info | Add holder + stick-out if you will cut with it (tools.update). |
<!-- codes:end -->
