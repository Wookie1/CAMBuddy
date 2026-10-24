# RR1c-5c RESULTS (fresh session, started ~01:15 MST, finished 02:03 MST — inside 2 h cap)

## (0) Root cause (measured, not assumed)
On dda4ed0 the closed 20x20 pocket IS entered by the RR1c-4b bore (helix r=4.960
to Z 24.2, rise inside the bore, both bore-descents recorded). The deep entry is
NOT the descent — it is the level-entry link: after the rise, the link from the
bore rim (24.86, 19.9, Z 28.2) to the first ring start fails dda4ed0's new
"link must be stock-clear at the cutting Z" check, so the ladder runs and
**step1 plunges axially at (18.4625, 18.7), Z 28.2**. The planner's live model
(fine = stock cell 0.5) measures that column at depth 0.017 <= shallow, but the
helix leaves an uncut core (a ball R 4.7625 on the r 4.96 helix never reaches
rho < r_h - R ~ 0.2 mm of the axis) and the judge's fine=0.1 model reads it as
**1.476 mm of live stock** — exactly the failing entry (line 196). On 45d8685
the same link was a CL-checked horizontal feed from the bore rim (not scored,
no axial plunge).

## (1) Line count
`git diff --numstat dda4ed0 -- engine/rest_rough.py` -> `15  4`
**19 changed non-test lines (adds+dels) <= 20.** Locks untouched
(m4slot.prio / m4model.busy never written; m4small.lock created/dropped only
by slot_m4.sh itself — verified none left). engine/test_engine.py: +33/-1,
the single "-" line is the `_main` registration tuple extended with the new
test name; no existing test, assertion or tolerance changed.

## (2) Change (engine/rest_rough.py only, plus ONE new test)
- **rest_rough.py:826-831** — the level-entry link check: a bore-seeded zone
  (`mode == "bore"`, `r_h > 0.0`, tool already at level Z after the in-bore
  rise/descent, `dzd <= 1e-9`, prev on the bore circle within CELL) keeps the
  RR1c-4b entry: an exact-CL-checked (`cl_ok_path(lp)`) feed-in from the bore
  replaces the ladder, so step1 can never plunge into the hidden bore core.
  The lower levels' entries through the bore (helix + stepped descent, each
  step exact-CL + live-ZB <= 0.5) are RR1c-4b's, unchanged (rest_rough.py
  691-712). Everything else — open-edge stock-clear link rule, ladder, fronts,
  engagement/axial reports, ZB floor, validate_exact tolerance, leave — as is.
- **rest_rough.py:356-359** (`g0`) — land 0.2 mm above the coarse live column
  top instead of 0.01: at cell 0.5 `disk_top` under-reads the true column top
  by up to ~0.1 mm, and every SE2 diversion that dda4ed0's link check creates
  ends in a G0 drop that then grazes live stock. This was needed to reach the
  brief's required full-suite green: **test_rr1c2_cf_rapid_shapes_clear_stock
  is a THIRD pre-existing dda4ed0 regression the brief did not list** — it
  passes on 45d8685 (verified via `git archive`, EXIT=0) and fails on pristine
  dda4ed0 with "rapid through live stock: 13 pts (worst 0.113)". Raising the
  landing margin tightens rapid clearance (never relaxes a gate); entry depths
  are read at the descent end and are unchanged.
- **test_engine.py:1716** — NEW `test_rr1c5c_closed_pocket_bore_entry_no_deep_axial`:
  closed-pocket bore-seed case, ZB — no scored entry deeper than 0.5 into live
  stock (registered in `_main`).

## (3) Tests — PASTED exit codes (all run by me, FOREGROUND, via scratchpad/slot_m4.sh, ENGINE_WORKERS<=4; no Core Front job)
Gate set (2 previously failing + 4 RR1c-5b + new + rr1c2):
```
PASS test_rr1c4b_closed_pocket_bore_levels (1s)
PASS test_rr1b_rest_rough_synth_pocket (1s)
PASS test_rr1c5b_varying_width_band_fronts (1s)
PASS test_rr1c5b_open_edge_proud_block (1s)
PASS test_rr1c5b_fully_walled_band_bore_seed (0s)
PASS test_rr1c5b_mixed_band_core_front (1s)
PASS test_rr1c5c_closed_pocket_bore_entry_no_deep_axial (0s)
PASS test_rr1c2_cf_rapid_shapes_clear_stock (1s)
EXIT=0
```
Full suite `python engine/test_engine.py` (42 registered tests, incl. the new
one): `0 failure(s)` — **EXIT=0**. (First full-suite run, before the g0
margin fix: EXIT=1 with the single pre-existing rr1c2 failure, 11 pts worst
0.074; see (4).)

## (4) Fail-on-dda4ed0 (git archive dda4ed0 into /tmp/rr1c5c_dda4ed0, current
test file copied in — never checked out):
```
FAIL BY ASSERTION on dda4ed0 (expected): bore-seed level entered by axial
entry into live stock: [{'line': 196, 'x': 18.462, 'y': 18.7, 'z': 28.2,
'depth_mm': 1.4761090163473511, 'deep': False}]
EXIT=1
```
— exactly the 1.48 mm entry at (18.462, 18.70), Z 28.2 from the brief.
Pre-existing rr1c2 status check on pristine dda4ed0: `FAIL ... 13 pts (worst
0.113)`; on 45d8685: `PASS` (both run via slot, EXIT=0 for the harness).

## (5) Not done / notes
- Nothing else changed; nothing committed. Working tree: engine/rest_rough.py,
  engine/test_engine.py modified (+ this file).
- The bore's uncut core (rho < r_h - R) is inherent to a 2-deg helix whose
  radius exceeds ball reach; this round removes the *deep axial plunge* into it
  (entry now via bore + CL-checked feed-in at level Z, as RR1c-4b). The core
  itself is still removed only by the level's ring passes, as on 45d8685.
- No stuck slot observed: every slot_m4.sh call acquired the lock and completed
  in the foreground; no locks were created, removed or edited by hand.
