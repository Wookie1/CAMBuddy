# Task G (round 7, track A): rest-aware roughing
Same rules: no MCP, no questions, do not commit, probes in engine/probe_*.py, spike/ untouched, run long jobs in
the foreground (the session must not end while a run is going). Do NOT create engine/finish.py (another track owns it).
Baseline: out/core_front_roughF.ngc / out/bench_engine_rough2.json (ours 49.5 min, p95 14.1; Fusion 17.5 min, p95 5.27).
Fusion's measured levels: 47.62 45.72 43.81 41.91 40.0 38.1 36.2 24.95 = big levels + 1.905 mm rest step-ups.

1. engine/stock.py: the engine's own stock heightfield (same grid idea as zmap but written independently; do NOT
   import verify/zmap.py). Updated by each level's paths with the tool footprint (flat/bull disk is fine).
2. Per level, build Adaptive2d stock paths (Execute's first argument) from the stock heightfield: cells where stock
   top > level Z + axial leave -> marching squares -> small dilation. Adaptive2d then skips cleared area and can
   enter from open sides instead of helixing.
3. Step-up levels: after each big 19.05 mm level, add levels every 1.905 mm upward from it, clipped to where
   remaining stock above the part is > ~1 mm. Replaces the full-area intermediate levels. Print the level list
   with the area machined at each.
4. Links: stay tool-down within a level when the stock model shows the straight link at cutting Z (or Z+1 mm) is
   clear; retract to clearance only between levels or when blocked. Use Adaptive2d keep-tool-down options.
   Keep the hard allowance post-check passing.
5. Benchmark vs Fusion (out/fusion_rough.ngc), same as round 6, with zmap --flute 25.4: gouges 0, rapid
   collisions 0, leftover mean/p95/max, within_0p5mm, length by 5 mm Z band, time, retract count.
   Goal: time <= 1.5x Fusion (26 min) and p95 <= 1.5x Fusion (7.9 mm). Write out/bench_engine_rough3.json.
Run both test suites before finishing (verify: /opt/homebrew/bin/python3 -m pytest verify -q; engine:
/Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_engine.py) and add tests for stock.py.
