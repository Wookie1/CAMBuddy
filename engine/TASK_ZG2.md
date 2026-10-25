# Task ZG2: zmap ZE2 windowing MERGES sub-1 mm tails instead of dropping them. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. A pinned value that changes
because a tail now merges is NOT edited by you: list it (item 3) and leave the test red. Add NEW tests.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate; do NOT
edit engine/ or connector/ or opencode.json; verify/ never imports engine (its tests may build inputs with it).
SCRATCH: scratch files and mutation copies go ONLY in /Users/James/ai-sandbox/stevecam-zg2/scratch/ - never /tmp.
RESULTS: create verify/ZG2_RESULTS.md and only ever APPEND to it. CAUSE FIRST: write the cause there before any code.
CONTINUE: continue from your plan; don't stop before every test has run.
Edit verify/zmap.py and verify/test_zmap.py only. BUDGET: <= 25 changed non-test lines in verify/zmap.py vs 98a5706;
STOP and report at ~35. FRESH session, HARD CAP 2 h (run `date` at start). Worktree
/Users/James/ai-sandbox/stevecam-zg2, branch zg2 at the commit carrying this brief (= main 98a5706 + brief).
Small tests ONLY through /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh <command>.
AT-RISK: every test in verify/test_zmap.py (run it file-wide, one call), plus test_ze2b_flat_and_bull_json_byte_identical
by name; engine/test_engine.py tests that read zmap ZE2 windows are judged by the supervisor gate, not by you.

## Facts (supervisor data, read-only regrouping of zmap's own _ae2_windows input; reference script
## scratch/tailmerge_ref.py - its runs()/merged() logic is THE reference for item 1)
- verify/zmap.py _ae2_windows (:977) keeps only runs >= AE2_WINDOW_MM (1.0) and DROPS a trailing run < 1 mm ("grid
  noise"), so those cuts are never judged. Measured on 0.1 mm grids, cutting feed >= 0.9 x 3429:
| program | kept windows (zmap = regroup) | dropped runs | pushed over by a merged tail 2.44 / 2.25 / 1.85 | worst |
| L scene (lshaped, in-process) | 6828 | 461 | 0 / 1 / 5 | 2.350 mm (pre 0.865; 4.06 mm2 / 1.727 mm) line 12979 |
| TB scratch/tb.ngc on scratch/tb_hf01.npy | 7622 | 336 | 0 / 0 / 1 | 1.892 mm (pre 1.773) line 22635 |
| CF archive bs1a3_main_cf.ngc | 73192 | 940 | 1 / 1 / 1 | 2.978 mm (pre 1.389; 5.63 / 1.890) line 224286 |
- Reference commands (each one lane call): python scratch/tailmerge_ref.py <worktree> TB cli scratch/tb.ngc --part
  scratch/tb_hf01.npy --tool flat --dia 12.686 --engage-max 2.438 --stock -50 50 -40 40 0 38 --jobs 4 --out-json
  scratch/tb_check.json ; CF: same with /Users/James/ai-sandbox/stevecam-bs1a/out/bs1a3_main_cf.ngc --part
  /Users/James/ai-sandbox/stevecam-rr1b/out/cf_hf01_z5b.npy --stock -128.651 128.651 -82.55 82.55 0 60.96 ; L: mode L
  (needs /Applications/VibeCAD.app/Contents/Resources/bin/python for opencamlib). TB/CF use /opt/homebrew/bin/python3.
## Change (coordinator spec)
1. ZE2 windowing: a trailing run under 1 mm is MERGED into the preceding kept window of its chain (same link rule as
   today), never dropped. If a chain has only sub-1 mm runs, merge it into its path neighbour (previous kept window,
   else next) exactly as scratch/tailmerge_ref.py merged(). ae_eff of a merged window = merged area / merged length.
2. A truly isolated sub-1 mm cut (no neighbour window at all) is NOT gated: report it in a NEW sub-key of the existing
   ZE2 report (count, worst area/length capped at the tool diameter D). NO new top-level keys:
   test_ze2b_flat_and_bull_json_byte_identical's extra-key rule stays {below_stock_bottom, part_mask}.
3. Expected pin changes ONLY where a tail merged. Run verify/test_zmap.py; for EVERY failing pinned value list: test,
   old value, new value, and the cause line (which tail merged into which window). Do NOT edit any of them.
4. NEW tests: (a) synthetic - a ~0.865 mm-wide 1.0-1.7 mm window plus a sub-1 mm tail that pushes it over 2.25 is
   judged over (measured ae_eff printed); (b) one per side: a window + tail that stays under the limit is unchanged
   (ae_eff and count before == after). Mutation (scratch copy, revert): drop tails again; test (a) must fail by the
   measured ae_eff (mm). Record it.
5. Re-judge L, TB and CF with the changed zmap: windows over each limit (2.44 / 2.25 / 1.85) at cutting feed, BEFORE
   (98a5706 zmap) and AFTER (yours). The reference script's post-merge totals are L 17/18/29, TB 10/10/2130,
   CF 515/550/35582 and its pushed-over counts CF 1/1/1, L 0/1/5, TB 0/0/1: your AFTER must equal those totals, and
   AFTER - BEFORE must be explained window by window (a merge can also lower a window's ae_eff).
## verify/ZG2_RESULTS.md: cause, change with file:line, line count, the item 3 list, PASTED test exit codes, the
mutation output, the item 5 table, git diff --numstat. Then stop.
