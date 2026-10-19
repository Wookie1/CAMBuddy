# Task Z5: zmap must never silently judge less than the whole stock / toolpath. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests;
verify/ must NOT import engine/.
Found by the supervisor: with a part heightfield whose grid ended 1.7 mm inside the stock box in Y, zmap ran, printed no
warning, and judged ~1,800 fewer cutting moves. A judge must fail loudly instead.
1. If the stock box (--stock, or the --stock-in grid) extends beyond the part grid by more than half a cell on any side,
   exit non-zero with a clear error (state the part grid bounds and the stock box). No option to skip it.
2. If any move's tool footprint (XY +- tool radius) leaves the part grid, count it: report "outside_grid":
   {count, first_line}; and make it a failure the same way (non-zero exit), since cells outside the grid are unjudged.
   Moves entirely outside the STOCK box in air (e.g. approach rapids) are fine only if they are also inside the part
   grid; otherwise they count.
3. Also fail (non-zero) if the part sidecar's tess_tol is missing or > 0.02 (today only a warning).
4. connector/runner.py: make sure its zmap calls still pass (its heightfields are built for the stock; adjust only the
   PAD it passes to verify/heightfield.py if needed so its grid covers stock + tool radius). Tests for 1-3 in
   verify/test_zmap.py. Run /opt/homebrew/bin/python3 -m pytest verify connector -q. Short outputs.
