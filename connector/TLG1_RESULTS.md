# TLG1 results (living record — appended as work proceeds)

Session start (`date`): Sun Oct 25 12:00:30 MST 2026. Hard cap ~14:00 MST.
Branch tlg1 @ ad84f16 (main 98a5706 + brief). No commits.

## Plan
1. engine/cli.py: `--tools-json PATH` on the subparsers the runner calls
   (prepare, rough, finish, post). When given, main() redirects the table
   path constants: engine.finish.TOOL_TABLE_PATH (finish/rest passes) and
   engine.post_lnc.TOOL_TABLE_PATH (post + rough --post lnc lookup). Both
   read their module constant at call time, so finish.py's table lookup
   (tool_geometry/tool_geometry_full/holder_segments, path or
   TOOL_TABLE_PATH) uses the given table WITHOUT editing finish.py.
   With NO --tools-json: no import, no override -> byte-identical.
2. connector/runner.py: pass `*self._tools_json_args()` (already exists) to
   EVERY engine.cli call of a run that has an effective table (prepare,
   rough, finish, rest finish, post, rest post), not only zmap. check.json
   and the run result (run record) name the table path + sha256
   ("tools_table"). Fail-closed rework of _check_library_geometry:
   used library tool needs every geometry field (dia, corner, flute,
   shank, holder, stickout) else tool_not_in_table; a tool_id that IS in
   the repo table with different geometry keeps tool_geometry_mismatch;
   a library-only tool WITH complete geometry is now allowed.
3. verify/zmap.py: NO change needed — --tools-json already exists and the
   runner feeds --dia/--flute/--shank-dia/--tool-number from the effective
   table, so zmap's tool block reads the library diameter. Leaving zmap
   untouched keeps its JSON byte-identical (item 4b).
4. Tests: new connector/test_tlg1.py (fake-spawn argv + real engine post +
   real zmap through slot_m4.sh), engine/test_post.py additions for
   --tools-json, changed assert in test_toollib.py (contract item 3).
5. Byte-identity vs 98a5706 via `git archive 98a5706` into scratch/
   (read-only extraction; no checkout/restore).
6. Mutation (scratch copy): runner passes the repo table instead of the
   effective one -> test (a) must fail by the measured diameter.

## Call sites (file:line at HEAD ad84f16, before edits)
- runner engine calls gaining --tools-json: run() prepare :451, rough :471;
  run_check_program() prepare :669; run_slope_split_finish() prepare :910,
  rough :961, finish :1010, post :1029, rest finish :1137, rest post :1168.
  (run_measure prepare :592 never loads a table - tools_path is None,
  _tools_json_args() is empty there.)
- zmap calls already carry it: :544, :728, :1068, :1091, :1210 (unchanged).
- probe_clcheck.py / heightfield.py calls take no tool table (diameter
  passed explicitly / only TOOL_R) - unchanged, files not editable here.
- engine: cli.py main() dispatch :513; post_lnc.load_tool_table/lookup_tool
  read post_lnc.TOOL_TABLE_PATH (:55) at call time; finish.py
  _tool_entry/holder_segments read finish.TOOL_TABLE_PATH (:117) at call
  time via `path or TOOL_TABLE_PATH`.

## Changes
(to be appended)

## Test runs
(to be appended)

## Changes (file:line after edits)
- engine/cli.py:265-267,426-427,519-520,570-571 (approx): `--tools-json`
  added to the rough, post and finish subparsers (prepare reads no table,
  so it is deliberately NOT given the flag and NOT passed one);
  cli.py:584-591 (after parse_args): when --tools-json is given, redirect
  engine.finish.TOOL_TABLE_PATH (cmd finish/rest) or
  engine.post_lnc.TOOL_TABLE_PATH (post, rough --post lnc lookup). Both
  constants are read at call time, so finish.py's table lookup uses the
  given table with NO edit to finish.py or post_lnc.py. Without the flag
  nothing is imported or changed (byte-identical path).
- connector/runner.py:9 import hashlib; :329-334 _table_record();
  :345-381 _check_library_geometry reworked (item 3);
  :489,:703,:1005 rough argv, :1049 finish, :1061 post, :1182 rest finish,
  :1205 rest post now carry the effective table; :568-570 run() check.json
  gains tools_table; :600 result tools_table; :794 check.json + :827 result
  (check_program); :1273 check.json + :1363 result (slope chain).
- verify/zmap.py: UNCHANGED (0 lines) - --tools-json already exists; the
  runner feeds --dia/--flute/--shank-dia/--tool-number from the effective
  table, so zmap's tool block reads the library diameter (verified by the
  real-call test), and its JSON stays byte-identical.

## Test runs (pasted exit codes)
- connector/test_toollib.py+test_track2.py+test_panel_inputs.py direct
  (before new tests): 1 failed (test_tl2_library_only_tool_refused - the
  contract item 3 changes), 73 passed.
- slot_m4.sh /opt/homebrew/bin/python3 -m pytest connector/test_tlg1.py
  connector/test_toollib.py -q -> 40 passed  EXIT=0
  (incl. the ONE real engine.cli post + verify.zmap call test)
