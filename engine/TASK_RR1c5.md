# Task RR1c-5: rest-rough rings meet <= ae everywhere, opened from cleared stock; links never cut. Step 0 first. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate, the
validate_exact tolerance or the leave; do NOT edit verify/ or opencode.json; engine code never imports zmap/verify;
cutting values are parameters only (no feed reduction). Edit engine/rest_rough.py and engine/test_engine.py only.
BUDGET: <= 60 changed non-test lines vs 45d8685 (`git diff --numstat 45d8685 -- engine/rest_rough.py`, adds + dels),
STOP at ~80. FRESH session, HARD CAP 2 h (run `date` at start). FOREGROUND RULE: run every command in the foreground and
wait for it; the session ends the moment you end your turn. Never print NGC/G-code or large outputs; rg / sed -n line
ranges. Tests ONLY via scratchpad/slot_m4.sh (ENGINE_WORKERS <= 4); engine tests are NOT pytest (VibeCAD python,
call the functions; full suite `.../python engine/test_engine.py`). NO Core Front job - the supervisor runs the judge.
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at the commit carrying this brief (= 45d8685 + briefs).

## Facts (supervisor, Core Front chain4 on 45d8685, from the program and the zmap ZE2B dumps)
All 83.3 mm of cutting-feed overload (> 2.286; 44 windows, max ae_eq 4.14; 8 full-width windows / 46.7 mm) is in
ONE zone, the centre band (bbox x -23.3..57.1, y -36.4..0.4), entered at its top level (Z 44.965, a 0.75) and cut
top-down (Z 42.965, a 2.07-2.20). 42 of the 44 windows are new vs the previous chain.
1. Inside-out from fixed boundary offsets (c = ae/2 + k*ae) leaves each neck with no cleared seed. At Z 44.965 the
   zone's rings are: two TINY innermost loops (only where the band is widest, near x 14 and x -15), then one long ring
   over the whole band (every top-level window is on it, w_plan 3.5-5.1 vs ae 1.905; the chord at a 0.75 is 5.15),
   then the outermost ring. The same family repeats at Z 42.965 (w_plan 3.7-7.7). The plan assumes each ring removes
   ae; nothing in rest_rough checks it.
2. A link cuts: the two tiny loops are joined by a straight ~31 mm move at the RAMP-FEED parameter through the uncut
   spine, at both levels (at Z 42.965: ae_eq 3.98 over 31.7 mm, w_plan 7.7). Links are emitted when CL-legal and short;
   they are not checked to be stock-clear.
3. Lower level a = 2.07-2.20 > ap 2.0: the upper level's ball scallop (cusp ~0.10 at ae 1.905) plus the band edges.

## Step 0 - REPORT ONLY, before any code change (write it in the results file)
Per level of the centre-band-like zones you reproduce: is each boundary segment OPEN (live stock clear just outside at
that Z) or WALLED? Also answer it for the Core Front centre band from the facts above (its band edges at y ~ 0.4 and
the ends). If the answer is MIXED (some edges open, some walled), write Step 0 and STOP - the supervisor takes that
answer to the coordinator before any fix.
## Change
(1) Open from cleared stock - a spine / centre-line pass in uncut stock is itself a slot (fails full width; ae_eq
    ~0.67 x chord), so never cut a gap from inside raw stock:
    - OPEN edges: order the rings OUTSIDE-IN from those edges, so each ring's cleared side is the open edge or the
      previous ring.
    - WALLED everywhere: inside-out from the bore, with the necks between the innermost loops opened by a trochoid along
      the spine (the ball version of BS1a), each loop meeting <= ae.
    - Helix bores at entry feed are allowed as seeds but slow: report their count and time.
(2) Engagement check before emit: every ring meets <= ae against the LIVE stock (the planner's own disk model). A ring
    that still fails after the fallbacks is NEVER silent: list it in stats["rr_ring_failed"] with place, Z and the
    measured w_plan / ae_eq (same rule as failed_region_emitted).
(3) No link cuts: a feed link at depth must be stock-clear at the cutting Z (stock.link_clear, 0.05 tolerance);
    otherwise it goes through the existing ladder (lift / re-entry).
(4) Report only: the lower-level a vs ap, and what the level step would be if spacing were ap minus the upper level's
    cusp.
## Tests (engine/test_engine.py) - each NEW test must FAIL BY ASSERTION on 45d8685 (`git archive 45d8685`, never checkout)
- a varying-width band (tiny innermost loops + an uncut spine, like the centre band);
- an open-edge proud block;
- a fully walled band.
Each: zmap (verify/zmap.py, padded part grid, --engage-max 2.286) shows 0 mm over 2.286 and 0 full-width windows at
cutting feed, and no feed link at depth crosses standing stock. Every existing test passes unchanged; full
engine/test_engine.py green. Run every test yourself and paste the exit codes.
## engine/RR1c5_RESULTS.md (required)
(0) Step 0; (1) line count; (2) change with file:line; (3) report items (helix seeds count/time, lower-level a vs ap,
cusp-adjusted step); (4) PASTED exit codes + fail-on-45d8685 output; (5) anything not done. Then stop.
