# ZG2 results (branch zg2, base 98a5706 + brief d575734)

Started: Sun Oct 25 11:57 MST 2026 (`date`), HARD CAP 2 h (~13:57).

## CAUSE (written before any code)

`verify/zmap.py:_ae2_windows` (:977) groups consecutive linked horizontal feed
moves into MINIMAL windows of >= AE2_WINDOW_MM (1.0 mm) travel. Its `close()`
(:993) keeps a run only when `length_mm >= AE2_WINDOW_MM`; any trailing run
below 1 mm (the last run of a chain, produced when the chain's total travel is
not a multiple of 1 mm) is silently DROPPED as "grid noise". The material those
sub-1 mm moves remove is therefore never attributed to any window: the dropped
run's `area_mm2` disappears from the engagement statistics, so a window that is
benign on its own kept travel can be materially overloaded once its tail's area
is charged to it. Supervisor measurements (brief facts table): on 0.1 mm grids
this drops 461 (L) / 336 (TB) / 940 (CF) runs and lets windows read e.g.
0.865 mm pre-merge vs 2.350 mm with the tail merged (L line 12979).

Fix per coordinator spec: merge every dropped tail into the preceding kept
window of its chain; a chain with no kept window merges into its path neighbour
(previous kept window, else next), exactly as `scratch/tailmerge_ref.py
merged()` does. Key structural fact used for a minimal implementation: within
one chain, runs are [kept, kept, ..., kept?, tail?] - a sub-1 mm run can only
be the LAST run of its chain (a run ends sub-1 mm only when the chain breaks).
Therefore "preceding kept window of the chain" == "last kept window closed
before the tail closed" whenever the chain had one, and the reference's
fallback ladder (same-chain prev kept -> any prev kept -> next kept) collapses
to: target = windows[n-1] where n = number of kept windows closed when the tail
closed; if n == 0 the target is windows[0] (the first kept window after it,
which is the next kept in path order); if no kept window exists at all the cut
is truly isolated -> reported, never gated (item 2).

## PLAN
1. Judge script scratch/zg2_judge.py (copies tailmerge_ref runs()/merged()
   verbatim; additionally counts per-limit over-limit windows over zmap's OWN
   returned windows, and lists pushed-over / fell-below windows with pre/post
   ae_eff for the item 5 window-by-window explanation).
2. BEFORE runs (current 98a5706 zmap): L, TB, CF via lane.
3. Edit verify/zmap.py (budget <= 25 changed non-test lines, stop ~35):
   tails collected in close(); merge pass after the loop; isolated tails
   exposed as `.iso` on the returned list subclass; new sub-key
   `ae2_isolated_sub1mm` in _ae2_engagement_keys ONLY when iso is non-empty
   (the b1688b8 byte-identity test freezes the whole engagement subtree for a
   program with no tails; its extra-key rule {below_stock_bottom, part_mask}
   must stay green).
4. NEW tests in verify/test_zmap.py: (a) merge pushes window over 2.25,
   (b) merge under the limit changes nothing (before == after),
   (c) isolated sub-1 mm cut reported + not gated.
5. Run verify/test_zmap.py file-wide (one call) + test_ze2b_flat_and_bull_-
   json_byte_identical by name; collect item-3 pin changes (do NOT edit pins).
6. Mutation: scratch copy with tails dropped again -> test (a) must fail by
   measured ae_eff; revert (delete copy).
7. AFTER runs (my zmap): L, TB, CF; AFTER must equal reference totals
   L 17/18/29, TB 10/10/2130, CF 515/550/35582; AFTER-BEFORE explained
   window by window via pushed-over/fell-below lists.
8. Finish this file (exit codes, numstat, tables). Do not commit.

## Log
### BEFORE (98a5706 zmap) judge runs — scratch/zg2_judge.py via lane

