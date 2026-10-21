# Task ZE: engagement report gives axial depth per wide move (report-only). Do not commit. verify/ only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; NO gate or
threshold change; the existing engagement numbers (threshold_mm, count, horizontal/entry p50/p95/p99/max, spikes) stay
byte-identical; verify/ must NOT import engine/.
1. For every engaging cutting move, also record its AXIAL depth: the deepest stock removed above the tool tip under the
   footprint during that move (max over the removed cells of stock_before - cut surface).
2. Report (new keys only): "wide_moves": for horizontal moves over the engagement threshold, split into "slot" (axial
   depth > 0.5 mm) and "skim" (<= 0.5 mm): count, total length, total time at their feed, p50/p99 of radial width and of
   axial depth. "slot_horizontal": {n, p50, p95, p99, max} of radial width over horizontal moves whose axial depth > 0.5
   mm (the engagement statistic that matters for load). "skim_by_z": per Z level, the time spent skimming (axial depth
   <= 0.05 mm, i.e. floors already within a few hundredths).
2b. For EVERY horizontal feed move (not only wide ones) record radial width AND axial depth, and report
   "full_width_slots": moves with radial width >= 0.9 x tool diameter AND axial depth > 0.5 mm - count, total length,
   time, and the top 20 by depth (line, XY, width, depth). A full-width slot of the 12.686 flat must show as width ~12.7
   with depth > 0.5.
2c. "overload_feeds": horizontal feeds with radial width > 2.44 mm (1.2 x the 2.032 load) AND axial depth > 0.5 mm -
   count, total length, and the worst 20 (line, X, Y, Z, width, depth). This is the SE2 merge bar: SE2 must not increase
   the count or the total length vs main's helix-only rough on Core Front.
3. Tests: a full-width slot at 3 mm depth -> slot; a full-width pass over a floor 0.02 mm high -> skim (and counted in
   skim_by_z); existing engagement numbers unchanged on an existing test fixture (assert equality).
Run /opt/homebrew/bin/python3 -m pytest verify -q until green. Then run the report on BOTH
/Users/James/ai-sandbox/stevecam-rp/out/rp1a_cf.ngc or, if absent, /private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/rpm/cf.ngc (main, helix-only entries) AND
/Users/James/ai-sandbox/stevecam-se/out/rp2_1_new_cf.ngc (side entries, RP2 step 1), and the SE2 rough when it exists
(/Users/James/ai-sandbox/stevecam-se/out/se2_cf*.ngc): compare full_width_slots AND overload_feeds counts and total lengths. Also run it on
/Users/James/ai-sandbox/stevecam-rt2/out/rt2_after.ngc (part out/cf_hf01_z5b.npy, flat 12.686, stock -128.651 128.651
-82.55 82.55 0 60.96, --engage-max 2.438) and write the new numbers to verify/ZE_RESULTS.md. FOREGROUND. Short outputs.
