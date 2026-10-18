# Task I (round 9a, track A): tool table + zmap first-Z fix. Small; do both, then stop.
Rules as before (no MCP, no questions, do not commit, probes in engine/probe_*.py, spike/ untouched, do not touch
engine/finish.py, foreground runs).
1. tools/x7_tools.json: map tool specs to the X7's numbers. Seed from reference/1001.nc: 0.5 in bull nose, CR 0.005 in
   -> T3 / H03 / D03. post_lnc.py looks the tool up there (match type + diameter + corner within 0.001 mm);
   --tool-number still overrides. Not in table and no number given -> refuse with a clear error (no silent T1).
   Re-post out/core_front_rough_X7.nc (must read T3 / H03). Tests for lookup, override, refusal.
2. verify/zmap.py --jobs: a leading XY-only rapid before the first Z word = "Z unknown, above stock", not Z=0.
   Fix in verify/ only (zmap must not import engine code). Test with a program that starts like 1001.nc
   (G00 X.. Y.. then G43 Z3. H03). Then remove the first-Z normalisation workaround from engine/test_post.py and
   confirm --jobs 4 and --jobs 1 agree on reference/1001.nc rough section and on our X7 file.
Run /opt/homebrew/bin/python3 -m pytest verify -q, engine/test_engine.py and engine/test_post.py before finishing.
