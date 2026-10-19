# Task CR: optional rest pass in slope_split_finish, reachable from STEVE. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do not edit
verify/; no gate is added, relaxed or skipped - the rest program goes through every gate the finish goes through.
Today connector/runner.py run_slope_split_finish posts rough.nc + finish.nc. The engine CLI already does a rest pass:
  engine.cli finish --stl <model.stl> --tool ball:<finish dia> --rest-from <stock after finish .npy>
    --rest-tool ball:<rest dia> --min-rest 0.5 --stock-from <rough engine stock> ... (see out/run_s5.sh style).
1. catalog.py slope_split_finish: optional rest_tool_number (integer; tool must be a ball in tools/x7_tools.json,
   type/diameter/flute/shank/holder from the table; unknown tool or holder fails like today) and min_rest (number,
   default 0.5, minimum 0.1). Absent rest_tool_number = today's behaviour exactly.
2. runner: after the finish zmap (which already writes the stock after finishing with --stock-out), run the rest finish
   with --rest-from that stock, post it to rest.nc (same LNC post, program number +2, tool number = rest tool), then
   run probe_clcheck on rest.nc with the rest ball diameter (0 below CL by >0.005 mm or the run fails), then zmap the
   rest program chained with --stock-in = the finish's --stock-out, with the rest tool's flute/shank/tool-number/holder
   - all the same gates as the finish (_check_zmap_gates). check.json gets a "rest" section alongside rough/finish;
   the result summary adds rest cut length/time and the combined cycle time. All three .nc files are uploaded.
3. Tests (connector/test_connector.py): e2e with a rest tool on the synthetic part: three programs uploaded, check.json
   has rest gates, run fails if the rest tool is unknown or has no holder. Existing tests unchanged.
Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q in the FOREGROUND until green
(don't end your turn with background jobs). Short outputs.
