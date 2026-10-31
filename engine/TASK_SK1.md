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
(2) For an air-column candidate ONLY, replace SE2's link_clear(path, z + AXIAL_FLOOR) with: the feed-in may cross
    standing stock at this level with the flank, provided lnk_cut_ok(stock, path, z, "fdin") passes (engagement
    simulated through the live stock and within limits) AND nothing under the flat bottom along the path stands above
    z + AXIAL_FLOOR except within the outer (tool_r - (tool_r - corner_r)) ring, i.e. flank only, never the bottom.
    State the exact predicate you used in the results.
(3) Use it only where today's code would otherwise count an axial plunge: the side=True branch and the wide_fail
    branch of feed_down. Change nothing else: no other caller, no ring/region/path generation, no constant, no other
    entry type.
Tests (new file engine/test_sk1.py; never edit existing tests):
 - a synthetic block with a 1.3 mm stock skin around a part wall, roughed below the top so the skin is a ring region:
   the run completes, n_axial_plunge == 0, n_side_entries > 0, every side-entry descent column lies outside the stock
   box by >= tool_r, and the feed-in engagement stays within the limit used by lnk_cut_ok.
 - unchanged elsewhere: the test block rough program is byte-identical to main (run it; it has no skin rings).
 - mutation (scratch, then revert): disable the air-column class; the synthetic test must fail with
   n_axial_plunge > 0. Report the count.
Rules: FOREGROUND RULE. Targeted tests only: your new file plus engine/test_engine.py tests that cover find_shift /
feed_down / side entries (name them). The supervisor runs the full suites and ALL Core Front jobs (James's setup with
floor 0 must complete with axial plunges 0 and all zmap gates 0; CF catalog-default and TB must stay unchanged except
at entries). Running any Core Front job voids the round. Write engine/SK1_RESULTS.md early and append after every run
(exit codes + git diff --numstat). Stage nothing, commit nothing. No destructive git. Do not edit any existing test; if
a requirement conflicts with one, stop and report. Continue from your plan; don't stop before the tests exist and have
run. Hard 2 h cap.
