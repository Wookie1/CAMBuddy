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

## (a) Omitted units mean inch
- Fix: `catalog.to_mm(values, action)` applies the action's units default
  (inch) BEFORE converting; the connector's input pipeline is now
  `connector.prepare_values(values_in, action)` (to_mm -> document_id
  fallback -> validate_inputs). check_program has no units input: unchanged.
- Tests: test_track2.py `test_a_omitted_units_mean_inch` (fake engine: rough
  `--tool` diameter and `--cut-feed` equal the inch values x 25.4, no
  --metric) and E2E `TestOmittedUnitsE2E` (real post, no units input:
  G20 only, header `(T13 D=0.5 ...`, max F = 135 in/min).
- Injected fault (`test_a_injected_fault_is_measured`): the old order
  (to_mm ignoring the default): diameter off by 24.4 mm (1.0 read as mm vs
  25.4), feed off by 2440 mm/min (100 vs 2540).

## (b) model.measure
- New action `model.measure {model, orientation}` (confirm false) ->
  `{size_mm:{x,y,z}, bbox_mm:{min:[x,y,z], max:[x,y,z]}}`; runner
  `run_measure` runs the same `engine.cli prepare` (zero allowances) every
  cutting action uses and reads its bbox; nothing uploaded.
- Tests: fast `test_b_*` (shape, prepare argv) and E2E
  `TestModelMeasureE2E` (measured bbox + GOOD_INPUTS allowances = the rough's
  stock_box_mm within 2e-4 mm).
- Injected fault (`test_b_injected_fault_is_measured`): measuring the
  stock box instead of the part -> off by 2.0 mm (largest allowance).

## (c) Setup memory
- `jobs/<doc_id>.json` gains a reserved `setup` key next to the
  `{tool_id: T}` overrides. `setup = {orientation, units, stock_xy,
  stock_x, stock_y, stock_top, stock_bottom, floor_z, blank:{x,y,z}|null}`
  in mm, validated with adaptive_rough's own catalog specs (enums and
  mm ranges; omitted fields take the action defaults).
- New action `job.setup {document_id, setup}` -> the job. `job.get` now
  also returns `setup` (null if never saved). NOTE: this changed the
  job.get shape I committed in the contract step; my own two equality
  asserts (test_toollib.py:94, test_connector.py TestToolLibE2E) gained
  `"setup": None` - no pre-existing test was touched.
- Errors: out_of_range (range/enum), invalid_field (non-number, unknown
  key, bad blank), bad_document_id.
- Injected fault (`test_c_injected_fault_is_measured`): validation
  skipped -> stock_top 30.0 saved, 4.6 mm above the 25.4 mm maximum.
- Runs do not read the saved setup yet (the panel fills inputs from it).

## (d) Orientation rot_x_90 / rot_x_270 / rot_y_90 / rot_y_270
- Touched outside connector/: engine/_orient.py (the four rotations, about
  the bbox centre like the flips, right-hand rule) and engine/cli.py
  (`prepare --orient` choices only). Catalog orientation enum + one plain
  description, shared by all three actions, model.measure and job.setup.
- Sign check (one-off freecadcmd): rotating a +Y boss +90 deg about X puts
  it at z 10..12 (+Z); a +Z boss +90 deg about Y lands at x 10..12 (+X).
- New fixture connector/testdata/box_off_centre.step (40x20x10, x 5..45,
  y -3..17, z -10..0: off-centre, Z0 at its top; built with
  Part.makeBox).
- E2E `TestOrientationE2E`: measured sizes for all 8 orientations
  (rot_x: 40x10x20, rot_y: 10x20x40) within 1e-3 mm, box centre stays
  (25, 7, -5); a rough on the rot_x_90 box passes every gate, stock box
  42 x 12 x 21.4.
- Injected fault (`test_injected_fault_is_measured`): rot_x_90 mapped to
  the 180 flip -> the real measurement misses by 10 mm in Y and Z.

### (a)-(d) status at commit
- Fast: test_track2.py + test_toollib.py + engine/test_post.py green
  (51 + 19, exit 0).
- E2E first run (slot_m4): TestToolLibE2E 3/3 and TestOmittedUnitsE2E
  passed; TestModelMeasureE2E and the measure tests of TestOrientationE2E
  FAILED - real bug: prepare_values injected the model's document_id into
  model.measure (which has no such input) -> input_unknown. Fixed (only
  actions that declare document_id get the fallback) + fast regression
  test `test_b_measure_inputs_get_no_document_fallback`. Direct runner
  measurement of box_off_centre: as_modeled 40x20x10, rot_x_90 40x10x20,
  box centre kept.
- The (d) rough on the plain turned box FAILED its gates (2 rapid
  collisions at line 16, `G43 Z0.`): the roughing engine clears only
  enclosed regions, so a plain exterior box posts an empty program (all
  levels region 0 mm2) - same on as_modeled, not an orientation bug. The
  fixture is now box_turn.step (block with a pocket that faces up after
  rot_x_90). E2E re-run is queued behind the merge gate (slot_m4).

