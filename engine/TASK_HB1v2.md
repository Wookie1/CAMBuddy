# Task HB1 v2: one flat circle at each helix bottom, at helix feed. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ (read and run it only). Edit engine/rough.py and engine/test_engine.py (add tests) only. Do NOT touch
opencode.json. Budget: about 60 changed lines NOT counting re-indent; if it overruns ~80, STOP and report why.
Report ONLY numbers you produced this session from files under /Users/James (this worktree:
/Users/James/ai-sandbox/stevecam-hb1v2, branch hb1v2 = main 843337a, i.e. with HR1). Long runs: nohup + short polling;
never end your turn while one runs. ONE-JOB SLOT - EVERY heavy run (engine, zmap, pytest, test_engine, test_finish)
goes through
  nohup /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot.sh <command> > out/<log> 2>&1 &
then poll the log. Never run two at once, never one outside the slot. If blocked, write the question into
engine/HB1v2_RESULTS.md and stop - do not wait for an answer.

## Background
v1 (branch hb1, commit 4e39238: read with `git show hb1:engine/rough.py`, `git show hb1:engine/HB1_RESULTS.md`; do NOT
merge it) found the real mechanism: our helix IS centred on Adaptive2d's HelixCenterPoint with r = r_a2d, but the
helix floor is a spiral - up to one pitch (~1.1 mm at 2 deg, r 5.074) stands as a ridge inside the bore, and a2d's first
loop shears it across the full disk at the CUTTING feed (F3429) instead of the helix feed (F1270). v1 fixed it with a
floor circle but ALSO capped the pitch at 0.45 mm (REFUSED: it quietly lowers RT2's ramp angle, +20 min).

## Change
1. After each helix entry, emit ONE full flat circle at the helix bottom Z on the helix path (same centre and radius as
   the helix), at the helix (ramp) feed, milled honestly into the live stock model. It is part of the entry.
2. Keep the pitch EXACTLY as RT2 has it (ramp_angle_deg, turns rounded up). No pitch cap.
3. Containment fallback (v1's tiers) ONLY if an ablation (with vs without it, everything else equal) shows it removes
   real full-width windows at the cutting feed; report the ablation either way.

## Test (engine/test_engine.py)
After a helix entry, the next emitted moves are one full circle at the helix bottom Z, same centre/radius, at the ramp
feed, before any cutting-feed move. Must fail on main's code.

## Judge (main's verify/zmap.py = ZE2 + ZE2F feed tags; same commands as engine/TASK_HR1.md on branch hr1)
Core Front T13 and the test block, BEFORE = main (out/hr1_cf_ae2.json, out/hr1_tb_ae2.json are main's program; owners
for main from out/hr1l_labels.json, the byte-identical labelled run - tags a2d_first / a2d_mid / helix_bottom /
hug_boundary). Run zmap with --ae2-dump and --out-json. Classify each a2d_first full-width window
(ae_eff >= 0.9*12.686, a > 0.5) as RIDGE type (its Z is a helix bottom and a <= that helix's pitch + 0.05, within the
helix bore) or BAND type (everything else) - write your own script under out/.
PASS:
- ridge-type a2d_first full-width = 0 (band-type: report count/length, out of scope)
- helix-bottom full-width at CUTTING feed = 0: engagement.full_width_slots_ae2_cutting_feed restricted to helix-bottom
  windows; report engagement.roughing_target_ae2 too
- no other owner's full-width or overload length worse than main
- zmap gouges / rapid collisions / axial plunges / outside_grid = 0
- Core Front cycle (zmap cycle_time_s) at most main + 240 s; report helix minutes before/after
- scripts/check_fixtures.py ok; engine/test_engine.py, engine/test_finish.py (VibeCAD python
  /Applications/VibeCAD.app/Contents/Resources/bin/python, as scripts) and
  `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green, real exit codes, all via the slot.
Write engine/HB1v2_RESULTS.md with every number and the exact commands. Then stop.

## RESUME (supervisor, after the M5 oMLX outage killed your session)
Your change is committed on hb1v2 (circle at the helix bottom; CF all-owner FW 330.2 -> 285.5 mm, cycle 4851.6 -> 4980.1 s,
gates 0, pytest 218 green - all in out/). Do NOT redo those runs. Finish: (1) the ablation result for the containment
fallback (out/hb1v2_containment.patch / hb1v2_cfa_*: you already ran it - report with vs without); (2) your ridge vs band
classification of a2d_first FW (out/hb1v2_classify.py, out/hb1v2_*_classify.json) and helix-bottom FW at CUTTING feed,
before (out/hb1v2_cfmain_*) vs after, Core Front and test block; (3) note: ZE2F currently gives the helix pitch only to the
FIRST window after a helix, so your circle's later windows show as "fw_entry_not_allowed" - the supervisor is fixing that in
verify/ (propagate the pitch along the contiguous entry-feed run at the helix bottom Z); report those windows separately as
"circle windows (entry feed, a <= pitch + 0.05?)" with their a vs the helix pitch, from your own script. Then write
engine/HB1v2_RESULTS.md with every number and the exact commands, and stop.