- slot_m4.sh ... pytest connector/test_connector.py -k "(tool or table or
  tl2 or rest_chain_argv) and not E2E and not e2e and not
  missing_tool_fails" -q -> 9 passed, 101 deselected  EXIT=0
  (unit-only per brief: the excluded names use the live MockSteve fixture)
- slot_m4.sh ... pytest verify/test_zmap.py -k "tools_json or tool_number
  or holder" -q -> 3 passed, 123 deselected  EXIT=0
- slot_m4.sh ... pytest engine/test_post.py -q -> 35 passed  EXIT=31.43s
  (exit code 0; includes new test_cli_tools_json_redirects_table)
- git diff --numstat (non-test files): see below at each checkpoint.

## Changed test asserts (the only test rewritten, allowed by the TESTS
## exception - its assertion was exactly "a library-only tool is refused
## tool_not_in_table"):
connector/test_toollib.py::test_tl2_library_only_tool_refused
  OLD: assert err is not None and len(calls) == 0 ("library-only tool
       used: run proceeded ... must be refused before any")
       assert err["code"] == "tool_not_in_table"
       assert err["got"] == "lib-only-flat" and ROUGH in err["allowed"]
       assert err["next_step"].startswith("add this tool to
         tools/x7_tools.json")
       assert len(calls) == 0
  NEW: assert calls ("a library-only tool with complete geometry must
       run"); result["tool"]["diameter_mm"] == 12.686; zmap argv
       --dia == "12.6860" and --tools-json = effective table containing
       "lib-only-flat"; THEN the same tool with holder/stickout_mm = None:
       assert err["code"] == "tool_not_in_table", err["got"] ==
       "lib-only-flat", ROUGH in err["allowed"], calls == [] (refused
       before any engine work). The unused-library-only-tool tail is
       unchanged.

## Byte-identity (item 4b) - scratch/bi_check.sh via slot_m4.sh:
  POST BYTE-IDENTICAL
  ZMAP JSON BYTE-IDENTICAL
  EXIT_BI=0
  (baseline 98a5706 extracted read-only with `git archive` into
  scratch/base - no checkout/restore; same fixture, both runs without
  --tools-json. The ONLY raw-diff line was the module-relative default
  table path inside zmap's "holder unknown" reason string (scratch/base/
  tools/... vs repo tools/...), inherent to running the baseline from a
  different directory; masked run-root prefixes -> byte-identical. The
  post .nc compared byte-identical with NO masking.)

## Slot congestion note: at ~13:15 the slot lane was held by another
session's ZG2 judging job (slot_m4.sh ... zg2_judge.py, started 12:29,
still running). My mutation run queued and exceeded a 10 min wait; the
lock files were NOT touched (per LOCKS). Retrying; if the lane stays busy
the mutation (fake-spawn tests only, no engine, no zmap - same nature as
the directly-runnable test_toollib suite) will run directly, recorded.

## numstat at this checkpoint: connector/runner.py 35 11 | engine/cli.py
16 0 | verify/zmap.py unchanged. (adds+dels = 62)

## Mutation (item 4) - scratch/mutation.sh via slot_m4.sh, scratch copy
## (mut/) reverted afterwards (rm -rf scratch/mut). Mutation: the runner's
## _table_file()/_tools_json_args() pass/passes the REPO table instead of
## the effective one. Output (pasted):
##   mutation applied: runner reads/passes the repo table
##   MUTATED RUN EXIT=1
##     assert _opt(z, "--dia") == "11.1110"       # the library's diameter
##     AssertionError: assert '12.6860' == '11.1110'
##       - 11.1110
##       + 12.6860
##   FAILED mut/connector/test_tlg1.py::test_library_only_tool_judged_by_table_diameter
##   FAILED mut/connector/test_tlg1.py::test_every_engine_call_reads_the_effective_table
##   2 failed in 0.13s
## -> test (a) fails BY THE MEASURED DIAMETER (repo 12.6860 instead of the
## library's 11.1110); the argv/table test fails naming the repo table path
## where tools_effective.json is required. Reverted: worktree tests re-run
## green below.

## FINAL TEST RECORD (all against the final sources; exit codes pasted)
- slot_m4.sh /opt/homebrew/bin/python3 -m pytest connector/test_tlg1.py
  connector/test_toollib.py -q  ->  41 passed  EXIT=0
- slot_m4.sh ... connector/test_connector.py -k "(tool or table or tl2 or
  rest_chain_argv) and not E2E and not e2e and not missing_tool_fails" -q
  ->  9 passed, 101 deselected  EXIT=0   (unit-only: the excluded names use
  the live MockSteve fixture; *_e2e_* excluded per brief)
- slot_m4.sh ... verify/test_zmap.py -k "tools_json or tool_number or
  holder" -q  ->  3 passed, 123 deselected  EXIT=0
- slot_m4.sh ... engine/test_post.py -q  ->  35 passed  EXIT=0
  (includes new test_cli_tools_json_redirects_table)
