# Task HN (safety gate): engine holder net must be at least as conservative as zmap. engine/ only. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; never touch verify/ (zmap is the judge, never loosen it);
no bypass flags; never relax or delete tests.
Evidence: Core Front T31 6 mm ball finish (stick-out 18, holder BT30-ER20-60) after the S3b roughing: the engine's holder
net dropped 23,002 points, but verify/zmap.py --tool-number 31 still counts 79 HOLDER HITS (1.0 mm clearance). The T20
plan had 0. Read verify/zmap.py's holder check (resolve_holder, holder_on/envelope code) to see exactly what it tests:
the full frustum stack at tip + stick-out against max(live stock, part) within each segment's radius.
Fix engine/finish.py holder_net so it tests the holder against max(part, remaining stock) along the WHOLE outline, at
least as conservative as zmap: (a) use the stock you are given (--stock-from, the roughing's StockField heightfield) and
update it with the finishing cuts already emitted (or conservatively keep the roughing stock - never lower than zmap's
live stock); (b) each frustum segment checked with its true max radius + 1.0 mm over its full height band (no gaps between
segments, include the nose ring); (c) drop + split + verified relink as before, never lower points.
Tests: synthetic case where the holder clears the PART but not the remaining STOCK (a stock ridge left by roughing next
to a deep pocket) -> holder points dropped and zmap holder_hits 0 on the output (tests may run verify/zmap.py as the
judge); keep all engine/finish tests green. Do NOT run Core Front; the supervisor runs the T31 regression.
