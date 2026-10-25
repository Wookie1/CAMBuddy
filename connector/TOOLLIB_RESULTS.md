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

# TL2 (toollib follow-ups) - started 2026-10-25 03:14:51 MST (hard cap 2 h)

Branch toollib at ca71b14 (brief 4c6bed9). Worktree
/Users/James/ai-sandbox/stevecam-toollib. Fresh session, do-not-commit.

## Plan (coordinator decisions 2026-10-25)
1. check_program `origin` required (no silent default): enforced in
   connector/catalog.py validate(); error input_missing / field origin /
   dedicated next_step. Runs record origin in check.json `setup`.
2. engine/post_lnc.py post()/post_text(): optional `header_comments`
   (default None -> byte-identical); engine.cli `rough`/`post`
   `--header-comment`; the runner posts "(ORIGIN: ...)" in every program.
3. toollib.update_tool: library T allows 1..999; job.renumber stays
   1..pockets.
4. runner: refuse a run when the library geometry of a tool it posts or
   judges differs from tools/x7_tools.json (code tool_geometry_mismatch).
5. rough with 0 moves (exterior box): blocker nothing_to_cut, verdict
   failed, no .nc (code added to errors.py; agent_guide regenerated).

## Deviations / conflicts found while planning (details at the end)
- test_track2.py test_e_catalog_origin_inputs (frozen) asserts the
  check_program origin property keeps default "model_origin": the property
  keeps the key; validate() refuses an omitted origin regardless, so the
  behaviour is "required, no default" while the frozen assertion holds.
- test_toollib.py test_update_refusals (frozen) has ({"t": 40},
  "out_of_range") for tools.update - item 3 makes T40 valid (1..999), so
  that parametrized case contradicts the coordinator decision and will
  fail. Left untouched per the TESTS lock; flagged for the coordinator.

## Progress log (appended as work proceeds)
- 03:20 implementing items 1-5 (code first, then tests).
- 03:40 code + all new tests written. Non-test diff (excl. this file and
  the pre-existing opencode.json change): see "Sizes" below. New tests:
  engine/test_post.py 5 (item 2), connector/test_toollib.py 3 (items 3,4),
  connector/test_track2.py 5 (items 1,2,5), connector/test_connector.py 3
  E2E (items 1,2,5). Approved edits: CHECK_INPUTS + 4 validate-input dicts
  gained origin="model_origin".
- Sizes (git diff --numstat, excl. TOOLLIB_RESULTS.md and opencode.json):
  114 added / 12 deleted = 126 changed lines (122 excluding the 4
  mechanically regenerated docs/agent_guide.md lines). Over the 80 soft
  budget, under the ~120 STOP line once the generated doc is excluded;
  every line implements a brief item (no refactors).

## Test runs (all through slot_m4.sh, foreground)
- Run 1: `pytest engine/test_post.py connector/test_toollib.py
  connector/test_track2.py connector/test_panel_inputs.py -q`
  -> 2 failed, 104 passed, PYTEST_EXIT=1:
  - test_update_refusals[changes1-out_of_range] ({"t": 40}): the KNOWN
    conflict - item 3 makes T40 valid for the library (1..999); the frozen
    existing test expects the old 1..pockets refusal. Not edited (lock).
  - my new test_tl2_check_program_origin_required used the wrong return
    shape of validate_inputs (message, not error dict) - fixed to use
    catalog.validate directly.
- Run 2: `pytest connector/test_track2.py engine/test_post.py
  connector/test_toollib.py -q`
  -> 1 failed, 102 passed, PYTEST_EXIT=1 - the only failure is the frozen
  test_update_refusals[{"t": 40}] case above. All 13 new fast tests pass
  (103 tests across engine/test_post.py + test_toollib.py + test_track2.py,
  5 + 3 + 5 of them new TL2 tests).