TB (scratch/tb.ngc on scratch/tb_hf01.npy), EXIT=0:
- cutting feed 3429.0; zmap kept windows 7622 = regrouped kept 7622; dropped runs 336; merged windows 7622; iso 0
- zmap-own windows over 2.44 / 2.25 / 1.85 (of 7440 cutting-feed): **11 / 11 / 2130**
- reference merged totals: 10 / 10 / 2130 (= brief's TB AFTER target 10/10/2130 ✓)
- window-by-window TB: FELL BELOW 2.44+2.25 line 36684 (pre 2.673 -> 2.075);
  PUSHED OVER 1.85 line 22635 (pre 1.773 -> 1.892, brief's worst ✓);
  FELL BELOW 1.85 line 36641 (pre 2.194 -> 1.322).
  Check: 11-1=10, 11-1=10, 2130+1-1=2130 ✓
CF (bs1a3_main_cf.ngc on cf_hf01_z5b.npy), EXIT=0:
- cutting feed 3429.0; zmap kept 73192 = regrouped kept 73192; dropped runs 940; merged 73192; iso 0
- zmap-own windows over 2.44 / 2.25 / 1.85 (of 70130 cutting-feed): **517 / 551 / 35584**
- reference merged totals: 515 / 550 / 35582 (= brief's CF AFTER target ✓); pushed-over 1/1/1 all at line 224286 (pre 1.389 -> 2.978, brief's worst ✓)
- window-by-window CF: 2.44: FELL 96720 (2.803->1.766), 124290 (2.532->1.772), 124331 (2.872->2.395); PUSHED 224286 => 517-3+1=515 ✓
  2.25: FELL 96720, 124290; PUSHED 224286 => 551-2+1=550 ✓
  1.85: FELL 96684 (2.096->1.285), 96720, 124290; PUSHED 224286 => 35584-3+1=35582 ✓

## Code change (verify/zmap.py only; test file additions separate)

- _ae2_windows docstring :987-989 rewritten (ZG2 merge rule).
- :991 `windows, tails, iso = [], [], []`
- :994-999 close(): sub-1 mm runs are collected as `tails.append((w, len(windows)))`
  instead of vanishing (n = kept windows closed so far).
- :1036-1048 merge pass: `tgt = windows[n - 1] if n else (windows[0] if windows
  else None)` == the reference ladder same-chain-prev -> any-prev -> next
  (a sub-1 mm run is always its chain's LAST run, so windows[n-1] IS the
  chain's last kept window when the chain has one); iso when no kept window
  exists at all; merged window gets area/length/a/hist summed and
  `ae_eff = round(area/length, 4)`.
- :1052 `class _Wins(list)` carries `.iso` out of _ae2_windows (no call-site
  churn; plain-list consumers unaffected).
- _ae2_engagement_keys :1088 `iso = getattr(win_recs, "iso", ())`; :1160-1163
  new sub-key `ae2_isolated_sub1mm` {count, worst_ae_eff_mm capped at D},
  present ONLY when iso is non-empty (the b1688b8 byte-identity test freezes
  the whole engagement subtree for a program without tails; its extra-key
  rule {below_stock_bottom, part_mask} stays green).
- git diff --numstat 98a5706 -- verify/zmap.py: **30 added, 5 deleted = 35
  changed non-test lines** (budget <= 25 target, stop ~35: over target,
  AT the stop line; drivers: docstring 3/3, merge pass 13, _Wins 4, sub-key
  4, close/header/return plumbing).

## NEW tests (verify/test_zmap.py, +88 lines, nothing existing edited)

- test_zg2_merged_tail_pushes_window_over_spike: 1.2 mm window at ~0.865 wall
  + neighbour-free-chain 0.9 mm tail into fresh solid -> ONE window,
  measured merged ae_eff **5.857 mm** (12.300/2.100) > 2.25, overload_feeds_ae2
  count 1. PASS.
- test_zg2_merged_tail_under_limit_changes_nothing: uniform 0.865 wall,
  ae_eff before 0.800 == after 0.800 mm (len 1.2 -> 1.8), count 1 == 1,
  nothing flagged. PASS.
- test_zg2_isolated_sub1mm_cut_reported_not_gated: lone 0.6 mm cut -> no
  window, no gating, ae2_isolated_sub1mm {'count': 1, 'worst_ae_eff_mm': 12.6}
  (<= D 12.686). PASS.

## Mutation (item 4): scratch/mut copy, merge pass reverted to `return windows`
(tails dropped again), scratch/mut deleted afterwards (REVERTED):

    $ pytest scratch/mut/test_zmap.py::test_zg2_merged_tail_pushes_window_over_spike
    AssertionError: merged ae_eff 0.800 mm not judged over 2.25
    ZG2(a) measured merged ae_eff 0.800 mm (area 0.960 / length 1.200, line 4)
    1 failed in 0.32s   PYTEST_EXIT=1

=> test (a) fails by the measured ae_eff: 0.800 mm (dropped tail) vs 5.857 mm (merged).

## verify/test_zmap.py file-wide (one call, final code): 1 failed, 128 passed,
in 167.53s  PYTEST_EXIT=1

### Item 3 list - failing pinned values (NOT edited, left red):

1. test_ze2_full_slot_short_segments_ae_eff_is_dia (verify/test_zmap.py:1353)
   - pinned: `1.0 <= w["length_mm"] <= 1.15` for every window.
   - old value: last window length_mm 1.0 (n_moves 10, ae_eff 12.6, 39 windows)
   - new value: last window length_mm 1.6999999999999993 (ae_eff 12.6)
   - cause: the trailing 7 x 0.1 mm = 0.7 mm run (gcode moves after the one
     ending at the window starting line 387, i.e. the program's last 0.7 mm of
     the 40 mm slot) is now MERGED INTO the last kept window (starts line 387,
     x=-16.100 y=0) instead of dropped: 1.0 + 0.7 = 1.7 mm. Every other
     assertion of the test (ae_eff = D, n_moves, p50, slot/overload counts)
     still passes. Verified old values against a scratch copy of 98a5706's
     zmap (scratch/pre_zmap.py).

(Everything else green: 128 passed incl. all ze2b byte-identity, parallel
merge, ze2d full_width_depth (fixed by merging hist into the kept window),
ze2f/ze2f2 pitch tests.)

## Item 5 - re-judged L / TB / CF, windows over 2.44 / 2.25 / 1.85 at cutting
feed (>= 0.9 x 3429), BEFORE = 98a5706 zmap, AFTER = ZG2 zmap (zg2_judge.py,
one lane call per program and state, all EXIT=0; zmap-own counts):

| program | BEFORE (mine) | AFTER (mine) | reference merged AFTER | brief's AFTER target |
|---------|---------------|--------------|------------------------|----------------------|
| TB      | 11 / 11 / 2130 | 10 / 10 / 2130 | 10 / 10 / 2130 ✓ | 10 / 10 / 2130 ✓ MATCH |
| CF      | 517 / 551 / 35584 | 515 / 550 / 35582 | 515 / 550 / 35582 ✓ | 515 / 550 / 35582 ✓ MATCH |
| L       | 62 / 69 / 81 | 62 / 69 / 81 | 62 / 69 / 81 ✓ (self-consistent) | 17 / 18 / 29 ✗ see note |

Window-by-window AFTER - BEFORE (from the reference merged set; identical in
both judge runs):
- TB: -1 at 2.44 and 2.25 (line 36684 fell 2.673 -> 2.075); 1.85: +1 line
  22635 (1.773 -> 1.892, brief's worst ✓) -1 line 36641 (2.194 -> 1.322).
  11-1=10, 11-1=10, 2130+1-1=2130 ✓
- CF: 2.44 -3 (96720, 124290, 124331) +1 (224286, 1.389 -> 2.978, brief's
  worst ✓) = 515; 2.25 -2 (96720, 124290) +1 (224286) = 550; 1.85 -3 (96684,
  96720, 124290) +1 (224286) = 35582 ✓ (pushed-over 1/1/1 = brief ✓)
- L (my scene): no window crossed any limit either way (0/0/0 pushed, my
  scene's tails all merge without flipping a verdict).

### L scene DISCREPANCY (flagged for supervisor, not fixable from here)
Running the brief's reference mode L (tailmerge_ref.py L branch, copied
verbatim into zg2_judge.py) on this worktree with
/Applications/VibeCAD.app/Contents/Resources/bin/python gives, DETERMINISTIC
across two runs, BEFORE == reference: kept 3188 (brief: 6828), dropped 256
(brief: 461), merged totals 62/69/81 (brief: 17/18/29), pushed-over 0/0/0
(brief: 0/1/5); roughing logged "Start point not found!" and repeated
"Unable to resolve tool down linking path (limit reached)". My AFTER equals
MY reference merged totals exactly (the invariant the change must satisfy),
but this environment's in-process L scene does not reproduce the supervisor's
L numbers; TB and CF reproduce every supervisor figure exactly (7622/336,
73192/940, pushed-over 0/0/1 and 1/1/1, worst lines/values). No lock was
touched; scratchpad was not browsed.

## FINAL RECORD

- Final full run verify/test_zmap.py (one call): 1 failed, 128 passed, 178.14s
  PYTEST_EXIT=1 (the 1 failure = item 3 pinned value, deliberately left red)
- test_ze2b_flat_and_bull_json_byte_identical by name: 1 passed, 0.57s
  PYTEST_EXIT=0 (extra-key rule {below_stock_bottom, part_mask} intact)
- new tests (3): 3 passed PYTEST_EXIT=0; mutation run PYTEST_EXIT=1 (intended)
- BEFORE/AFTER judge runs (6 lane calls): all EXIT=0
- git diff --numstat 98a5706 (this session's files):
  verify/zmap.py 30/5 (= 35 changed non-test lines, <= ~35 stop, > 25 target),
  verify/test_zmap.py 88/0 (tests only), verify/ZG2_RESULTS.md untracked->new,
  scratch/ untracked (zg2_judge.py, pre_zmap.py, tb_check.json, tb_after.json,
  cf_check.json, cf_after.json, tb.ngc, tb_hf01.* - mutation copy deleted).
  (engine/TASK_ZG2.md 48/0 and opencode.json 23/2 in the numstat are the
  brief commit / pre-existing dirty file, NOT my edits.)
- Nothing committed. No existing test or assertion was edited. No engine/,
  connector/ or opencode.json edit. No lock touched. All commands foreground.

DONE.
