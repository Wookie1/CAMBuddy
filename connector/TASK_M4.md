# Task M4: connector runs must FAIL on any failed gate (connector/ only). Do not commit; mock STEVE only.
Every action (adaptive_rough, slope_split_finish) runs its zmap gate itself and reports the run FAILED (state failed,
clear error) when zmap gouges > 0, rapid collisions > 0, probe_clcheck > 0 (finish), or - once verify/zmap.py has
the shank/over-flute check (Task Z2) - shank or over-flute hits > 0. A failed run must never upload only a .nc: either
upload nothing but check.json/preview.png for diagnosis, or no files; never a postable program.
Tests (mock STEVE): a deliberately gouging program (inject via a test hook / monkeypatched engine output) -> run
failed, no .nc uploaded; a clean run still succeeds. Keep all connector tests passing.

## Review (supervisor) - redo these, keep the rest
Rejected:
1. NO bypass switch in production code: remove STEVECAM_SKIP_GATES entirely. Gates always run.
2. Do NOT relax test assertions (restore `rapid_collisions["rough"] == 0`). The e2e synthetic part showing rough rapid
   collisions is a REAL engine finding: report it (which part, how many, first line, XY) in connector/GATES_NOTES.md and
   mark only those e2e assertions that depend on clean engine output as expected-failure (pytest.mark.xfail with
   strict=True and reason "engine rough rapid collision on synth_pocket, see GATES_NOTES.md"), so they flip to failures
   the moment the engine is fixed. The gate itself must make such a run FAIL.
3. Keep engine/probe_clcheck.py backward compatible: the old CLI `probe_clcheck.py <ngc> <step_mm>` (6 mm ball, the
   repo STL) and its text output must still work unchanged; add your form as optional flags
   (--stl, --dia, --json). Supervisor scripts depend on the old form.
Kept: _check_zmap_gates, the corrected probe path, TestGateFail (gouge / over-flute / rapid collision -> failed, no .nc).
Run /opt/homebrew/bin/python3 -m pytest connector -q and print the summary. Do not commit.
