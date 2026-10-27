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

---

# ADDENDUM FE5e-t results (this session, Thu Oct 22 2026)

Behavioural test through the PUBLIC finish() path - TEST ONLY, no engine
change, no commit. `git diff --stat 44e0a61 -- engine/finish.py
engine/entry_depth.py` is EMPTY; the only change is
`engine/test_finish.py` (+85 lines): new test
`test_fe5t_public_ramp_top_clear_of_ridge` (added after
`test_fe5e_ramp_top_clear_of_ridge`, also added to the __main__ runner).

## Scenario (small synthetic, NO Core Front / fe5_judge.py / zmap job)

Flat block 30x24 mm, floor_z 6.0, ball 6.0, stepover 1.5, ramp_angle_deg
2.0 (never steeper), --stock-from heightfield (cell 0.5, grid extends
4 mm past the block so edge disks read finite stock): base leave 0.2, a
shallow entry shelf (z 6.3 -> live depth ~0.3 > RAMP_TRIGGER at every
-X row start), and a standing leftover ridge (z 7.0) at x -8..-4 across
the whole raster. The FE5 ramp sized from P0 alone (L = 0.3/tan(2 deg)
~ 8.6 mm) lands its TOP at x ~ -6.43, z 6.3 -> ~0.7 mm UNDER the ridge
(the line-52593 defect reproduced at program level). The test replays the
estimator's LiveStock in emit order over the EMITTED moves and asserts
every entry landing strictly above the floor (vertical-descent bottom =
plunge onto a ramp top; horizontal arrival at ramp height) has live depth
<= 0.25 or appears in stats fe5_top_unresolved; sloped ramp-chord
vertices stay excluded (allowed, FE5e rule 4).

## Results (both runs, via slot_m4.sh)

- AFTER = worktree code (HEAD c342fcf; engine identical to 44e0a61):
  **PASS, exit 0** - `fe5t public: 9 entries ramped, 0 unresolved, tops
  clear (chord max depth 0.772)`. All 9 ramp tops sit clear of the live
  stock; the chord through the ridge (max 0.772) is the allowed <=15 deg
  descent recorded for ZE2.
- BEFORE = `git archive e40f664` extract in the scratchpad (worktree
  untouched - no checkout), same test file copied in: **FAIL BY
  ASSERTION, exit 1** - `AssertionError: FE5e-t: 9 buried ramp
  top/entry landing (max depth 0.700): [(-6.43, -12.0, 6.3, 0.7),
  (-6.43, -9.0, 6.3, 0.605), (-6.43, -6.0, 6.3, 0.605),
  (-6.43, -3.0, 6.3, 0.605)]` and there is no fe5_top_unresolved stat
  on e40f664 to report them. This is the FE5d defect itself: every
  forward row's P0-sized ramp top buried ~0.6-0.7 mm under the ridge.
- Full `engine/test_finish.py` on AFTER code: **exit 0**, 29 tests OK
  (28 before + the new one), `test_fe5t_public_ramp_top_clear_of_ridge
  OK in 0.2s`, ALL FINISH TESTS PASSED.
- `py_compile` of test_finish.py: clean.

## Exact commands

    SCRATCH=/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad
    # both runs in one script ($SCRATCH/fe5t_test.sh: 1 = AFTER single test,
    # 2 = same test on git archive e40f664 extract, must fail by assertion):
    cd /Users/James/ai-sandbox/stevecam-fe5 && nohup $SCRATCH/slot_m4.sh \
      $SCRATCH/fe5t_test.sh > out/oc_fe5t.log 2>&1 &
    # log: out/oc_fe5t.log (AFTER_fe5t_exit=0, BEFORE_fe5t_exit=1)
    cd /Users/James/ai-sandbox/stevecam-fe5 && nohup $SCRATCH/slot_m4.sh \
      /Applications/VibeCAD.app/Contents/Resources/bin/python \
      engine/test_finish.py > out/oc_fe5t_full.log 2>&1 &
    # log: out/oc_fe5t_full.log (ALL FINISH TESTS PASSED, 29 tests)

Not committed (per instruction). No Core Front, no fe5_judge.py, no zmap
job run in this session.
