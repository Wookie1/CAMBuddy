# Task H (round 8, track A): X7 post, engine/post_lnc.py
Rules as before: no MCP, no questions, do not commit, probes in engine/probe_*.py, spike/ untouched, long runs in
the foreground. Do not touch engine/finish.py. reference/*.cps is the vendor post: you MAY read it to understand
options, but write our own code and copy NONE of it. The target format is reference/1001.nc (James's SyilCNC -
LNCv2 post, runs on his LNC 5800). Learn conventions from the .nc output.

post_lnc.py turns the engine's neutral moves into G-code shaped like 1001.nc:
- Header: %, O<number>, tool comment "(T<n> D=<dia> CR=<cr> - ZMIN=<min z> - <type>)", "G90 G94 G17 G49 G40 G80",
  G20 or G21, "G53 G00 Z0.". Add a comment line stating cutter comp is OFF (paths are tool centre).
- Per op: "(<OP NAME>)", "T<n> M06", tool description comment, "S<rpm> M03", "G04 P3000", work offset (G54 param),
  M08, first XY rapid, "G43 Z<clear> H<n>", then motion.
- Number formats exactly as 1001.nc (inch: 4 decimals, trailing zeros trimmed, "3." for integers; mm per the .cps
  conventions), modal G and F suppression as 1001.nc does it, F formatting.
- Footer: exactly what 1001.nc ends with.
- Units: default G20 inches; --metric for G21. Arcs: G02/G03 with I/J in G17 only if engine paths contain arcs,
  else lines. No G41/G42.
- CLI: `python -m engine.cli post --in <neutral or engine output> --out F [--metric] --program 1001 --op-name ...`
  (or add --post lnc to `rough`). Output out/core_front_rough_X7.nc from the round-7 roughing (out/core_front_roughG).
Tests (engine/test_post.py, runnable with VibeCAD python or homebrew python3 if no ocl needed):
 a. structural diff of our posted rough program vs reference/1001.nc over every NON-motion line (header, tool
    change, footer): only tool number, op name, rpm, ZMIN-type values may differ. Print the diff summary.
 b. zmap the posted inch file and confirm results identical (within 1e-3) to the neutral metric run
    (out/core_front_roughG.ngc): gouges, leftover stats, cutting length.
 c. number-formatting edge cases: 0, negatives, 1.0, 0.00005 rounding, -0.0.
Write out/post_report.md: structural diff result + anything about the LNC format you could not match.
Run /opt/homebrew/bin/python3 -m pytest verify -q and the engine tests before finishing.
