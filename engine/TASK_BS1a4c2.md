# Task BS1a4c-2: every emitted band cutting chord is CL-checked; a discontinuous trochoid is split or rejected. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances; add NEW tests only.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; never relax a gate or
tolerance; do NOT edit verify/ or opencode.json; engine code never imports zmap/verify; no margin/leave/feed change.
Edit engine/band.py, engine/rough.py (band-path emission only) and engine/test_engine.py only.
BUDGET: <= 30 changed non-test lines vs 351ce50 (`git diff --numstat 351ce50 -- engine/band.py engine/rough.py`, adds +
dels), STOP at ~45. FRESH session, HARD CAP 2 h (run `date`). FOREGROUND RULE: run every command in the foreground
and wait; the session ends when you end your turn. Never print NGC/G-code or large outputs; rg / sed -n line ranges.
Tests ONLY via scratchpad/slot_m4.sh (ENGINE_WORKERS <= 4); engine tests are NOT pytest (VibeCAD python, call the
functions; full suite `.../python engine/test_engine.py`). NO Core Front job. Worktree
/Users/James/ai-sandbox/stevecam-bs1a4, branch bs1a4 at 62ad686 (= 351ce50 + briefs). Read `git show 351ce50` first.

## Facts (supervisor, instrumented copy of 351ce50, test_bs1a_lshaped_channel)
The rough's CLCHECK refuses the program: bad moves 2068 and 2107. Moves 2067 -> 2068 are a 5.4 mm straight move at
CUTTING feed, (-3.08, 2.47) -> (-4.87, -2.57) at Z 0.381, INSIDE one emitted band trochoid path (the path is
discontinuous: two loops joined by a straight chord across the part). The emit loop checks band paths with isl_ok on
their POINTS only, so the chord reaches CLCHECK. With honest credit both L-channel regions fail every shrink level
(failed_region_emitted: (-18.72,-0.12) shrink1 engine 15.25; (-2.09,5.74) shrink0.4 engine 13.5); the chosen shrunk
path contains the jump. credit_fallback = [].

## Change
(1) Every emitted cutting chord of a band path is CL-checked, SEGMENT-SAMPLED the way validate_exact samples segments
    (every 0.25 mm), not only its points. A discontinuous trochoid is split at the jump into separate paths joined
    through enter_at's CL-checked ladder; if no legal join exists, that piece is rejected and listed in
    stats["failed_region_emitted"].
## Report only (no fix)
(a) For each of the two L-channel regions (engine 15.25, 13.5): is its max window the region's FIRST window, at its
    entry? (Suspected: the start-centred credit disk vs the real off-centre helix bore + floor circle over-read.)
(b) grep engine/rough.py and engine/band.py for every other emit path checked only by its points (a2d paths, rings,
    floor circles, links): list them with file:line.
## Test - must FAIL BY ASSERTION on 351ce50 (`git archive 351ce50`, never checkout)
A band path with a jump across the part: CL refusal or a chord below CL + leave on 351ce50; after the change the
program passes CLCHECK and the jump is split or rejected-and-listed. Full engine/test_engine.py; paste exit codes.
## STOP rule
If test_bs1a_lshaped_channel then fails on LOAD (not CL) and (a) says first-window over-read: stop and report - that is
expected until BS1a4d.
## engine/BS1a4_RESULTS.md: add section (12) BS1a4c-2 - change with file:line, line count, (a) and (b), PASTED exit
codes + fail-on-351ce50 output. Then stop.
