# FE5e results (change + test; judge NOT run — supervisor runs out/fe5_judge.py)

Branch fe5 @ e40f664 + this session's uncommitted work. NOT committed (per brief).
This session ran ONLY the synthetic test block via slot_m4.sh; no fe5_judge.py,
no Core Front / interim-model engine run, no zmap job was executed here.

## Change (engine/finish.py, +83/-4; engine/test_finish.py +47; total 130 lines)

1. **New helper `_fe5_pick_ramp(live, P, s, tan)`** (finish.py, right after
   `_ramp_entry`): returns the SMALLEST ramp length L along the available run
   whose ramp TOP is clear of the live stock — `live.disk_depth(rv[0]) <=
   RAMP_TRIGGER` (0.25). Candidates are the pass's own vertices (the ramp
   emits those; `_ramp_entry`'s top at u = s[i] is exactly vertex i raised to
   max(vz, z0 + s[i]*tan), so no new CL lookup). A clear top also clears the
   link's vertical descent column onto rv[0] (depth only grows downward).
   If no vertex on the run clears, it tries the pass's OTHER end (reverse,
   same rule; a shallow reversed start returns L = 0.0, flip = True).
   Returns `(L, flip)`; `(None, False)` when neither end clears.
2. **FE5 block in `finish()`**: `L = d / tan_ramp` (P0-only sizing, the
   FE5d defect) replaced by `L, flip = _fe5_pick_ramp(live, P, s, tan_ramp)`.
   flip reverses the pass (recomputes s/d/total) before ramping. If
   `L is None`: entry left exactly as today (L = L0 = d/tan, fail closed so
   ZB must still fail on it) and recorded in `fe5_top_unresolved`
   [x, y, z, d]. Ramp angle untouched: 2 deg, never steeper, never a plunge.
3. **Ramp-chord stock recording (ZE2 prep)**: for every ramped entry, the
   max `live.disk_depth` along the ramp polyline (0.5 mm sampling, measured
   BEFORE stamping) goes to `fe5_chord_depths`; stats gain
   `fe5_top_unresolved_n`, `fe5_top_unresolved` ([:40]),
   `fe5_chord_max_depth` ([:40]) and `fe5_chord_max_depth_max`.
   The FE5d diag walrus (`u := min(L, total)`) became the plain `u` now
   defined by the new flow.

## Test (engine/test_finish.py, WIP from earlier attempt, kept as-is)

`test_fe5e_ramp_top_clear_of_ridge`: shallow P0 (live depth 0.299, ramp
L0 = d/tan = 8.6 mm) whose ramp top lands under a standing ridge (2.0 mm
of stock above it — the line-52593 shape); asserts `_fe5_pick_ramp` returns
a longer L whose top is clear (disk_depth <= 0.25, verified via
`_ramp_entry(P, s, tan, L)[0]`), and `(None, False)` when a ridge covers the
whole run (unresolved path). Registered in the `__main__` test list.

## Numbers produced this session (all commands below, VibeCAD python)

- AFTER (worktree code): **exit 0** — `fe5e ridge: d=0.299 L0=8.6 -> L=15.0
  clear; all-ridge unresolved` (pick chose vertex s = 15.0 mm > L0 = 8.6).
- **Fail-on-e40f664 proof: exit 1** — `ImportError: cannot import name
  '_fe5_pick_ramp' from 'engine.finish'` (e40f664 has no ramp-top check at
  all; the test exercises exactly the missing logic). Verified against a
  `git archive e40f664` extract in the scratchpad (worktree untouched — no
  checkout/restore used).
- Full `engine/test_finish.py` on AFTER code: **exit 0**, 28 tests OK,
  `test_fe5e_ramp_top_clear_of_ridge OK in 0.0s`, ALL FINISH TESTS PASSED.
- `py_compile` of finish.py + test_finish.py: clean.

## Exact commands

    SCRATCH=/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad
    # single test + e40f664 fail-proof (steps 1-2 of $SCRATCH/fe5e_test.sh), then:
    cd /Users/James/ai-sandbox/stevecam-fe5 && nohup $SCRATCH/slot_m4.sh \
      $SCRATCH/fe5e_test.sh > out/fe5e_slot_test.log 2>&1 &
    # log: out/fe5e_slot_test.log (AFTER_new_test_exit=0, BEFORE_new_test_exit=1,
    #       AFTER_full_test_finish_exit=0)

## Not done here (supervisor / judge scope, per instruction)

out/fe5_judge.py BEFORE/AFTER runs (ZB counts/max, remaining ZB entries,
zmap gates, clcheck, cycle times, fe5_top_unresolved / fe5_chord_max_depth on
the real part), scripts/check_fixtures.py, engine/test_engine.py, the pytest
verify-connector run, and the final regenerate-and-cmp: none executed in this
session (all are Core Front / zmap judge jobs the supervisor runs).
