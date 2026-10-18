# Task L: remove Autodesk-derived references (James: "we need to avoid violating Autodesk TOS")
Rules: no MCP (never use any Fusion/fusion360 tool), no questions, do not commit, never contact the internet,
probes in engine/probe_*.py. Do NOT edit spike/ (archive) or the TASK_*.md briefs (historical prompts).
The vendor post (.cps) and reference/1001.nc have been REMOVED from the repo; do not look for them anywhere.

1. engine/post_lnc.py: rewrite its conventions to follow docs/lnc5800_post_spec.md (read it fully) and cite rule ids
   (P1..P13, N1..N7) in comments instead of "learned from 1001.nc" or "the vendor createFormat". Remove every
   mention of 1001.nc, the vendor post, Fusion and createFormat/forceDecimal-style names. Spec changes vs today:
   P8 dwell `G04 X<s>.` by default (option --dwell-p-ms to emit `G04 P<ms>`), P13 add `M05` after `M09`.
   Keep number formatting and modal rules (N1-N6), CRLF (N7), tool table lookup.
2. engine/test_post.py: delete the structural diff vs 1001.nc. Add a spec test: post a small synthetic program and
   check each P/N rule (header order, comment form, integer addresses without points, decimals, -0., modal
   suppression, footer order incl. M05). Keep the number-format edge-case tests and the zmap-equivalence test
   (posted inch vs neutral mm of out/core_front_roughG.ngc).
3. Remove Fusion output/figures from tests, bench files and docs: engine/bench_engine_rough2.json,
   engine/bench_engine_rough3.json, engine/post_report.md (rewrite as a short report on the spec-based post),
   anything in engine/ or verify/ that zmaps or compares Fusion G-code, Fusion leftover/time numbers in comments
   and docstrings (engine/cli.py, engine/rough.py, engine/test_engine.py, verify/zmap.py, verify/test_zmap.py).
   New bench file engine/bench_engine_rough.json with ABSOLUTE criteria only for out/core_front_roughG.ngc
   (rerun zmap: gouges, rapid collisions, over-flute 25.4, leftover vs allowance 0.381 mm mean/p95/max,
   within_0p5mm, cutting length, est. time).
4. Cutting data defaults (stepdown 19.05, optimal load 2.03, leave 0.381, rpm 7500, feeds 3429/1270) are James's
   own numbers: label them "James's cutting data" in cli help, comments and docs, never "Fusion's".
   tools/x7_tools.json: describe it as James's X7 tool table (no 1001.nc mention).
5. Rename "Steep & Shallow"/"SteepShallow" to "slope-split finishing" in anything user-facing in engine/, connector/,
   docs/ (engine/finish.py lives on another branch: skip it).
6. Final check: `grep -rniE "fusion|1001\.nc|autodesk|\.cps|cadpro" engine connector verify tools docs`
   must return only docs/lnc5800_post_spec.md's sourcing note (if any) - print the grep output.
Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q and engine/test_engine.py (VibeCAD python).
