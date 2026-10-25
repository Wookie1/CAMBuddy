# Task RR1c-4: rest-rough load - cut levels top-down and rings inside-out; plan the small fragments. Build, then report. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests (or new assertions
inside your own new tests) only. If an existing test conflicts with the change, STOP and write that in the results file.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/ or opencode.json; no leave/margin change; the T20 values stay connector defaults (never in engine code). Edit
engine/rest_rough.py and engine/test_engine.py only.
BUDGET: <= 90 changed non-test lines vs d46a04a (`git diff --numstat d46a04a -- engine/rest_rough.py`, adds + dels),
STOP at ~130. FRESH session, HARD CAP 2 h. Never print NGC/G-code or large outputs; rg / sed -n line ranges, never read
big files whole. Small tests ONLY via the small-test lane
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(ENGINE_WORKERS <= 4). NO Core Front engine or zmap job - the supervisor runs the Core Front chain judge.
Worktree /Users/James/ai-sandbox/stevecam-rr1b, branch rr1b at d46a04a.

## Load bar (set from ZE2B, verify/zmap.py --engage-max 2.286, read-only use)
At cutting feed: 0 mm with ae_eq over 2.286 and 0 full-width windows (w_plan flag). Entry-feed floor circles are listed
separately (by design). Today the Core Front fails it: 41.6 mm over 2.286, all in ONE zone (centre band, levels
41.543 / 42.965 / 44.965), all at Z 42.965 with a = 2.75, w_plan 5.2-5.8, ae_eq up to 4.28 (worst at (-20.35,-6.4)).

## Diagnosis (supervisor)
The rough left a flat 3.26 mm block there (stock 45.72 over a part floor at 42.46).
1. Level order. The entry loop (rest_rough.py ~533-596) tries levels from the LOWEST up and enters the first one it
   can (here 41.543). The cut order (~628-629) is the entered level, then the ones below it top-down, then the ones ABOVE
   it bottom-up. So 42.965 is cut while the stock above it still stands at 45.72: a = 2.75 > stepdown 2.0. The
   44.965 level comes after it and cuts mostly air.
2. Ring order. Rings are stepped c = ae/2, 3ae/2, ... in from the region boundary (~641-651). The entry aims at the
   OUTERMOST ring (c = ae/2, ~538) and the passes go greedy-nearest (~697-700). So the outer ring is cut first, against
   the whole uncut inside: w_plan ~= R + ae/2 = 5.71 instead of ae.

## Change
1. Cut a zone's levels TOP-DOWN. Enter at the highest level that has a legal entry (with the same one ladder, same rules,
   no new entry type), and cut it before every lower level. Each lower level is re-entered from the level just cleared,
   as RR1c-3 already does. No level may be cut while stock that a higher level of the same zone would remove still
   stands above it.
2. Cut each level's rings INSIDE-OUT, so every ring after the first removes <= ae: innermost ring (largest c) first,
   then outward. The entry is at the innermost ring (or the region's deepest-Dz point, as the argmax fallback already
   does). Links follow the current rules.
3. Fragments (find_zones ~110, area < 5 mm2): merge a fragment into a neighbouring zone's mask when it lies within the
   tool radius of that zone. Otherwise plan it as its own mini-zone, which is cut only where the existing entry ladder
   finds a legal entry. A fragment that is neither merged nor entered stays in fragments_dropped, with a reason.
   Nothing is ever dropped silently.

## Tests (engine/test_engine.py) - each new test must FAIL BY ASSERTION on d46a04a (`git archive d46a04a` extract, never checkout)
- Plateau block: a flat floor with a 3.3 mm rest block over it plus a lower legal entry pocket, so today's code enters
  low and cuts under the block. After the rest-rough, ZE2B (verify/zmap.py) shows 0 mm over 2.286 at cutting feed and
  0 full-width cutting windows, and no level cuts deeper than the stepdown + 0.01 below live stock. Every move is
  CL-legal (exact clcheck as in the existing rr tests).
- Fragment: a sub-5 mm2 excess patch next to a zone is cut (live stock <= CL + leave + 0.1 there), and a lone sub-5 mm2
  patch is either cut with a legal entry or listed in fragments_dropped with a reason.
Keep every existing test green (full engine/test_engine.py at the end).

## engine/RR1c4_RESULTS.md (required)
(1) line count; (2) change with file:line; tests with exit codes; fail-on-d46a04a proof; (3) anything not done. Then stop.
