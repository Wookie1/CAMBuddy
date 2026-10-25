# POST_ARCS results (track 1, branch post_arcs, from main 681f551)

Scope: arc fitting as an opt-in LNC post option (`arcs=False` default), G2/G3 centre guard, spec facts for
G2/G3 and G40/G41/G42. Log appended as work proceeds.

## Log
- started 2026-10-24; RESULTS file created first.
- Spec: docs/lnc5800_post_spec.md gained "Arcs" A1-A8 and "Cutter radius compensation" C1-C6, page-cited to
  [LNC-PM] (PDF page numbers, printed page in brackets; same convention as the existing p.13 G04 cite). Manual
  read via a local PDFKit text extraction in the scratchpad (nothing from the PDFs in the repo). Manual is
  **silent** on: helical arcs, full circles, R sign for >180 deg, and the value of parameter 50048 (arc end-point
  alarm 510204) -> post uses 0.0005 mm, no helical, no R, sweeps <= 180 deg. Operation manual has nothing on arcs.
- Code: new engine/arcfit.py (pure geometry); engine/post_lnc.py: `arcs=False` on post() (post_text passes it
  through), arc emission + centre guard in post_moves (`_arc_centre`); engine/cli.py post subcommand `--arcs`
  (2 lines; cli.py is outside the listed file set but the task asks for the flag there).
- Design note: the fit is stricter than "every point within 0.002 mm": each original chord must also stay within
  0.002 mm of the arc (vertex residual + sagitta bound), so the arc never strays from the verified linear path
  between sparse points. After rounding, the post tries the 3x3 nearest-grid centres for |r_start-r_end| <=
  0.0005 mm and re-checks ARC_TOL with the posted centre; if none passes the arc is written as its original lines.
- Note: one early full `pytest engine/test_post.py` run (28 passed) ran outside slot_m4.sh (it includes the
  zmap equivalence test at its default 8 jobs) - a slip; all later engine/judge runs go through slot_m4.sh.

## Byte identity, arcs off
- test_post fixtures: new test `test_arcs_off_byte_identical_to_main` pins sha256 of main 681f551's post output on
  8 fixture posts (synthetic mm/inch/dwell-X/CRLF/slashstar, core_front_roughG inch + mm T5, ball header) and checks
  default and explicit arcs=False against them. Hashes computed by running main's post_lnc.py (git show) and this
  branch side by side: 8/8 IDENT.
