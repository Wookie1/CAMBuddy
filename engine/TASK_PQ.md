# Task PQ: finishing must stay gouge-free at the post's output precision. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do not edit
verify/ or the clcheck checkers (engine/probe_clcheck.py) - they are the judges.
Problem (supervisor-found): finish_neutral.ngc writes 4-decimal mm and has 0 points below CL, but engine/post_lnc.py
rounds mm to 3 decimals (inch: 4 decimals = 0.00254 mm). At vertical-wall CL jumps the rounded XY lands on the low side
of the jump: 25 posted points below CL, worst 3.201 mm (X-30.492 Y34.737 Z4.050, neutral X-30.4925 Y34.7375). The
connector's clcheck gate correctly fails the slope_split_finish chain.
Fix, in the engine (where the CL model is), NOT by changing post rounding:
1. Finishing takes the output grid (--post-grid-mm, default 0.001; 0.00254 for inch output; the connector passes the
   grid that matches its post units). For every emitted point: of the 4 neighbouring output-grid XY points, pick the one
   whose exact drop-cutter CL is closest to the point's original Z (normally the open side of the wall, never a jump up
   the wall); Z = that CL rounded UP to the grid (never down). If |chosen CL - original Z| is still > 0.01 mm, DROP the
   point (no one-point spikes); the segment between its neighbours must then pass the existing one-sided net check,
   else split/retract as today. Write the neutral file with enough decimals that the post's rounding is a no-op on the
   snapped values (test: post(neutral) coords == neutral coords). No checker tolerance changes.
2. Remove the two xfail markers in connector/test_connector.py (lines ~680 and ~787) - they must PASS now.
3. Post header bug: for ball tools the header prints CR=0.; CR must be D/2 for ball, the table corner radius for bull,
   0 for flat. Fix where the corner value comes from, add a test.
4. Test: a synthetic vertical-wall part where a CL jump sits between grid points; posted program has 0 points below CL
   by engine/probe_clcheck.py.
Acceptance (supervisor re-runs): /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q plus the VibeCAD-python engine suites (/Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_engine.py and engine/test_finish.py) all pass with no
xfail; Core Front T20 finish posted metric passes probe_clcheck with 0 below CL. Short outputs.
