# Task UN: every action honors the requested units. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; NO gate or
threshold change; verify/ must NOT import engine/.
Found by the supervisor: adaptive_rough posts G20 (inch) even when units "mm" is requested (connector/runner.py never
passes --metric to the rough's LNC post), while slope_split_finish always posts the finish and rest with --metric even
when inch is requested. The result JSON then states the requested units, not what was posted.
1. connector/runner.py: rough, finish and rest posts emit G21 when values["units"] == "mm" and G20 when "inch" (pass
   --metric only for mm). For inch output the finish/rest must also use the matching post grid (--post-grid-mm 0.00254
   for inch, 0.001 for mm) so PQ's snap stays a no-op on posting.
2. After every post, read the program and FAIL the run (EngineError) unless its G20/G21 matches the request; result JSON
   reports the posted units per program.
3. check_program unchanged: it keeps reading units from the program itself.
4. Tests: connector e2e roughs the test block once with units mm (posted G21, values in mm) and once with inch (G20),
   both passing all gates; the post-units assertion fails a run whose posted units differ (fake _spawn, existing
   pattern); finish/rest argv carry --metric and --post-grid-mm 0.001 for mm, no --metric and 0.00254 for inch.
Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q in the FOREGROUND until green. Short outputs.