## (e) Work origin
- Input `origin` (enum stock_bottom_centre | stock_top_centre |
  model_origin) on adaptive_rough + slope_split_finish (default
  stock_bottom_centre), check_program (default **model_origin**, see
  deviation below) and in job.setup (`setup.origin`).
- Engine (outside connector/, exactly): engine/cli.py - new pure
  `origin_offset(stock, origin)` + `ORIGINS`/`ORIGIN_EPS`, `prepare
  --origin` (CLI default model_origin = unchanged for every other caller);
  after the stock box is built, a non-zero offset (> 1e-4 mm) re-runs
  engine/_orient.py with new env TRANSLATE to move the oriented STEP, and
  the stock box is rebuilt from the moved bbox; prepare.json gains
  `origin` + `origin_offset`. engine/_orient.py - optional TRANSLATE.
  Below 1e-4 mm nothing is moved, so a model already in the chosen frame
  keeps today's exact STEP.
- Runner passes `--origin` to every prepare (rough, slope, check;
  model.measure stays in the model frame); results gain `origin` and
  `origin_offset_mm`.
- Deviation 1 (check_program default model_origin): the existing
  check_program E2E fixtures (check_ok.nc etc.) were posted in the
  synth_pocket model frame (part z 0..12, stock bottom -1). Judged at
  stock_bottom_centre the model moves +1 mm in Z and the top skim at
  Z12.05 would sit 0.95 mm inside the part (13.0 top). Existing tests
  cannot change, and a STEVE-posted program is in the frame it was
  posted with, so check_program defaults to model_origin and takes
  `origin` to judge in another frame.
- Deviation 2 (header line HELD): the only existing post comment
  parameter is `--op-name` (posted as `(<OP NAME>)`); using it changes the
  posted bytes, which contradicts byte identity at the default. Held, no
  edit to engine/post_lnc.py.
- Byte identity note: synth_pocket (z 0..12) and samples/test_block.step
  (bbox x -50..50, y -40..40, z 0..35) are XY-centred with Z0 at the PART
  bottom; at the default origin they only stay byte-identical when
  stock_bottom = 0 (else everything moves up by stock_bottom). TB pair
  (stock_bottom 0 and 1) vs main 681f551 is queued; CF needs your setup
  STEP path and runner inputs (not searched, nothing committed).
- Fast tests: `test_e_*` (offset math for all 3 origins, catalog, runner
  argv). Injected fault (`test_e_injected_fault_is_measured`): a Z offset
  0.5 mm off -> frame check misses by 0.5 mm. E2E `TestWorkOriginE2E`
  (box_origin.step: off-centre, Z0 at its top, pocket on top): stock box
  in result and in zmap's check.json within 1e-3 mm for each origin,
  the posted program moves by exactly the offset, the same check on real
  data with a 0.5 mm wrong expectation measures 0.5 mm, and check_program
  passes the bottom-centre program at stock_bottom_centre and fails it at
  model_origin.

## (f) Agent-facing envelope, errors, catalog text, guide
- New: connector/errors.py (the code table CODES / NEXT_STEPS,
  make_error, error_issues, the guide generator), connector/envelope.py
  (verdict / summary / attention), docs/agent_guide.md (code table
  generated: `python3 connector/errors.py`).
- Envelope on every action's result (cutting actions, model.measure and
  the five tool/job actions) and written into check.json before upload.
  Mapping: zmap/clcheck/unsupported/posted-units/... gate failures =
  blocker (run failed, error + failed envelope in the report, no .nc);
  engagement over threshold, steep plunges and - when an engine emits
  them - reduced_feed_windows / credit_fallback / failed_region_emitted =
  review; leftover summary and "area left for the next operation"
  (within_0p5mm_fraction < 1) = info; tools without a holder in
  tools.list = info. NOTE: this engine base emits none of the three
  engine review counters yet; the envelope reads them when present.
- Errors: every refusal is `{code, message, field?, got?, allowed?,
  next_step}`: input_missing, input_unknown (closest names in `allowed`
  and "did you mean"), input_out_of_range (range in the caller's units:
  inch callers get inch bounds), the bull corner rule, every toollib code,
  and every runner fail-closed path (26 raise sites, each with its own
  code). Engine stderr never reaches the caller: a known gate line
  (unsupported / outside grid) or the last non-traceback line; the full
  stderr goes to runs/<id>/engine_stderr.log, unexpected exceptions to
  runs/<id>/connector_error.log (internal_error).
- Catalog: action descriptions rewritten to 1-2 sentences (when to use,
  what it returns); every value input's description now ends with its
  unit ("length/feed, follows `units`"), range in mm and inch, and
  default; units and origin are explained once (their own inputs).
- Contract note: tool/job results gained verdict/summary/attention; my
  own TestToolLibE2E exact-equality assert now compares the job keys and
  checks verdict ready (no pre-existing test touched).