- slot_m4.sh bash scratch/bi_check.sh  ->  POST BYTE-IDENTICAL / ZMAP JSON
  BYTE-IDENTICAL  EXIT=0
- slot_m4.sh bash scratch/mutation.sh  ->  MUTATED RUN EXIT=1 (both (a)
  tests fail as intended)  EXIT_WRAP=0
- direct (fast connector suites, allowed directly): pytest
  connector/test_toollib.py connector/test_track2.py
  connector/test_panel_inputs.py connector/test_tlg1.py -q
  ->  80 passed  EXIT_FAST=0
- Full suite NOT run (supervisor's job, per brief).

## EVERY touched call site (file:line after edits)
engine/cli.py
  :387-388  rough  --tools-json added
  :423-424  post   --tools-json added
  :516-517  finish --tools-json added (covers rest finish)
  :521-529  main(): --tools-json redirects engine.finish.TOOL_TABLE_PATH
            (cmd finish) or engine.post_lnc.TOOL_TABLE_PATH (post, rough
            --post lnc lookup); both read at call time. prepare reads no
            tool table -> deliberately no flag there and nothing passed.
connector/runner.py
  :8        import hashlib
  :329-334  _table_record() (path + sha256 of the effective table)
  :344-376  _check_library_geometry rework (item 3; :368 missing-fields
            block; tool_not_in_table only for incomplete library geometry;
            tool_geometry_mismatch unchanged)
  NEW engine calls given the effective table:
  :499      rough (run)              :996   rough (slope chain)
  :1041     finish                   :1174  rest finish
  :1053     post (argv_fp +=)        :1197  rest post (argv_rp +=)
  already carried it (unchanged): :555 zmap(run), :743 zmap(check_program),
  :1088 zmap(rough), :1111 zmap(finish), :1232 zmap(rest)
  check.json / run record name the table: :561+:592 (rough),
  :786+:819 (check_program), :1264+:1354 (slope chain)
  not given a table (none exists / none read): run_measure prepare (:614),
  prepare calls (:467, :684, :935), heightfield.py calls (TOOL_R only),
  probe_clcheck.py calls (diameter argument; file not editable here).
verify/zmap.py  UNCHANGED - 0 lines (see Changes).
connector/toollib.py  UNTOUCHED (renumber/job tables never touched).

## New tests
- connector/test_tlg1.py (NEW): test_every_engine_call_reads_the_effective_
  table, test_library_only_tool_runs_with_its_own_geometry,
  test_library_only_tool_judged_by_table_diameter (mutation-sensitive),
  test_incomplete_library_geometry_refused_before_engine,
  test_library_geometry_mismatch_still_refused,
  test_real_post_and_zmap_read_the_effective_table (ONE real engine.cli
  post + ONE real verify.zmap call through slot_m4.sh: posted program
  T50/H50 + "D=7.777" and zmap tool dia 7.777 + holder BT30-ER20-60 all
  from the effective table; without --tools-json the tool is refused /
  holder unknown).
- engine/test_post.py: test_cli_tools_json_redirects_table (appended).

## Budget / line count
git diff --numstat (final):
  35	11	connector/runner.py
  16	0	engine/cli.py
  (verify/zmap.py unchanged; test files: test_toollib.py 24/14,
  engine/test_post.py 32/0, connector/test_tlg1.py new - excluded)
Non-test changed lines: 46 + 16 = 62 (adds+dels; 51 pure additions) vs
budget <= 60, stop ~75 -> 2 over budget, reported here, far under 75.
(prepare --tools-json was cut to stay near budget: prepare reads no tool
table, so the ceremony buys nothing; every table-reading call carries it.)

## Notes / deviations
- opencode.json shows as modified in git status - PRE-EXISTING at session
  start, NOT touched by this task (brief forbids editing it).
- The --tools-json redirect is a per-process module-constant override in
  the CLI process; every runner engine call is its own subprocess, so no
  bleed between calls.
- Slot lane was briefly held by another session's ZG2 job (~13:15); the
  queued mutation run was retried after the lane freed. Lock files were
  never touched.
- No commits made.

## Correction addendum (exact line numbers supersede earlier approximations)
- runner.py: _table_record :329-334; _check_library_geometry :344-376;
  NEW table-carrying engine calls: rough :499 (argv_r, list at :481),
  rough :996 (argv, :978), finish :1041 (:1028), post :1053 (argv_fp,
  :1048), rest finish :1174 (argv_rest, :1157), rest post :1197 (argv_rp,
  :1189). prepare calls WITHOUT a table arg (reads no tool table): :461,
  :607 (run_measure), :684, :927.
- Slot congestion was ~12:25-12:40 MST (not 13:15 as first written).
- Session end `date`: Sun Oct 25 12:46 MST 2026 (inside the 2 h cap).
  Task complete: items 1-5 implemented and tested; results file finished;
  nothing committed; scratch/ holds bi_check.sh, mutation.sh (mut/ reverted).
