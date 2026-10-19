# Task H1: tests for the new "holder unknown" gate (connector/ + verify/ tests). Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; never weaken the gate, no bypass flags, never delete tests.
The supervisor added (commit fbd4af6): zmap reports "holder": {"status": "checked"|"holder unknown"|"not requested",
"name", "stickout_mm", "dimension_source"}; the connector now FAILS a run unless holder status is "checked"
(connector/runner.py _check_zmap_gates). T13 got holder "BT30-ER32-70" (estimated, Steve catalogue item bt30_er32).
5 tests now fail - correctly, because the fixtures use tools with no holder:
- verify/test_zmap.py::test_holder_resolve_from_table: read why it fails (likely T13 now resolves; update the expectation
  to the new table, and add an assertion that an unknown tool number gives status "holder unknown").
- connector e2e tests (TestEndToEnd::test_enroll_confirm_run, TestSlopeSplitFinish::test_e2e_chain_rough_then_finish,
  TestWarningsInCheckJson::test_rough/slope_check_json_has_warnings) use tool_number 1 (not in tools/x7_tools.json).
  Fix the FIXTURES, not the gate: use real table tools whose holder is known (rough: T13 flat 12.686, or T20/T31 balls for
  finishing with their real diameters 9.525 / 5.958) and make tool type/diameter match the table entry. If the synthetic
  part is too small for those tools, enlarge the test part (connector/testdata) rather than weakening anything.
- Add tests: a run with a tool number that has no holder outline FAILS with "holder unknown" and uploads no .nc; check.json
  carries holder.dimension_source "estimated" for T13.
Run /opt/homebrew/bin/python3 -m pytest verify connector -q until all pass. Short outputs.
