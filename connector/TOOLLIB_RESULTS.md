# TOOLLIB results (track 2, branch toollib)

## Log
- 2026-10-24: started. Added a stable `tool_id` to every entry in
  tools/x7_tools.json (`<type>-<dia>` with `-r<corner>` for bulls; written
  once, never regenerated). Next: connector/toollib.py, catalog actions,
  runner wiring, tests.

## Contract (tool library + job renumbering)

Files: connector/toollib.py (new), connector/catalog.py, connector/runner.py,
connector/connector.py, tools/x7_tools.json (tool_id only),
connector/test_toollib.py (new), connector/test_connector.py (new class
TestToolLibE2E appended, nothing existing changed),
connector/testdata/check_ok_t5.nc (new: check_ok.nc with T13/H13 -> T5/H05).
engine/post_lnc.py: NOT touched (lookup_tool already takes a `table`
argument; the runner passes the effective table).

Storage (all under the connector state dir, STEVECAM_HOME / --home; tests
use pytest temp dirs only, the real ~/.stevecam was never written):
- `tools.json` - the library, seeded once from tools/x7_tools.json. The
  connector never rewrites the repo file. Optional top-level `pockets`
  (default 12).
- `jobs/<document_id>.json` = `{tool_id: T}` (only overrides; renumbering
  back to the library T removes the key).
- `jobs/used/<document_id>.json` = `[tool_id]` (tools the document's
  successful runs posted or checked).
- each run writes `runs/<id>/tools_effective.json` (library + job map) and
  passes it to every zmap call as `--tools-json`, so holder/flute/shank
  lookups by T use the job numbers.

Document id: the new optional `document_id` input on adaptive_rough,
slope_split_finish and check_program; when omitted, the model input's STEVE
`document.id` is used (so an agent run on the document gets the panel's
renumbering). Ids must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` (they are
file names) else `bad_document_id`.

Posting: rough/finish/rest T (and H, which the post writes from the same
number) come from the effective table; an explicit tool_number /
rest_tool_number is read as a job T. check_program resolves the program's
T word through the effective table.

### Actions (all confirm:false)
- `tools.list {}` -> `{tools:[{tool_id, t, h, d, name, type, dia_mm,
  corner_r_mm, flute_len_mm, reach_mm, holder, rpm, feed_mm_min,
  plunge_mm_min}], pockets}`
- `tools.update {tool_id?, changes?: {field: value}, pockets?}` -> `{tool:
  <tools.list entry or null>, pockets}`. Editable: t, name, type, dia_mm,
  corner_r_mm, flute_len_mm, reach_mm, holder, rpm, feed_mm_min,
  plunge_mm_min (h and d follow t: H%02d/D%02d; tool_id never changes).
  Saved to the library only.
  Errors: unknown_tool, invalid_field, duplicate_t (another library tool
  has that T), out_of_range (t outside 1..pockets, pockets outside 1..999),
  unknown_holder, duplicate_tool (same type/dia/corner as another tool).
- `job.get {document_id}` -> `{document_id, renumber:{tool_id:t},
  tools_used:[tool_id]}`
- `job.renumber {document_id, tool_id, t}` -> the job (as job.get), or the
  run fails with error `{code, message}`: duplicate_t, out_of_range,
  unknown_tool, bad_document_id. t equal to the library T clears the
  override (always allowed).
- A run whose job map now collides (a later library edit put another tool
  on the same T) fails with `tool library: duplicate_t ...` before any
  engine work.

### Field gaps (null in tools.list; nothing invented)
- reach_mm: no tool has it (stickout_mm/oal_mm exist but are not reach).
- rpm, feed_mm_min, plunge_mm_min: no tool has them.
- holder: null for bull-12.700-r0.127 (T3), ball-19.050, ball-12.700,
  ball-1.587, ball-0.794.
- t/h/d: null for ball-19.050, ball-12.700, ball-1.587, ball-0.794 (no
  assigned T in the table).
- name: from `description` (all tools have one).

### Open issues
- Library default T20, T31, T33, T13 exceed the default 12 pockets. They
  stay valid as library defaults; job.renumber/tools.update refuse new T
  > pockets. Set `pockets` (tools.update {pockets}) if the X7 holds more.
- The library is seeded once; later repo-table additions do not reach an
  existing ~/.stevecam/tools.json.
- engine/finish.py reads flute/shank/holder by diameter from the repo
  table (outside my file set): tools.update edits to those fields reach
  zmap and check_program, but not the engine finish's own S4/S5 passes for
  the finish ball (the rest pass gets them via explicit flags already).
- rpm/feed/plunge in the library are stored only; runs still use their
  inputs.

### Contract test results
- `slot_m4.sh python3 -m pytest connector/test_connector.py connector/test_toollib.py -q`
  -> 129 passed in 1393.5 s, exit 0 (99 test_connector incl. the 3 new
  TestToolLibE2E, 30 test_toollib).
- `python3 -m pytest engine/test_post.py -q` -> 19 passed, exit 0.
- E2E proof: slope_split_finish + rest (T31) on doc-renum-e2e with
  flat-12.686 T13->T5: rough.nc T/H words = {T5}/{H05}, finish.nc
  {T20}/{H20}, rest.nc {T31}/{H31}; library + repo table sha256 unchanged;
  check_program of check_ok_t5.nc resolves T5 -> flat 12.686 BT30-ER32-70
  and passes; without the job (doc-1) it fails naming T5.
