# Task TLG1: library tool geometry reaches the engine as well as the judges, through one effective table per run. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances, except connector tests whose
assertion is exactly "a library-only tool is refused tool_not_in_table" (item 3 changes that contract): list each one
you change with old/new assert in the results. Add NEW tests otherwise.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit opencode.json; verify/ never imports engine and engine never imports verify (both read the same JSON format);
NEVER touch tool renumbering logic (connector/toollib.py renumber/job tables).
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-tlg1/scratch/ - never /tmp.
RESULTS: create connector/TLG1_RESULTS.md and only ever APPEND to it.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit engine/cli.py, engine/finish.py (its table path/lookup only), verify/zmap.py, connector/runner.py and their test
files only. BUDGET: <= 60 changed non-test lines across those files vs 98a5706; STOP and report at ~75. FRESH session,
HARD CAP 2 h (run `date` at start). Worktree /Users/James/ai-sandbox/stevecam-tlg1, branch tlg1 at the commit
carrying this brief (= main 98a5706 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>. Fast connector suites (connector/test_track2.py, test_toollib.py,
test_panel_inputs.py) may run directly; anything that runs the engine or zmap goes through slot_m4.sh.
AT-RISK: connector/test_toollib.py, connector/test_track2.py, connector/test_connector.py -k "tool or table or tl2 or
rest_chain_argv" (unit ones only - no *_e2e_* / live tests), verify/test_zmap.py -k "tools_json or tool_number or
holder", engine/test_post.py, plus your new tests.

## Facts (supervisor, main 98a5706 - what ALREADY exists; build on it, do not duplicate it)
- connector/runner.py:316-326: with a library (cfg home) the runner writes the run's effective table to
  <run>/tools_effective.json (self.tools_path) and passes --tools-json <it> to EVERY verify.zmap call
  (_tools_json_args at :544, :728, :1068, :1091, :1210); check_tool_entry(..., self._table_file()) reads it.
- verify/zmap.py:2401 already has --tools-json (default TOOLS_JSON = the repo table), read at :140/:2520.
- connector/runner.py:340-366 (TL2 d3871ee) fails closed: a used library tool whose tool_id is NOT in the repo table
  -> tool_not_in_table; in the repo table with different geometry -> tool_geometry_mismatch. Reason it exists: the
  ENGINE only reads tools/x7_tools.json (engine/finish.py:118 path constant; cli.py post refuses unlisted tools at
  ~:240), so a library-only tool's geometry could never reach the engine.
## Change (coordinator spec)
1. Engine CLI accepts an explicit tool table path (--tools-json PATH) on every subcommand the runner calls (rough,
   finish, rest finish, post, ...); engine/finish.py's table lookup uses it. With NO path given, today's repo table
   is used and every output is byte-identical (test it).
2. The runner passes the SAME effective table (tools_effective.json) to EVERY engine call of the run, not only
   zmap. check.json (and the run record) name the table path and its sha256.
3. Fail-closed: a library tool used by a run must have every geometry field (dia, corner, flute, shank, holder,
   stickout) or the run is refused with the existing codes. tool_geometry_mismatch STAYS for a library tool whose
   tool_id IS in the repo table with different geometry. tool_not_in_table now applies ONLY when the library has no
   complete geometry for it (a library-only tool with complete geometry is now allowed).
4. Tests: (a) a library-only tool (complete geometry, tool_id not in the repo table) posts and is judged with ITS
   diameter: assert the engine argv/table, the posted program's tool comment and zmap's tool block all read the
   library diameter (runner subprocesses may be faked as connector/test_toollib.py _fake_spawn does, plus ONE real
   engine post + zmap call through slot_m4.sh). (b) default-path byte-identity: no --tools-json -> engine post output
   and zmap JSON byte-identical to 98a5706 on one fixture. Mutation (scratch copy, revert): the runner passes the
   repo table instead of the effective one; (a) must fail by the measured diameter (or holder/flute value). Record it.
5. List EVERY touched call site (file:line) in the results.
## connector/TLG1_RESULTS.md: the call-site list, changes with file:line, line count, any changed test asserts
(old/new), PASTED test exit codes, the mutation output, git diff --numstat. Then stop.
