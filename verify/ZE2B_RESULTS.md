# ZE2B results (report-only, ball-tool engagement in verify/zmap.py)

Branch `ze2b` on b1688b8 (+ brief 65c843c). Finished the WIP left by the cut-off session,
reviewed it against ZE2B_DESIGN.md, fixed one design deviation, ran everything in the
small-test lane via `slot_m4.sh`. Nothing committed. No Core Front / real-part zmap job run.

## 1. Line count (`git diff --numstat b1688b8`)

    150     0    verify/zmap.py        <- BUDGET <= 150: exactly at budget
    217     0    verify/test_zmap.py   (tests, not budgeted)
     27     0    verify/TASK_ZE2B.md   (the brief, committed in 65c843c)
      1     1    opencode.json         (NOT part of ZE2B: pre-existing infra edit,
                                         model-server baseURL LAN -> 127.0.0.1 from the outage;
                                         left untouched per HARD RULES)

## 2. What changed (verify/zmap.py) + review of the WIP

- `ZE2B_DESCENT_FRAC = 0.1` (zmap.py:82) — descent = horizontal travel < 10 % of 3D travel.
- `_ze2b_chord` (zmap.py:1157) — c(a) = 2*sqrt(a*(dia-a)).
- `_ze2b_windows` (zmap.py:1162) — ZE2 minimal-window merge over 3D travel (>= AE2_WINDOW_MM,
  consecutive idx = no rapid between, dir change <= AE2_DIR_MAX_DEG, ANY Z change; short tail
  dropped); ae_eq = vol/length_3d/a, w_plan = ext (descent: dext) clamped to dia,
  theta = acos(1 - a/R).
- `_ze2b_keys` (zmap.py:1204) — `engagement.ze2b`: n_windows, full_width / overload (count,
  length_mm, worst[10] with the dump fields), ae_eq / w_plan_over_chord / a stats, descent,
  ZE2F cutting/entry-feed split (AE2_ENTRY_FEED_FRAC). full_width = not descent AND a >= 0.05
  AND w_plan >= FULL_WIDTH_FRAC * c(a); overload = ae_eq > engage_max.
- `simulate`: `zb_on` ball-only gate (zmap.py:1363); per-move pre-stamp footprint snapshot +
  accumulators (zmap.py:1514-1523); per-sample sampling (zmap.py:1686-1701); per-move record
  (zmap.py:1851); window build + raw keys (zmap.py:1913, 1962); ball-only
  `engagement.semantics = "flat-only, see ze2b"` + `engagement.ze2b` (zmap.py:1978-1980).
- `simulate_parallel`: same ze2b merge/keys on the combined raw (zmap.py:2167-2174).
- CLI: `--ae2b-dump` (zmap.py:2377, 2535-2537) writes the windows (line, x, y, z, a, theta,
  w_plan, c_a, ae_eq, length_3d, feed, descent).

**WIP review finding (fixed):** the design says engagement cells are kept where
`r = stock_top - z_b > 0.01` against "the stock as it stands BEFORE the move is stamped".
The WIP applied the gate to per-sample cuts on the live stock, which at cell/4 sampling only
ever sees slivers — it collapsed the design's own analytic values (ae_eq 0.356 vs 1.905,
w_plan 6.35 vs 7.76). Fixed: vol keeps the live-stock telescoping sum (counts each cell's
removal once, reproduces segment-area/a exactly), while a/ext/dext are now read against a
per-move pre-stamp snapshot of the swept footprint bbox (`.copy()`, zmap.py:1523) with
`r > 0.01` (zmap.py:1694). First bbox attempt used ±R and clipped the footprint window
(padded by k cells) — fixed to the same floor/index ± k arithmetic (zmap.py:1517-1520).
Trimmed comments/docstrings to land the implementation back at exactly 150 lines.

## 3. Tests (all via slot_m4.sh, /opt/homebrew/bin/python3 -m pytest)

