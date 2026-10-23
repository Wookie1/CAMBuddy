# FE5f RESULTS - skip (never plunge) unresolvable finish/rest entries; report skipped area

Session: continuation of the FE5f WIP cut off by the model-server outage
(branch fe5 @ 1fac500; baseline e773afa = FE5e + FE5e-t, verified with
`git cat-file -t e773afa` -> commit). NOT committed, per brief.

## 1. Line count vs e773afa (`git diff --numstat e773afa`)

| file | adds | dels | role |
|---|---|---|---|
| engine/finish.py | 57 | 3 | impl |
| connector/runner.py | 13 | 0 | summary only |
| engine/test_finish.py | 106 | 0 | test |

Non-test changed lines: **73** (<= 80 budget). Test lines reported separately.

## 2. Change

WIP review (previous session): the skip was keyed on the entry depth `d` at
the (possibly flipped) pass start only. Debugging with FE5_TRACK + a replay
dump showed that misses the dominant case: an unresolved entry whose start is
shallow (d <= 0.5, fail-closed kept) but whose ramp top - where the link's
vertical plunge actually lands - is buried in the bore (observed 0.989 mm >
floor). Fixed the gate to check BOTH depths.

- engine/finish.py:109 `ZB_FLOOR_BALL = 0.5` - mirror of zmap
  BALL_AXIAL_FLOOR (never lowered).
- engine/finish.py:1856 `_fe5_cluster_skips(pts, merge_r)` - greedy merge of
  skipped vertices into clusters within merge_r = 2 x tool D; each cluster
  reports centre, bbox, max live depth, bbox area, n.
- engine/finish.py:2308-2331 - in the FE5e entry loop, when no ramp top
  clears on either end (`L is None`): after building the fail-closed entry
  `rv`, if the entry depth `d` OR the landing depth at the ramp top
  `live.disk_depth(rv[0])` exceeds ZB_FLOOR_BALL, SKIP: drop the pass
  (`ordered[k] = None`), record its vertices with live depths in
  `fe5_skip_pts`. Shallower unresolved entries keep today's fail-closed
  entry (never relaxes FE5e; a legally enterable - ramped or shallow -
  entry is never skipped).
- engine/finish.py:2401 - skipped passes are dropped before the link stage,
  so links join retained passes only; no plunge is ever emitted for them.
- Same code path covers the T33 rest pass (rest_from -> link_stock feeds the
  identical loop); engine/finish.py:2479-2481 emit `fe5_skipped_n` +
  `fe5_skipped_clusters` into the stats of whichever pass ran there.
- connector/runner.py:1046-1055 - check.json gains
  `"left_for_hole_op_or_another_setup": {"finish": [...], "rest": [...]}`,
  read from each program's stats json (`fe5_skipped_clusters`; [] if absent,
  rest only when a rest pass ran), so James sees the skipped areas in the
  summary. Summary-only edit; no engine behaviour touched.

## 3. Tests (all via slot_m4.sh small-test lane, ENGINE_WORKERS=4; no Core
Front / interim-model engine or zmap job; no G-code printed)

| run | result | exit |
|---|---|---|
| engine/test_finish.py::test_fe5f_skip_bore_entries (twice, pre/post comment trims) | PASS - "skipped 17 passes in 1 cluster(s) at [0.0, -0.466] (max live depth 5.90 mm)" | 0 |
| FE5/FE5e/FE5e-t/FL1b set: test_ramp_vertices_never_below_verified_path, test_fe5e_ramp_top_clear_of_ridge, test_fe5t_public_ramp_top_clear_of_ridge, test_floor_dip_split_finish_and_rest, test_floor_pad_rows_inside_stock_box (+ fe5f) | ALL-6-PASS | 0 |
| regression sweep: test_stock_from_ridge_rapids, test_link_plan_stock_ridge, test_gap_split_and_verified_link, test_flat_plate_length_and_links, test_two_boss_rapid_over_boss, test_stock_out_roundtrip | PASS | 0 |
| py_compile finish.py / runner.py / test_finish.py | OK | 0 |

## 4. Fail-on-e773afa proof (by assertion, git archive - never checkout)

`git archive e773afa | tar -x -C <tmp>` + copy of the NEW engine/test_finish.py
(ZB_FLOOR_BALL read via `getattr(..., 0.5)` so e773afa fails by ASSERTION,
not ImportError):

    AssertionError: FE5f: 4 bore entries plunged > 0.5 mm into live stock
    (max 2.899): [(-0.44, -1.96, 13.101, 2.899), (-0.49, -1.56, 12.803,
    1.028), (-0.41, -1.26, 12.502, 0.983), (-0.11, -1.06, 12.433, 0.982)]
    exit code 1

On FE5f the same test passes: zero vertical entry plunges land deeper than
the 0.5 mm ball floor, and the skip report lists a cluster centred at
(0.00, -0.47) - within 1 mm of the bore axis (17 passes skipped).

Test scenario per brief: bored cylinder boss (r 8, through bore r 4.8 =
9.6 mm for the 9.525 ball, ~0.038 mm radial room/side), bore FULL of stock
(top 16 > boss top 14 > stock allowance 14.3), floor_z 6, ramp 2 deg. The
replay mirrors test_fe5t: LiveStock over the EMITTED moves in order; every
ENTRY (bottom of a vertical G1 descent) must land at live depth <= 0.5 mm.

## 5. Not done / notes

- Mid-pass CL descents that cross the bore along the verified path (sloped
  18-35 deg, and the traversal of the standing bore column by rows whose
  entry is legal) are NOT skipped: FE5f's scope per brief is pass ENTRIES
  ("never skip a pass entry that can be entered legally"); the bore itself
  is left for James's drill/bore op as chosen. The cluster report lists the
  bore area; on this synthetic part wall passes buried by the stock block
  also appear in the report (correct: they are skipped, not plunged).
- The previous session's test replay rule (any G1 descent steeper than
  15 deg) was replaced with test_fe5t's entry rule (vertical plunge
  landings), because mid-pass CL traversal is FE5e behaviour outside this
  brief's scope; the entry rule still fails hard on e773afa (4 plunges up
  to 2.9 mm) and is the ZB-visible violation FE5f removes.
- No locks created/removed/edited; no git stash/reset/clean/checkout/
  rebase; verify/ and opencode.json untouched; nothing committed.
- Elapsed: ~1 h 40 m of the fresh 2 h cap.
