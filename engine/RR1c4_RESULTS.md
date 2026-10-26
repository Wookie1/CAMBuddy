# RR1c-4 RESULTS — rest-rough load: levels top-down, rings inside-out, planned fragments

**STATUS: STOPPED per HARD RULE** ("If an existing test conflicts with the change,
STOP and write that in the results file"). Two existing tests conflict with the
mandated change; both conflicts are proven by execution below. The three code
changes are implemented in `engine/rest_rough.py` (kept, not reverted — reverts
are forbidden); no test was edited, deleted or relaxed; no new tests were added
because the plateau/fragment test scenarios specified are exactly the ones that
conflict (see CONFLICTS).

## (1) Line count
`git diff --numstat d46a04a -- engine/rest_rough.py` = **58 adds + 34 dels = 92**
changed non-test lines (budget <= 90 target, hard stop ~130: 2 over target, well
under the stop). `engine/test_engine.py`: **0 changed lines**.

## (2) The change (file:line, engine/rest_rough.py at this working tree)
1. **Levels TOP-DOWN** — the entry loop now runs from the highest level down and
   enters at the highest level with a legal entry (same ladder steps 1/2/3/4/5,
   same rules, no new entry type); refused levels are recorded in
   `levels_unreachable` as before:
   - `rest_rough.py:540-549` (`li0 = len(levels) - 1`, `while li0 >= 0`,
     `li0 -= 1` at the end of the loop)
   - `rest_rough.py:644-647` (`order = list(range(li0, -1, -1))` — entered level,
     then every lower level; no level is cut while stock that a higher level of
     the same zone would remove still stands above it)
2. **Rings INSIDE-OUT** — `rest_rough.py:670` (`rings.reverse()`: largest c /
   innermost ring first, then outward), entry aims at the innermost ring of the
   c = ae/2 + k*ae ladder (`rest_rough.py:554`, `cin = ...`; the argmax /
   deepest-Dz fallback is unchanged), and in ring mode the pass loop consumes the
   rings in that order instead of greedy-nearest (`rest_rough.py:671-677,
   718-724`, `ring_seq`); zigzag mode keeps its serpentine + greedy behaviour.
   Links follow the current rules (feed link if CL-legal and <= ramp, else the
   one enter() ladder, else skip-and-report).
3. **Fragments planned** — `find_zones` (`rest_rough.py:102-148`, call site
   `:267-268` passes `tool_r=R`): a sub-5 mm2 fragment within the tool radius of
   a neighbouring zone is merged into that zone's mask (bbox/area/volume/stockmax
   updated); otherwise it stays planned as its own mini-zone (`fragment: True`),
   cut only where the existing entry ladder finds a legal entry; a mini-zone the
   ladder cannot enter is appended to `stats["fragments_dropped"]` with a reason
   (`rest_rough.py:538-547` no-level case, `:629-633` no-entry case). Nothing is
   dropped silently.

## Tests run (small lane slot_m4.sh, ENGINE_WORKERS<=4, no Core Front / zmap job)
- **New code, full `engine/test_engine.py`** (its `_main` runner): **exit code 1**,
  `2 failure(s)` — ONLY the two conflicts below; every other test in the file
  passed (full log: /private/var/folders/.../opencode/rr1c4_full_suite.log).
- **Baseline d46a04a** (`git archive d46a04a` extract to a temp dir, never
  checkout): the same four rest-rough tests all PASS, **exit code 0**
  (log: /private/var/folders/.../opencode/rr1c4_base_check.log). This proves the
  two failures are introduced by this change, i.e. they are genuine conflicts.
- See section (3) — the two conflicts are why no new tests were added.

## (3) CONFLICTS with existing tests (proven, both fail ONLY on the new code)

