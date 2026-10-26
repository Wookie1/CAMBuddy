# RR1c-3 results (rr1b worktree, base e206c56; not committed)

## (1) Line count vs e206c56
`git diff --numstat e206c56`:
- non-test: `engine/rest_rough.py` 78 adds / 9 dels = **87 changed lines** (budget <= 150, stop ~200);
  `engine/cli.py` untouched (no new parameter was needed).
- test: `engine/test_engine.py` +139 / -1 (two new tests + runner registration).

## (2) Changes

### Item 1 - thin level strips cut along their own centre line
`engine/rest_rough.py` (pass-path build, formerly :635-638): when a level has no offset rings and
`maxDz < ae/2`, the axis-aligned `zigzag_runs(reg, xs, ys, ae, 2*CELL)` fallback is replaced by the
ordered iso-polylines of the distance field at `c = max(maxDz/2, CELL/2)` from `march_level(Dz, xs, ys,
c_mid, comp=reg)` (rest_rough.py:650-666). Zig-zag stays only where it was briefed - step 3 zone entry
(runs >= D, rest_rough.py:557) and the non-thin no-rings fallback. Every centre-line point goes through
the same exact CL check as the passes: paths marked `clneed` are validated with `cl_ok_path` at the cut
level before any point is emitted, fail closed (rest_rough.py:731-745). This is the flank-band / T33 ZB
root cause (DIAG (a), (c)): the axis rows crossed the curved 1-2 cell strips in < min_run groups and cut
0 levels.

### Item 2 - levels top-down after entry
`engine/rest_rough.py:613-624`: the cut order is now `[li0] + (levels below li0, descending) + (levels
above li0, ascending)`. The entered level is cut first, then each deeper level - previously skipped by
`levels[li0:]` (DIAG (b): bays entered at t 38.965 never revisited t 36.965 / 36.365). For descent
levels (rest_rough.py:621-624, 683-718):
- no vertical drop at `prev` XY is ever emitted (the inter-level `g1` only feeds UP; a degenerate
  straight drop to a path starting below `prev` is also routed through the ladder);
- a direct diagonal link is allowed only when it stays at <= ramp_angle (in-pass, live depth ~ one
  stepdown instead of 3.3-3.9) and CL-legal along the line;
- otherwise the SAME one `enter()` ladder (steps 1/2/4) is used, with the step-2 ramp direction taken
  from the direction of travel FROM the just-cleared level, retried along the strip's own long axis
  (at a contour cap the tangent runs across the strip and a ramp cannot fit).

Zone-entry scan direction is deliberately UNCHANGED (deepest reachable level, steps 1-5): entering at
the deepest ladder-reachable level is what keeps test_rr1b_rest_rough_synth_pocket (wide deep pocket
entered by helix at its floor) and test_rr1c_narrow_pocket_side_entry (first entry must be step 4)
green - a highest-level-first scan would enter those zones by a shallow ramp/helix at a top level and
could not reach the floor (the 2 deg ramp needs ~ (depth-shallow)/tan2 deg ~ 107 mm at 4 mm depth,
longer than the pocket). For the bays of DIAG (b) the two are equivalent: the only ladder-enterable
level is the top one, and the descent phase now cuts the deeper groove levels from it.

### Item 3 - nothing else
No bore work (the three through-bores' no-entry report untouched), no ladder changes beyond using
`enter()` per level.

## (3) Tests
Two new tests in `engine/test_engine.py` (registered in `_main()`):
- `test_rr1c3_curved_thin_band_centre_line`: quarter-ring rest band (r 29.8-30.2 on a flat-topped
  block, ~1 cell wide after resample, r_max < ae/2) - asserts the zone is entered, cut-feed length
  along the band >= 80 % of its 47.1 mm centre line, validate_exact 0, every scored entry <= 0.5;
- `test_rr1c3_bay_deep_groove_top_down`: bay with a concave (rho 12) floor - the deepest level is a
  ~0.4 mm wide valley strip (r_max_cl 0.2) under a ~10 mm wide upper level - asserts both levels cut
  (`zones[0]["levels"] >= 2`), LiveStock depth at the groove floor <= 0.5 mm after the program
  (e206c56 leaves ~0.9-2.0 mm there), validate_exact 0, every entry <= 0.5.

## (4) Pending at the 2 h CAP - test execution queued, not yet run
The machine was held continuously by the supervisor's BS1a3 chain (slot.sh, 2 h 36 min at the time this
cap hit: failproof, fixtures, full test_engine, test_finish, pytest, then a final CF regeneration plus a
Core Front zmap judge still running at cap time). slot_m4.sh correctly refuses to overlap those
python/zmap jobs, and the HARD RULES forbid bypassing that. Per the 2 h CAP the work is stopped here
with the test run still queued:

- queued job (launched ~21:00, still waiting for the slot):
  `/private/tmp/claude-502/.../scratchpad/slot_m4.sh bash
  /var/folders/zb/2kw4kjs525j70pvjdhhlvxp00000gp/T/opencode/rr1c3_runall.sh`
- its output will land in `/var/folders/zb/2kw4kjs525j70pvjdhhlvxp00000gp/T/opencode/rr1c3_all.log`
  and runs, in order: (a) fail-by-assertion proof of both new tests on e206c56 extracted with
  `git archive` (no checkout), (b) the two new tests on this working tree, (c) full
  `engine/test_engine.py`, (d) `engine/test_finish.py`; ends with `ALLSTEPS-DONE`.
  The supervisor can read that log when the slot frees; no re-launch is needed.

Why the two new tests must fail on e206c56 by construction:
- curved band: the old thin-strip fallback `zigzag_runs(reg, xs, ys, ae, 2*CELL)` lays axis-aligned
  rows across the quarter-ring; rows cross the ~1-cell-wide arc in chords of ~1-4 mm, totalling well
  under the 80 % x 47.1 mm assertion (DIAG probe: curved flank strips give 0 runs; the straight
  synthetic band only passed because it is axis-aligned);
- bay groove: old pass loop ran `levels[li0:]` (rest_rough.py:614 at e206c56) - with li0 = the entered
  upper level, the floor-hugging valley level is never cut; stamping the old program leaves
  ~0.9-2.0 mm live depth at the valley line (disk_depth reads ~28.2 stock top vs the 26.2 target),
  failing both the `levels >= 2` and the <= 0.5 mm assertions.

Static checks done within the cap: `ast.parse` clean on both edited files; diff budget 87 non-test lines
(<= 150); verify/, opencode.json, engine/entry_depth.py, engine/test_entry_depth.py untouched; no
existing test assertion changed (only the `_main()` registration tuple grew by two names); nothing
committed. Note: the supervisor's `m4model.busy` flag (created by queue_rr1c3.sh for this session) was
removed while cleaning a stale slot lock; the queue script removes it at completion anyway.

