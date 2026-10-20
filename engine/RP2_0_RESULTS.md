# RP2 step 0 — OPEN vs CLOSED roughing regions (diagnosis only)

Method: `RT_RP2=1` env-gated instrumentation in `engine/rough.py` (no behavior
change when unset; no generator logic touched). Full Core Front T13 rough per the
task command; data in `out/rp2_0_cf.json`, log `out/rp2_0_cf.log`.
Criterion, live stock at each region start: OPEN iff a centre q exists with
max(top,part) <= Z+0.05 over disk(q, tool_r+0.5) (tool + 2x0.5 gap descends in
cleared stock/air, no axial removal), region's still-standing cut material
(within tool_r of its cutting paths, top > Z+0.05) within tool_r+2.0 of q
(short sideways feed, flank only), and q island-legal (0.03). Else CLOSED.

## Counts (21 executed levels, 213 regions — matches baseline)
| Z | open | closed | | Z | open | closed |
|---|---:|---:|---|---|---:|---:|
| 25.146 | 4 | 0 | | 39.605 | 19 | 0 |
| 27.051 | 7 | 0 | | 40.289 | 13 | 3 |
| 28.956 | 7 | 0 | | 40.386 | 13 | 0 |
| 30.861 | 7 | 0 | | 41.910 | 22 | 0 |
| 32.766 | 7 | 0 | | 42.354 | 7 | 3 |
| 34.671 | 7 | 0 | | 42.926 | 8 | 0 |
| 35.306 | 3 | 2 | | 43.815 | 11 | 0 |
| 36.449 | 16 | 0 | | 45.720 | 9 | 0 |
| 36.576 | 12 | 0 | | 47.224 | 5 | 0 |
| 37.082 | 13 | 0 | | 47.625 | 5 | 0 |
TOTAL: **open 205 / closed 8**. Closed = z42.354 r2,r5,r8 (cand 0: ring of stock
above Z+0.05); z40.289 r1,r9,r14 (cand 0); z35.306 r1 (cand 0), r2 (161 candi-
dates, all island-illegal). All are islands/boss-surrounded pockets, mostly the
first big levels; below 35.306 every region is open (same-level cleared ground).

## Entry feed if ONLY closed regions helix (measured G1 descent per region entry)
This run: all-region entry feed 53,525 mm = 42.1 min; total descending G1 in the
emitted NGC 83,614 mm = 65.8 min (≈ RP1's 83.4 m / 65.6 min baseline; the extra
~30 m is mid-region re-entries/lift descents, outside region entries).
Remaining (closed only): **2 deg: 2,905 mm = 2.3 min** (measured; conservative
full-helix model: 3,130 mm = 2.5 min) | 5 deg: 1,347 mm = 1.1 min |
10 deg: 745 mm = 0.6 min | 15 deg: 525 mm = 0.4 min.
i.e. ~94.6 % of entry feed (50,620 mm) is on regions that need no helix —
193 open regions still descend >50 mm today.

## Adaptive2d outside-entry
API offers opType {ClearingInside, ClearingOutside, ProfilingOutside}, forceIn-
sideOut, keepToolDownDistRatio — no start-from-outside/side-entry option.
Probe (/tmp/rp2probe/probe_outside.py): ClearingOutside with our input conven-
tion (stock outer in geometry) -> "Start point not found" on every region; with
geometry-only it merges the outside-of-islands territory into ONE region but its
StartPoint == HelixCenterPoint — it still plans a helix/ramp plunge, just one
per level instead of one per region. ProfilingOutside likewise starts at its own
plunge point outside the box. So a2d cannot supply side entries: they must be
engine-side — for OPEN regions try the existing find_shift/feed_down offset
descent (clear column + horizontal feed-in, already used for wide_fail) BEFORE
helix_entry, and keep helix as fallback for the 8 closed regions.

STOPPED — diagnosis only; nothing committed.