ZE2B suite `verify/test_zmap.py -k ze2b`: **7 passed, exit 0** (12.7 s):

| test | design case | result |
|---|---|---|
| test_ze2b_side_pass_ae_eq_is_stepover | 1 (ae_eq ~1.905 +-5 %, w_plan/c(a) ~0.62, not full width) | PASS |
| test_ze2b_full_slot_flagged_chord_and_ae_eq | 2 (w_plan ~7.76 flagged, ae_eq ~5.44) | PASS |
| test_ze2b_slope_skim_not_flagged | 3 (0.2 mm skim on 45 deg, no flags) | PASS |
| test_ze2b_helix_finite_and_descent_tagged | 4 (2 deg helix finite, entry tagged descent) | PASS |
| test_ze2b_flat_and_bull_json_byte_identical | 5 (runs b1688b8 + new zmap, byte cmp) | PASS |
| test_ze2b_cli_ball_block_and_dump | ze2b block + --ae2b-dump fields, rc 0 (report-only) | PASS |
| test_ze2b_mutation_broken_chord_breaks_assertions | 6 (monkeypatch c(a)->D, fail by assertion) | PASS |

Measured clean values (demo run): full slot w_plan 7.650 vs c(a) 7.759, ae_eq 5.438 (design
~5.44), a 2.000, theta 54.5 deg.

Full suite `verify connector engine/test_post.py -q`: **225 passed, 5 failed, exit 1** (931 s).
All 5 failures are missing gitignored `out/` Core Front fixtures, NOT ZE2B regressions:
- engine/test_post.py: test_tool_table_lookup, test_tool_number_override (FileNotFoundError
  out/core_front_roughG.ngc), test_posted_x7_file_reads_T3, test_zmap_matches_neutral
  (missing out/core_front_rough_X7.nc / out/core_front_setup_hf.npy) — exit 1, rest pass.
- verify/test_zmap.py: test_axial_real_core_front_rough_fails (FileNotFoundError) — exit 1.
Proof pre-existing: `git ls-files out/` = 0 files (fixtures never committed); ran all five in
a pristine `git worktree` at b1688b8 — identical failures in 0.07-0.2 s (fixture checks fire
before any zmap code). Regenerating them needs Core Front / freecad jobs, forbidden by the
brief; the supervisor runs ZE2B on the chain programs afterwards. `verify` + `connector`
otherwise: 210 passed, exit 1 only from the fixture test above.

## 4. Mutation proof (design case 6)

`test_ze2b_mutation_broken_chord_breaks_assertions` (monkeypatch wrapper, no edit): with
c(a) replaced by D, both checks FAIL BY ASSERTION (demo output: "slot pass not flagged full
width" — w_plan 7.65 < 0.9*D; side-pass check fails too). `git diff --numstat b1688b8`
unchanged at 150/0 after the mutation run — no file edits involved.

## 5. Flat byte-identity proof (design case 5)

Standalone run: `git show b1688b8:verify/zmap.py` vs working zmap.py on the same flat program
(+ bull variant), same args, `--out-json` compared with `cmp`:
flat: **identical, 8873 bytes**; bull: **identical, 11677 bytes** (exit 0). The in-suite test
repeats this per run. Ball-only: the ze2b block and semantics marker appear only for
`--tool ball` with engagement tracking on; ZE2 keys unchanged for every tool.

## 6. Not done / notes

- The full-suite "green" requirement cannot be met in this worktree: the 5 fixture-dependent
  tests need Core Front artifacts (gitignored, regeneration forbidden). Everything runnable in
  the small-test lane is green; failures proven identical at b1688b8.
- opencode.json's 1-line baseURL edit predates this session (outage workaround); left as-is.
- Report-only honored: ZE2B never changes an exit code (asserted in the CLI test, rc 0 with
  full_width + overload flags raised). No engine/ imports in verify/ (zmap.py imports
  unchanged; only stdlib/numpy). Nothing committed.
