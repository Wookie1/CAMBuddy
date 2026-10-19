# Task V1: engagement-spike and plunge reports (verify/ + connector check.json). REPORT-ONLY. Do not commit.
Rules: no MCP, no questions, never contact the internet, probes in verify/probe_*.py. verify/ must stay numpy-only
and independent of engine/ (never import engine or ocl). No bypass switches, never weaken existing tests.
1. In verify/zmap.py (or a new verify/engagement.py used by zmap): for every cutting move, radial engagement against
   the LIVE simulated stock = width of material the tool footprint removes measured perpendicular to the direction
   of travel (or the engaged arc angle converted to an equivalent radial width; document which). Record per-move
   max engagement and where. Flag moves over a threshold (--engage-max mm; default 1.5 x --optimal-load if given,
   else off) with line numbers and XY; summary: count, max, top 10 spots (line, XY, mm).
2. Plunge flag: a feed move with a downward Z component that enters stock (removes material while descending) is
   flagged unless it is a helix/ramp at or under --ramp-angle (deg, default 3.0): report line numbers, XY, angle,
   depth into stock. Rapids that end inside stock are already rapid collisions - just cross-reference them.
3. Tests (synthetic): straight full-width slot -> engagement = D, flagged; 90-degree inside corner of a constant
   radial-engagement path -> spike flagged at the corner; helix entry at 2 deg -> not flagged; straight vertical
   plunge into stock -> flagged. Keep all existing verify tests passing: /opt/homebrew/bin/python3 -m pytest verify -q.
4. Connector: add both reports to check.json under "warnings" (never fail a run on them). Keep connector tests
   passing: /opt/homebrew/bin/python3 -m pytest connector -q.
Do NOT run Core Front or the test block; the supervisor does. Short outputs.

## Review (supervisor) - finish these
Done and kept: engagement + plunge reports in zmap with the 4 synthetic tests (23 verify tests pass).
Missing:
1. zmap CLI flags: --engage-max MM, --optimal-load MM (default threshold 1.5 x optimal load when given), --ramp-angle DEG
   (default 3.0); both reports in the output JSON. Add a CLI-level test (subprocess or main() call).
2. Item 4: connector/runner.py adds both reports to check.json under "warnings" for adaptive_rough and both stages of
   slope_split_finish, passing --optimal-load from the action inputs and --ramp-angle default; warnings NEVER fail a
   run. Test with the mock: check.json contains warnings.engagement and warnings.plunge. Note: on main the e2e rough
   currently fails on purpose (engine bug R3, another track) - do not change gates or relax tests; if an e2e test fails
   for that reason, leave it failing and say so.
Run /opt/homebrew/bin/python3 -m pytest verify -q and connector -q. Do not commit.

## Review 2 (supervisor) - real bugs, fix these
1. Engagement = inf on a real program: zmap on stevecam-finish/out/test_block_roughR2.ngc (flat 12.686, stock -50 50
   -40 40 0 38, --optimal-load 2.032) reports engagement max_mm inf and 18,673 flags; top spots lines 18-20 (the helix
   entry near (-29.5, -23.6)). Engagement must be finite and physically bounded (0 <= engagement <= tool diameter) for
   every move, including helix/ramp segments, zero-XY-length moves (pure Z), and arcs. Add tests for a helix entry and a
   pure plunge asserting finite values <= D.
2. Never emit inf/NaN into JSON (check.json must be strict JSON): clamp or use null with a reason.
3. On this branch connector test_e2e_chain_rough_then_finish now FAILS (it passed on main bf95a93 before your change):
   find and fix the cause (likely the inf). All connector tests must pass again. Add a connector test asserting
   check.json has warnings.engagement and warnings.plunge for both actions (adaptive_rough too, not only the chain).
4. The finish stage should not use the roughing optimal load as its engagement threshold; use the finish stepover
   (or leave the threshold off for finishing) - say which.
Run verify and connector tests. Do not commit.

## Review 3 (supervisor)
HARD RULE: never run git stash, git checkout <file|rev>, git reset, git restore or git clean. Last session lost its work
that way (recovered by the supervisor; your current tree = V1b + part of V1c). Edit files in place only.
State now: engagement is finite (clamped to D), verify 27 pass. Connector: 2 tests fail because the slope_split_finish
chain run ends 'failed' (test_e2e_chain_rough_then_finish, test_slope_check_json_has_warnings). They passed on the
branch base before your zmap changes, so the cause is in your changes (runner zmap args for the ball finish stage, a
zmap exit code, or non-strict JSON). Find it: print the run's error (the runner catches EngineError -> failed with
message; add a temporary print or read the work dir ~/.stevecam-test.../runs/<id>/ logs from the test's temp HOME), fix
the cause, keep warnings report-only. Then: all connector + verify tests pass. Do not commit.
