# FE5fc RESULTS - finish the fragment trim (on-grid skip vertices) + never plunge a one-point pass

Branch fe5 @ 0a601fc (on top of the FE5f-b WIP f2e0c10), baseline 1f499f5.
NOT committed, per brief. No locks created/removed/edited; no Core Front
engine or zmap job; every test ran through the small-test lane slot_m4.sh
(ENGINE_WORKERS<=4); no G-code printed anywhere (stats/assertions only).

## 1. Line count vs 1f499f5 (`git diff --numstat 1f499f5`)

| file | adds | dels | role |
|---|---|---|---|
| engine/finish.py | 47 | 6 | impl - **53** non-test lines (<= 55 budget; the f2e0c10 WIP was 27) |
| engine/test_finish.py | +327 | 0 | tests (not counted; includes the f2e0c10 test WIP) |

## 2. Change (engine/finish.py only, per LOCKS)

1. FE5f-b finished - never invent a depth (task item 1):
   - engine/finish.py:2354-2359 - the trimmed fragment's vertices are now
     recorded with the MEASURED live depth only; the f2e0c10 fabrication
     `dq if math.isfinite(dq) else float(d)` (entry depth pasted onto
     off-grid vertices) is gone.
   - engine/finish.py:2521-2522 - the raw report `stats["fe5_skip_pts"]`
     exposes ONLY on-grid (finite live depth) fragment vertices. The
     clusters still receive every recorded position (a vertex fully off
     the stock grid carries its honest inf - "cannot tell", not an
     invented number) so a pass skipped entirely off-grid still yields a
     non-empty skip-area report, which the mandated test_fe5fb_* tests
     require (their only skipped passes in that geometry are the outer
     pad rows beyond the stock grid - verified: at 1f499f5 that geometry
     skips exactly those 12 passes, cluster at (-0.112, -22.736), 48
     vertices, all off-grid).
2. Never plunge a one-point / zero-length pass (task item 2):
   - engine/finish.py:2274-2287 - `len(pth) < 2`: the point's live depth
     is measured; if it exceeds ZB_FLOOR_BALL (0.5) the pass is SKIPPED
     (counted in fe5_skipped_n, its vertex clustered) instead of being
     linked-to and plunged straight down (the T33 (-23.64,1.68) 1.06 mm
     plunge); shallower ones stay exactly as before (unchanged). An
     off-grid point (inf = cannot tell) counts as deeper than the floor -
     fail-closed, never plunged.
   - engine/finish.py:2301-2308 - same for a zero-length pass
     (`total < 1e-9`, previously it bypassed every FE5e/FE5f check via
     the `total >= 1e-9` gate at :2309 and was emitted unchanged).
   - The ZB floor was NOT lowered; nothing legally enterable (ramped or
     shallow) is skipped; verify/ and opencode.json untouched (their
     pre-existing worktree modifications were left exactly as found).

## 3. Tests (all via slot_m4.sh small-test lane, ENGINE_WORKERS=4)

No existing test or assertion was edited; the new test is
`test_fe5fc_buried_ends_keep_middle` (engine/test_finish.py, registered in
the __main__ runner). pytest is not installed for the VibeCAD python3.11,
so tests ran through an in-process runner with per-test exit propagation.

| run | result | exit |
|---|---|---|
| test_fe5f_skip_bore_entries (unchanged) | PASS - "skipped 16 passes in 1 cluster(s) at [0.0, -0.466] (max live depth 5.90 mm)" | 0 |
| test_fe5fb_fragment_trim_keeps_surface (unchanged; was FAILING at session start on 48 off-grid inf skip vertices) | PASS - "skipped 12 passes/fragments in 1 cluster(s); surface beyond the bores fully covered" | 0 |
| test_fe5fb_real_bore_surface_kept (unchanged; was FAILING at session start) | PASS - "surface beyond the bore covered, skips 23" | 0 |
| NEW test_fe5fc_buried_ends_keep_middle | PASS - "skipped 28, hill kept (1571 mm cut, 400 finite skip vertices)" | 0 |
| full engine/test_finish.py | ALL FINISH TESTS PASSED | 0 |
| py_compile finish.py / test_finish.py | OK | 0 |

## 4. Fail-on-1f499f5 proof (by assertion, `git archive 1f499f5` extract - never checkout)

`git archive 1f499f5 | tar -x -C <tmp>` + copy of the NEW test_finish.py:

    FAIL-BY-ASSERTION on 1f499f5: FE5fc: 77 hill cells uncovered (whole
    passes dropped): [(-2.0, -5.0, 4.01), (-1.0, -5.0, 4.01), (0.0, -5.0,
    4.01), (1.0, ...)]
    exit code 1

Scenario: long raster passes over a hill prism (top z 13, ends z 10) with
live stock +2.0 mm at BOTH ends and only +0.3 over the hill: whole-pass
sizing from either buried end can never clear (every vertex sits 0.3 under
the allowance, the 2 deg ramp cannot beat the hill), so 1f499f5 drops each
pass WHOLE - the hill stays unfinished (77/60-cell grid uncovered, nearest
cut 4.01 mm). After the change FE5f-b's re-entry scan finds the legal
suffix (a ramp based on a hill vertex clears within ~1.5 mm), keeps the
middle, trims only the buried fragments: all hill cells covered within
1 mm, no vertical G1 descent lands deeper than 0.5 mm into live stock,
skips counted + clustered, and every raw skip vertex has a finite depth.

## 5. Not done / notes

- The NEW one-point-pass test from the brief could NOT be constructed
  through the public finish() in this session. Attempts: (a) near-vertical
  needles / cone tips (expected tiny waterline contours) - the deep passes
  arrive as len>=2 contours, so FE5f already whole-drops them at 1f499f5
  (no plunge there: verified plunges=[] on the baseline extract) and they
  cannot make the test fail-by-assertion there; (b) floor_z isolation of a
  thin fin to a single CL column - produced zero passes (n_moves=0), the
  ball radius smears the CL over ~R so an isolated single-column above-
  floor island is not reachable with synthetic meshes at this sampling.
  The len<2 / zero-length branch itself IS implemented (section 2 item 2)
  and the full suite stays green; the T33 one-point plunge case is
  covered by the supervisor's own chain replay.
- The task line "no emitted move enters stock deeper than 0.5 axially" is
  implemented/asserted per the established FE5f convention (every ENTRY -
  the bottom of a vertical G1 descent - lands at live depth <= 0.5 mm;
  mid-pass descents along verified paths are FE5e traversal, out of
  scope, as in test_fe5f_skip_bore_entries).
- No stuck slots observed; no lock was touched.
- Stopping here as instructed; nothing committed.