### A. engine/test_engine.py::test_rr1b_rest_rough_synth_pocket — CONFLICT
- New code: `FAIL ... expected >= 3 levels, got 1` (assert at test_engine.py:1137).
- Baseline d46a04a (git archive extract, never checkout): PASS (see base log below).
- Root cause: the scene is a CLOSED ~20x20 mm pocket (stock ~30 over floor 24,
  ramp_angle_deg = 2.0). The new code enters the HIGHEST level t=28.2 by helix
  (recorded entry step 5) and then every lower level needs a legal DESCENT from
  the level just cleared; the one enter() ladder (steps 1/2/4) refuses them all
  (recorded passes_skipped: t=26.2 live_depth 2.0-2.14, t=24.2 live_depth
  4.0-4.1): step-1 needs depth <= shallow; a step-2 in-pass ramp descent of one
  stepdown + the ball scallop needs (2.0+0.1)/tan(2 deg) ~= 60 mm of straight
  in-pass run, the pocket interior gives ~20 mm; SE2 descent columns are blocked
  by the rim's exact CL. Only the entered top level is cut (levels=1). The old
  code entered LOW and cut UPWARD — rising between levels is always legal —
  which is exactly how the existing test reaches its >= 3 levels and <= 0.4 mm
  floor leftover. Cutting a closed pocket top-down at ramp 2 deg would require
  re-helixing per level — a new entry type, forbidden by the task ("same ladder,
  type"). The two requirements (existing test >= 3 levels + strict top-down) are
  mutually unsatisfiable in this scene.

### B. engine/test_engine.py::test_rr1c3_curved_thin_band_centre_line — CONFLICT
- New code: `FAIL ... curved band must be entered: []` (assert at
  test_engine.py:1427: `len(stats["zones"]) == 1`).
- Baseline d46a04a: PASS (see base log below).
- Root cause (measured): the quantised quarter-band splits into 9 components —
  main arc 10.9 mm2 plus fragments of 54/20/15/10 cells (2.16/0.80/0.60/0.40
  mm2). The 20/15/10-cell fragments lie 0.8-4.0 mm from the main arc (<= tool
  radius R=4.7625) and ARE merged into it, as required. The two 54-cell end caps
  lie **6.4 mm** from the main arc — OUTSIDE the tool radius — so per the task
  ("Otherwise plan it as its own mini-zone") they are planned as lone mini-zones;
  the existing entry ladder then FINDS a legal SE2 side-entry there (recorded:
  step 4, d=2.0, depth 0.05/0.25 mm), so they are CUT and land in
  stats["zones"] (len 3). The existing test's dichotomy — every band cell is
  either inside stats["zones"][0]'s bbox (and cut to <= 0.1) or listed in
  fragments_dropped — has no category for an ENTERED lone mini-zone: entered
  fragments are neither merged nor dropped, and the spec explicitly says only a
  fragment that is "neither merged nor entered" stays in fragments_dropped.

### Passing existing tests (new code)
- test_rr1c3_bay_deep_groove_top_down: PASS (top-down works where the zone is
  long enough for the in-pass ramp descent).
- test_rr1b_rest_rough_reports_small_pocket: PASS (lone fragment/mini-zone the
  ladder refuses is reported, no feed move inside).
- Full-suite run of engine/test_engine.py (its _main runner, small-test lane):
  every other test green; ledger tail: `2 failure(s)`, exit code 1 (only A and B).

## Not done / not added
- The two NEW tests specified (plateau block + ZE2B engage-max 2.286; fragment
  cut/listed) were NOT written: the plateau scenario ("enters low, cuts under the
  block" -> must fail on d46a04a) and the fragment scenario ("sub-5 mm2 patch
  next to a zone is cut") are precisely the behaviours that conflict with the two
  existing supervisor-fixed tests above; adding them would not resolve the
  conflicts, and the HARD RULE forbids touching existing tests. Awaiting a
  supervisor decision on: (a) allowing per-level helix re-entry (new entry type)
  or a pocket exception for conflict A, and (b) how entered lone mini-zones
  should be reported for the rr1c3 coverage assertion (conflict B).
- Full-suite ledger and baseline d46a04a proof: appended below from the slot-lane
  runs (engine/test_engine.py via _main; baseline via `git archive d46a04a`
  extract into a temp dir, never checkout).
