# RR1c-5 RESULTS (fresh session, started Fri Oct 23 22:08 MST, finished 22:55 MST — inside 2 h cap)

## (0) Step 0 — centre-band edges OPEN vs WALLED  →  ANSWER: **MIXED** → STOP (per brief)

Method (read-only, no code change): live stock BEFORE rest =
`out/rr0_ref/stock_after_rough.npy` (cell 0.1, the chain's `$R0`; note
`chain4/stock_rest.npy` is the stock *after* rest per `chain.sh:22`
`--stock-out`, so the first pass on it was discarded and redone),
centre-band zone bbox x −23.3..57.1, y −36.4..0.4 (rr_stats zone 4,
entered ladder step 4). Standing = stock top > t+0.01; a boundary point is
OPEN when live stock 0.3–0.6 mm just outside is cleared at that Z
(<= t+0.05), WALLED when it stands there. Ball-disk map (square-max,
conservative superset of the R 4.7625 footprint) checked alongside.

Per level (raw stock / planner's own `Sg >= t+0.01` criterion):

Z 44.965 (top level, entered a 0.75):
- west segment x −23.3..22.3, y −15.8..0.1 (carries all 196 top-level
  cut-feed windows, x −21.5..20.2 y −12.6..−0.4 per rr_ae2b):
  perimeter OPEN 350/477 (73%) | WALLED 127 — **WALLED along the entire
  north edge y ≈ 0.4** (wall x −21.5..20.2, y −0.2..0.1); **OPEN along the
  south side and both ends** (open x −23.3..22.3, y −15.8..−0.2).
- east segment x 34.6..57.1, y −32.9..0.1: OPEN 255/370 (69%) |
  WALLED 115 — north edge y −32.9..0.1 and east end x ≈ 57.1 walled,
  south/inner side open.
- tiny sliver x 30.7..35.5, y −36.5..−31.4: 100% open.

Z 42.965 (lower level, a 2.07–2.20):
- west segment x −23.3..22.3: OPEN 350/477 | WALLED 127 — same picture:
  **north edge y ≈ 0.4 fully walled**, south side and ends open.
- east segment x 32.5..57.1: OPEN 271/398 (68%) | WALLED 127 — north edge
  and east end walled, south open.

Ball-disk view (entry-feasibility): walls on the north edge / east end
persist; the south openings remain open even to the ball (open y −36.2..−0.5),
consistent with the two SE2 side entries actually used (step 4: d=7.0 at
Z 44.965 depth 0.17; d=9.0 at Z 42.965 depth −0.81 — entered through stock
cleared at the level).

Core Front centre band from the facts, edges asked by the brief:
- band edge y ≈ 0.4: **WALLED at both levels** (standing stock/part wall
  above the level along its whole length; corroborated by fact 3 — the
  lower-level a > ap is attributed partly to "band edges").
- east end x ≈ 57.1: **WALLED** at both levels (~108 wall points).
- west end x ≈ −23.3: raw stock just outside is cleared at 42.965 (open),
  but the ball-disk map reads it WALLED to the ball — not a usable
  outside-in entry for this tool.
- south side y ≈ −36.4 and inland gaps: **OPEN** at both levels (this is
  where the SE2 mouths are).

**Verdict: MIXED — the band's y ≈ 0.4 edge and east end are walled at
every level, the south side/inland edges are open at every level.** The
brief's change clause offers outside-in (open) or inside-out+spine-trochoid
(walled-everywhere); neither applies uniformly, so per the brief I write
Step 0 and STOP — the supervisor takes this answer to the coordinator before
any fix. No engine change was made.

## (1) Line count
`git diff --numstat 45d8685 -- engine/rest_rough.py engine/test_engine.py`
→ empty output, exit 0. **0 changed non-test lines** (budget ≤ 60 untouched).

## (2) Change with file:line
None — stopped after Step 0 because the edge answer is MIXED (by design of
this brief, commit 0f1eefb "stop after Step 0 if edges are mixed").

## (3) Report items
- Helix seeds at entry feed in rr.nc: **3** (zones 2 and 3 at Z 38.965
  r=1.946; zone 12 at Z 42.548 r=1.903) + 2 bore-descents (zone 12).
  Measured from rr.nc: ~14 mm each, dz 1.33/1.33/3.18 mm — ~42 mm total,
  **~3 s at ramp_feed 850** (allowed but slow, as the brief predicts).
  The centre band itself used NO helix seed (step-4 SE2 entries).
- Lower level a vs ap: cut-feed windows at Z 42.965 in the band read
  a = 0.03..2.75 (brief's overload family a 2.07–2.20, max ae_eq 4.14);
  ap = 2.0 → exceeded wherever the ring hugs the walled north/edge stock.
- Cusp-adjusted level step: ball R 4.7625, ae 1.905 → scallop cusp
  c = R − √(R²−(ae/2)²) = **0.096 mm** (brief's ~0.10); stepping levels at
  ap − c = **1.904 mm** instead of 2.0 would keep the lower level's
  a ≤ ap (2.07–2.20 becomes ≤ 2.0 before the band-edge wall contribution).

## (4) Exit codes (all commands run by me, foreground; tests/analysis via
scratchpad/slot_m4.sh only; no Core Front job)
- Step 0 pass 1 (first version, chain4 stock_rest.npy — superseded, wrong
  stage of stock): first attempt waited on the slot (held by live job
  bs1a4c2_mytest.sh PID 23267, not stuck) and I killed it at a 15-min
  tool timeout before it took the lock (no stale lock left; verified).
- Step 0 pass 2 (same file, refined sampling): `EXIT=0`.
- Step 0 pass 3 attempt on rr0 excess map grid mismatch (`centre-band comp
  not found`): `EXIT=1` — superseded by the corrected pass below.
- Step 0 FINAL (stock_after_rough.npy, pre-rest): `EXIT=0`.
- ae2b/nc cross-checks of rr_ae2b.json + rr.nc (report-only numbers):
  `EXIT=0`; reproduce the brief exactly: 44 windows over 2.286, 83.3 mm,
  both levels Z 44.965/42.965, x −21.5..20.2 y −12.6..−0.4.
- No engine tests were run: no code was changed, so there is nothing to
  gate; existing suite untouched (engine/test_engine.py unmodified,
  `git status` clean apart from the pre-existing session `opencode.json`
  copy made by the supervisor's run_rr1c5.sh at launch — never edited here).
- Fail-on-45d8685: N/A (no new tests, per STOP).

## (5) Not done (by design — MIXED stop)
Change items (1)-(3), the three new tests, and anything gated on a fix: NOT
implemented, per the brief's Step 0 STOP clause. Locks untouched
(m4slot.prio / m4model.busy never written; m4small.lock created/dropped
only by slot_m4.sh itself; at 22:50 it is owned by another live session's
PID — left alone). Nothing committed.
