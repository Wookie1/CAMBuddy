TASK SK1: thin side-skin entry from the air outside the stock (engine/rough.py, entries only).
Context: with a small stock margin roughed below a flange (James's Core Front setup: 1 mm stock all round, floor 0,
bull 12.7 r0.127), every level below the flange is ONE ring region of ~1.3 mm skin around the part. The ring is
entered once (plus re-entries) and then cut sideways. At the entry, feed_down (rough.py ~1755-1815) finds stock under
the flat bottom, no helix fits a 1.3 mm skin, and find_shift returns None, so the entry is counted as an axial plunge
('wide') and the run aborts (rough.py ~2951: 22 points, all at the ring entry, x ~133.12 vs stock+R 133.715).
Why find_shift fails (rough.py ~1660-1732):
 (i) candidate descent columns are restricted to the stock box shrunk by tool_r ("footprint must stay inside the
     stock box", ~1683). For a skin the only axially legal columns are OUTSIDE the stock (centre >= stock edge + R);
 (ii) with flank=True, SE2 requires the sideways feed-in to cross only material already cleared at this level
     (stock.link_clear(path, z + AXIAL_FLOOR), ~1705). A skin entry must cross the standing skin with the flank.
Fixtures (out of git, read only): ~/ai-sandbox/stevecam-ops/speed/hf1_james/fixture/ (input.step, tools_effective.json,
prepare.json) and the exact rough argv in ~/ai-sandbox/stevecam-ops/speed/hf1_james/run.sh. Never print G-code.
Do (rough.py only):
(1) In find_shift, add a candidate class "air column": a column whose ENTIRE tool footprint (centre +- (tool_r +
    rapid_margin)) lies outside the stock box in X or Y (sx >= stock_box[1] + tool_r + rapid_margin, or the mirror on
    any side) and inside the grid the engine models. Search those columns along the existing (dist, 16 directions)
    pattern, plus the direction straight out through the nearest stock face. Every check that applies to today's
    candidates still applies (judge-disk-clear descent, isl_ok3 segment legality of the whole feed path,
    hf_gouge_violation on the feed path, the rapid-clear G0 descent at the column, lnk_cut_ok on the feed-in).
(2) For an air-column candidate ONLY, replace SE2's link_clear(path, z + AXIAL_FLOOR) with a LOAD check equal to the
    bands' engagement simulation: simulate the whole feed-in (column -> entry, swept by tool_r) through the LIVE stock at
    this level with engine.band._simulate (the same call lnk_cut_ok uses, eps=0.0) and accept only if every 1 mm window
    has ae <= band.SPIKE_MM (2.44, the judge's overload bar) AND ZE2 load <= 1.2 (load = ae_eff * a * F /
    (2.032 * 19.05 * Fcut), load_limit's rule), with the axial depth a of the engaged skin <= the tool's flute length.
    Nothing under the flat bottom along the path may stand above z + AXIAL_FLOOR (flank engagement only, never the
    bottom). Record per feed-in the max ae, max load and max a in stats ("sk1_feedin": [...]) and report the maxima.
    Flute length: the rough has no --flute today; take it from the --tools-json/--tool-number entry ("flute_mm") the way
    finish does, and add an optional --flute override. With no flute known, the air-column class is OFF.
(3) WORKHOLDING (required, safety): an air-column descent goes down OUTSIDE the stock, exactly where vise jaws or
    clamps sit, and the engine has no fixture model. Add rough CLI inputs --side-entry-clear (comma list of open faces:
    xneg,xpos,yneg,ypos; default NONE, so the air-column class is OFF unless the job lists faces) and --side-entry-min-z
    (default none = down to the floor). Allow an air-column candidate only when its whole footprint is beyond a LISTED
    face, and never at a level Z below --side-entry-min-z. Thread both through rough() as keyword arguments (default
    off). Do NOT touch connector/runner.py: passing them from the panel is a connector-thread follow-up.
(4) Use it only where today's code would otherwise count an axial plunge: the side=True branch and the wide_fail
    branch of feed_down. Change nothing else: no other caller, no ring/region/path generation, no constant, no other
    entry type.
Tests (new file engine/test_sk1.py; never edit existing tests):
 - a synthetic block with a 1.3 mm stock skin around a part wall, roughed below the top so the skin is a ring region,
   WITH all four faces listed in --side-entry-clear: the run completes, n_axial_plunge == 0, n_side_entries > 0, every
   side-entry descent column lies beyond a listed face by >= tool_r, every feed-in has max ae <= 2.44, max load <= 1.2
   and max a <= flute; print those maxima.
 - the same synthetic block with NO faces listed: today's behaviour exactly (the axial-plunge failure, same count),
   and with only some faces listed: no descent column beyond an unlisted face; with --side-entry-min-z above a level:
   no air-column entry at that level.
 - unchanged elsewhere: with no --side-entry-clear the test block rough program is byte-identical to main.
 - mutation (scratch, then revert): disable the air-column class; the synthetic test must fail with
   n_axial_plunge > 0. Report the count.
Rules: FOREGROUND RULE. Targeted tests only: your new file plus engine/test_engine.py tests that cover find_shift /
feed_down / side entries (name them). The supervisor runs the full suites and ALL Core Front jobs (James's setup with
floor 0 must complete with axial plunges 0 and all zmap gates 0; CF catalog-default and TB must stay unchanged except
at entries). Running any Core Front job voids the round. Write engine/SK1_RESULTS.md early and append after every run
(exit codes + git diff --numstat).
Follow-up (not this round): connector/runner.py + panel must pass --side-entry-clear / --side-entry-min-z from a job
input (the connector thread owns that). Stage nothing, commit nothing. No destructive git. Do not edit any existing test; if
a requirement conflicts with one, stop and report. Continue from your plan; don't stop before the tests exist and have
run. Hard 2 h cap.