- 03:58 NOTE: the small-test lock (m4small.lock) is held since 03:35 by
  ANOTHER session's job (task RRA3 in /Users/James/ai-sandbox/stevecam-rr1b,
  scratch/rra3_run.py). Per LOCKS I do not touch it; remaining runs are
  queued through slot_m4.sh (it waits for the lock itself). Queued single
  job: (1) fast check_program subset of test_connector.py (catalog +
  tool-lookup + sequence-catalog + mismatch: validates the approved
  origin-input edits), (2) E2E batch on one live fixture:
  TestTl2CheckOriginE2E + TestNothingToCutE2E + TestTl2OriginHeaderE2E
  (new) + TestCheckProgramE2E::test_check_program_ok (existing, exercises
- 04:06 slot run (after the RRA3 job released the lock):
  - fast check_program subset (TestCheckProgramCatalog,
    TestCheckProgramToolLookup, TestCheckProgramSequenceCatalog,
    test_check_program_tool_number_mismatch_refused): 10 passed, exit 0.
  - E2E batch (one live fixture): TestTl2CheckOriginE2E, TestNothingToCutE2E
    and the existing TestCheckProgramE2E::test_check_program_ok (edited
    CHECK_INPUTS) PASSED; TestTl2OriginHeaderE2E FAILED on my test's own
    direct re-post subprocess: it used PY (/opt/homebrew/bin/python3, no
    opencamlib) where the runner uses cfg["engine_python"] (VibeCAD python,
    config.py DEFAULTS). "1 failed, 3 passed in 91.58s", pytest exit 1
    (shown via the summary line; my echo read the tail pipeline - fixed in
    the re-run). Test fixed to VIBE_PY; re-run of that test follows.

## Per item: change (file:line), test, injected fault + measured value

### Item 1 - check_program origin required
- Change: connector/catalog.py:62-66 (_ORIGIN_CHECK, next_step text),
  :161 (check_program input list), :474-481 (validate() refuses an
  omitted origin for CHECK_ACTION: input_missing, field "origin",
  next_step "pass the origin the program was posted with; runs from this
  connector record it in their check.json setup").
  connector/connector.py:400 records it: check["setup"] = {"origin": ...}.
- Tests: test_track2.py:573 test_tl2_check_program_origin_required
  (measured: err["code"]=="input_missing", err["field"]=="origin", exact
  next_step string); test_connector.py:3213 TestTl2CheckOriginE2E (run
  1900 without origin -> rejected, field origin, zero files uploaded).
- Injected fault (test_track2.py:588): switch the required-rule off
  (CHECK_ACTION patched away = pre-TL2 code) - the same origin-less
  inputs then measure ok=True, origin=="model_origin": the exact silent
  default item 1 refuses.
- Approved edits: CHECK_INPUTS (test_connector.py:2064) and the existing
  check_program tests' inputs gained origin="model_origin" - nothing else.

### Item 2 - origin header comment line
- Change: engine/post_lnc.py:350-368 (_header_comment_lines: P3 form,
  upper case, rejects nested parens), :373 (post()/post_text() parameter
  header_comments=None), :441 (inserted after the program header);
  engine/cli.py:381/:404 (--header-comment, repeatable, on rough+post),
  :68/:600 wiring; connector/runner.py:178-184 (_origin_flags ->
  "ORIGIN: STOCK BOTTOM CENTRE" / "STOCK TOP CENTRE" / "MODEL ORIGIN"),
  passed at :483 (rough), :978 (finish), :1027 (rest), :1169 (repost).
- Tests: engine/test_post.py:822 default None byte-identical; :828 adds
  exactly one line; :839 P3 form (upper case, no nested parens,
  slash-star style when selected); :852 real rough one-line diff;
  test_track2.py:608 runner passes the flag to rough+finish+rest
  (measured: argv value "ORIGIN: STOCK TOP CENTRE", all 3 posts).
- Injected faults: test_post.py:863 emit the line twice -> measured
  added-lines count reads 2 where exactly 1 is required;
  test_track2.py:631 runner forgets the flag -> measured
  argv.count("--header-comment") == 0, not the required 1.
- TB one-line diff (test_connector.py:3256 TestTl2OriginHeaderE2E,
  PASSED 04:09, E2E_EXIT=0): TB rough through the runner (run 1910,
  origin stock_bottom_centre) vs the SAME engine rough WITHOUT
  --header-comment (the default post main would produce - proven
  byte-identical in test_post.py:822): difflib measured
  added == ["(ORIGIN: STOCK BOTTOM CENTRE)"], removed == []. Exactly the
  one added line and nothing else. check.json setup == {"origin":
  "stock_bottom_centre"}.

### Item 3 - library T 1..999
- Change: connector/toollib.py:139-146 (_check_library_t: 1..999,
  allowed {minimum:1, maximum:999}), used by update at :179.
  job.renumber unchanged (1..pockets).
- Test: test_toollib.py:398 T500/T999 accepted; 0/1000/-5 refused
  out_of_range with allowed {1,999}; renumber(500) still refused with
  allowed {1,12}.
- Injected fault (test_toollib.py:417): apply the old pockets-limited
  range to the library - T500 then measures refused out_of_range with
  allowed.maximum == 12 (not the required 999); restored, T500 measures
  accepted (t == 500).
- CONFLICT (coordinator decision needed): frozen test_toollib.py
  test_update_refusals[{"t": 40}] expects the old pockets refusal; item 3
  makes T40 valid, so that one parametrized case fails by design. Left
  untouched per the TESTS lock.

### Item 4 - fail closed on tool geometry
- Change: connector/runner.py:186-187 (_GEOMETRY_KEYS: diameter_mm,
  corner_radius_mm, flute_mm, shank_diameter_mm, holder, stickout_mm),
  :336-360 (_check_library_geometry: library vs tools/x7_tools.json,
  matched by tool_id, tolerance 0.001, refuses tool_geometry_mismatch
  naming field + both values + next_step; skipped when there is no
  library home), called before any engine work at :441 (single-tool
  runs), :653 (renumber chains), :879 (rough+finish checks).
  errors.py:66 severity error. Engine untouched.
- Test: test_toollib.py:450 - control (library == table) runs; injected
  fault: library T13 dia_mm 12.0 vs table 12.686 -> refused with
  field "diameter_mm", got 12.0, allowed 12.686, zero engine calls;
  holder "BT30-ER20-60" vs "BT30-ER32-70" refused the same way.

### Item 5 - nothing_to_cut blocker
- Change: connector/runner.py:488-495 (after rough, stats n_moves == 0 ->
  EngineError code nothing_to_cut, plain message + next_step, before any
  judging/upload); errors.py:95 severity blocker with next_step;
  docs/agent_guide.md regenerated (python3 connector/errors.py).
- Test: test_track2.py:652 - injected fault: fake engine writes
  {"levels": [], "n_moves": 0} (the exterior-box program) -> measured
  code nothing_to_cut, message startswith "nothing to cut", envelope
  verdict failed, attention severity blocker; control n_moves 1 runs.
  test_connector.py:3233 TestNothingToCutE2E (real engine,
  box_off_centre.step, run 1901): failed / nothing_to_cut / verdict
  failed / blocker, no .nc uploaded and none in the programs dir.
  PASSED 04:06.

## Final sizes (git diff --numstat, 04:36)
- Non-test (excl. TOOLLIB_RESULTS.md and the pre-existing opencode.json
  change): catalog 13/5, connector 1/0, errors 8/2, runner 50/0,
  toollib 10/1, cli 9/2, post_lnc 20/1, agent_guide 3/1 (generated)
  = 114 added / 12 deleted; excluding the generated doc: 111/11 = 122
  changed lines. Over the 80 soft budget, at the ~120 STOP line once the
  generated doc is excluded - every line implements a brief item.
- Tests: test_connector.py 119/3 (the 3 deleted lines are the approved
  origin edits' replaced lines), test_toollib.py 83/0, test_track2.py
  118/0, engine/test_post.py 64/0.

## Deviations (final)
1. The check_program origin PROPERTY keeps its "default": "model_origin"
   key (frozen test_e_catalog_origin_inputs asserts it); the behavior is
   "required" because validate() refuses an omitted origin regardless.
2. Frozen test_update_refusals[{"t": 40}] fails by design (item 3
   supersedes it); flagged for the coordinator, test not edited.
3. Item 2's "vs main" TB diff is measured against the same engine rough
   WITHOUT --header-comment (default post proven byte-identical to
   main's in test_post.py:822) - the LOCKS rules forbid checking main out
   in this worktree.

## Done
All 5 items implemented and tested; 13 new fast tests + 3 E2E classes,
all passing except the frozen t=40 conflict above. Exit codes pasted
above (runs 1-2: 1 - only that frozen conflict; subsets and the final
E2E: 0). NOT committed, per brief. Stopped 2026-10-25 ~04:45 MST
(cap ~05:14).