- Real programs (scripted check, scratchpad/pa/repost_check.sh, outputs in scratchpad/pa/repost, not committed),
  exit 0:
  | program | arcs off vs original .nc | arcs on: bytes | lines | arc lines | max vertex dev |
  |---|---|---|---|---|---|
  | fin_after (T20, 1002) | BYTE-IDENTICAL (9,654,798 B) | 9,654,798 -> 8,002,469 (-17.1 %) | 532,193 -> 410,887 (-22.8 %) | 21,944 | 0.00199 mm |
  | fin_before (T20, 1002) | BYTE-IDENTICAL (9,656,834 B) | 9,656,834 -> 8,003,994 (-17.1 %) | 532,287 -> 410,943 (-22.8 %) | 21,952 | 0.00199 mm |
  | t33 (T33 ball, 1004) | BYTE-IDENTICAL (661,939 B) | 661,939 -> 519,849 (-21.5 %) | 47,691 -> 37,265 (-21.9 %) | 1,652 | 0.00198 mm |
  Deviation (scratchpad/pa/arcdev.py) is measured independently: parse both posted programs with verify/zmap,
  walk them 1:1 (every non-arc move and every arc end must equal the linear program's point exactly), distance of
  each replaced linear point to the posted arc (centre = start + I/J). Chord bound (vertex dev + sagitta) <= 0.00200.

## Test block: strict judge, arcs off vs on
Neutral programs generated here into out/ (untracked), via slot_m4.sh, ENGINE_WORKERS=4:
- rough: `engine.cli rough --step samples/test_block.step --stock -50 50 -40 40 0 38 --tool flat:12.686 --floor 20
  --leave 0.381 --final-zmin 20.381 --stepdown 19.05 --optimal-load-mm 2.032 --hf out/test_block_hf_0.5.npy
  --workers 4 --out out/pa_tb_rough.ngc` (exit 0, 3m16s)
- finish: `engine.cli finish --step samples/test_block.step --tool ball:5.958 --workers 4 --out out/pa_tb_finish.ngc`
  (exit 0, 1m46s)
- posted metric with `engine.cli post` (rough `--tool-number 13 --tool-kind flat --dia 12.686 --corner 0`;
  finish ball 5.958/2.979 -> T31 from the table), with and without `--arcs`.
- judge: `verify/zmap.py <nc> --part out/test_block_hf_0.1.npy --stock -50 50 -40 40 0 38 --strict --jobs 4`,
  tool flat 12.686 (rough) / ball 5.958 corner 2.979 (finish); all four runs exit 0 (one slot job, 35m46s wall
  incl. lock wait).

| program | strict unsupported | gouges | rapid collisions | plunge flags | axial plunges | leftover mean / p95 / max mm | cut length mm |
|---|---|---|---|---|---|---|---|
| TB rough, lines | [] | 0 | 0 | 0 | 0 | 0.6206 / 0.9143 / 15.381 | 15433.4 |
| TB rough, arcs | [] | 0 | 0 | 0 | 0 | 0.6206 / 0.9143 / 15.381 | 15433.5 |
| TB finish, lines | [] | 0 | 178 | 1139 | 168 | 0.0885 / 0.6403 / 12.0861 | 57185.0 |
| TB finish, arcs | [] | 0 | 178 | 1139 | 167 | 0.0886 / 0.6403 / 12.0976 | 57184.7 |

Same strict verdict and identical gouge / rapid-collision counts on both. Minor drift, finish only: axial
plunges 168 -> 167 and leftover max +0.0115 mm (one extreme cell; mean/p95 unchanged). The 178 finish rapid
collisions are there in both and come from the finish program itself (run without --stock-from, so its rapids are
not checked against roughing stock), not from the post.

Size and deviation (scratchpad/pa/arcdev.py, arcs vs the same post with arcs off):
| program | bytes | lines | arcs | max vertex dev | chord bound |
|---|---|---|---|---|---|
| TB rough | 681,842 -> 627,062 (-8.0 %) | 38,210 -> 33,441 (-12.5 %) | 1,298 | 0.00178 mm | 0.00259 mm |
| TB finish | 1,691,992 -> 1,340,057 (-20.8 %) | 124,622 -> 99,195 (-20.4 %) | 3,824 | 0.00199 mm | 0.00200 mm |
The chord bound (vertex residual + sagitta) is an upper bound measured against the *rounded* posted linear
points, so it carries their +/-0.0005 mm rounding; the post's own ARC_TOL check (on the unrounded neutral points
with the posted centre) passed for every arc written. The vertex-deviation requirement (<= 0.002 mm) holds everywhere.

## Final tests (through slot_m4.sh)
- `POST_ZMAP_JOBS=4 python3 -m pytest engine/test_post.py -q`: 28 passed (19 existing + 9 new), exit 0.
  New: test_arcfit_circle_one_arc_per_half, test_arcfit_noise_gives_lines, test_arcfit_s_curve_split,
  test_arcs_off_byte_identical_to_main, test_arcs_on_circle_posts_ij_arcs,
  test_arcs_on_keeps_non_planar_and_short_runs_as_lines, test_g2_g3_without_centre_refused,
  test_arc_rounding_failure_falls_back_to_lines, test_cli_post_arcs_flag. No existing test changed.
- `python3 -m pytest verify -q`: 115 passed, exit 0.

## Outside scope / open
- engine/cli.py touched (post subcommand `--arcs` + passing it through) - required by the task, outside the listed set.
  `rough --post lnc` has no `--arcs` (not asked).
- VERIFY on the X7: parameter 50048 value (A6). The 0.0005 mm limit is the post's own choice.
- The real chain4 programs were re-posted and measured for deviation only (no part judge on them).
- Finish TB program has 178 rapid collisions in both line and arc form (engine finish issue, not post).