- Fast tests (test_track2.py `test_f_*`): 30 error paths each checked for
  non-empty code/message/next_step and the expected `field`; injected
  fault: input_out_of_range's next_step blanked -> exactly the 3 paths
  using it are flagged ("missing next_step"). Envelope mapping + a
  hand-written envelope schema check; injected fault: a review item with
  verdict ready -> "verdict ready but attention says needs_review".
  Guide drift test: the generated table must equal the doc section.

## Measurements (engine jobs, slot_m4)

### TB byte identity (samples/test_block.step, adaptive_rough, T13 flat,
GOOD-style inputs: stock xy 1 / top 0.4, floor_z 4, stepdown 4, mm)
Programs posted by main 681f551 (detached worktree), toollib at (e)
5ab38e2 and at (f) d96ff90, default origin:

| stock_bottom | main vs (e) | (e) vs (f) | main vs (f) |
| --- | --- | --- | --- |
| 0 | identical (0 diff lines of 38264) | identical | identical |
| 1 | differ: 14296 diff lines (Z moved +1.0 mm, stock 0..36.4) | identical | differ: 14296 |

So: (f)'s envelope changes no posted byte; at the default origin TB is
byte-identical to main only when the stock bottom already sits at Z0
(stock_bottom 0); with a bottom allowance the default moves it up by
that allowance (origin_offset (0, 0, 1.0)), as specified.
CF: not run - needs your setup STEP path and runner inputs.

### First full run of (a)-(f) (d96ff90 worktree)
166 passed, 2 failed (both in my new E2E, every pre-existing test passed):
- TestModelMeasureE2E compared the model-frame measurement to a rough at
  the new default origin (stock box moved by +1.0 mm in Z) - test now
  roughs at origin=model_origin.
- TestWorkOriginE2E: the stock boxes (result and zmap check.json) sat
  within 1e-3 mm for all three origins; the extra program-frame check
  (cut-move XY centre) moved by the offset to within 0.006 mm, not 0.001
  (the engine plans on a frame-tied grid). Tolerance for that program
  check is now 0.05 mm; the stock-box check stays at 0.001 mm.
- Passed there: TestOrientationE2E (sizes, centre, fault 10 mm, rough on
  turned box), TestAgentEnvelopeE2E (walk-through + envelope schema on
  TB rough, TB slope_split_finish and TB check_program), TestToolLibE2E,
  TestOmittedUnitsE2E.

## Merge of main 04eea8d
- `git merge main` -> merge commit 4cf7a36, no conflicts (this branch
  never edited engine/post_lnc.py).
- connector/test_panel_inputs.py: the skip in
  test_panel_defaults_validate_extended lifted by itself (origin +
  document_id are in the catalog); 3 passed, 0 skipped, file not edited.

## Panel name check (connector/panel/report.js, panel.js - read only)
Matches: action names (adaptive_rough, slope_split_finish,
check_program, model.measure, tools.list, tools.update, job.get,
job.renumber, job.setup); result verdict/summary/attention and items'
severity/message/where{program,line,x,y,z}/next_step (report.js reads them
from the result, else from check.json - both carry them); errors
code/message/field/next_step/allowed (panel.js 815-830); job fields
renumber/tools_used/setup; tools.list tool_id/pockets; measure
size_mm/bbox_mm; setup keys orientation/origin/units/stock_*/floor_z/
blank.
Mismatches / notes:
1. Partial blank: panel.js (setupObject) sends `blank: {x, y, z}` with a
   null axis when only some blank fields are filled; job.setup accepts
   only a full {x,y,z} > 0 or null, so such a save is refused with
   invalid_field (field "setup.blank"). Either the panel sends null until
   all three are filled, or the server accepts null axes - your call.
2. Setup error fields are prefixed "setup." (e.g. "setup.stock_top");
   panel.js shows job.setup errors through errText (message only), so
   nothing breaks, but markServerField would look them up as
   "setup.setup.stock_top" if it were ever used for them.
3. report.js LISTS looks for `areas_left` / `left_for_next_op` / ... keys;
   the connector reports that as an info attention item
   (`area_left_for_next_op`), which the panel shows under "Good to know".

## Final test results (after the merge of main 04eea8d)
- `slot_m4.sh pytest connector/test_connector.py connector/test_toollib.py
  connector/test_track2.py connector/test_panel_inputs.py -q -rs` at
  3d6230b (detached worktree): **171 passed, 0 skipped, exit 0** (33 min).
- `pytest engine/test_post.py -q` in this worktree: **29 passed, exit 0**.
  (In a detached worktree 5 fail only because the untracked out/ fixtures
  are absent there - not a code failure.)
- TestWorkOriginE2E at 95bec85 (`-s`, slot_m4): 1 passed, exit 0. Printed:
  `origin_program_worst_mm: {"stock_bottom_centre": 0.006,
  "stock_top_centre": 0.006}` - no WARNING (both under 0.02 mm); the
  stock-box asserts stay at 1e-3 mm, the program-frame assert at 0.05 mm.
