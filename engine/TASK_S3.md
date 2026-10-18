# Round S3 (finishing): faster links, flat-plate length test, then a corner rest pass
Rules: no MCP, no questions, do not commit (the supervisor commits), probes in engine/probe_*.py, long runs in the
foreground, keep outputs short. Do not edit connector/ (another track owns it) or verify/ (independent judge).
Baseline (full Core Front, S2c): 336 m cut, est. 3.0 h, rapids only 25 mm (all links at feed); clcheck 0; zmap 0.
Acceptance tools: engine/probe_clcheck.py <ngc> 0.25 (exact OCL, must report 0 points below CL by > 0.005 mm);
/opt/homebrew/bin/python3 verify/zmap.py ... --part out/core_front_setup_hf01t.npy (0.01-tess heightfield) chained
from --stock-in out/stock_roughG_01.npy (0 gouges, 0 rapid collisions).

1. Link speedup (engine/finish.py link logic): a link may be a G0 rapid (or short lift + rapid + descend) only where
   it is VERIFIED clear: drop-cutter along the swept XY path (sampled <= 0.25 mm, batched) shows CL + safety margin
   (param, default 1.0 mm) <= the rapid height for the whole path, and for rapids at low height also the ball's
   full footprint is clear of the part (drop-cutter already covers the part; the roughing leftover stock is above
   the part by <= the roughing allowance plus steps - so use rapid height >= max(CL along path) + margin + 1 mm
   unless you check against a stock model). Otherwise keep the existing verified feed link. Prefer: retract to the
   minimum verified-clear height, G0 across, plunge at ramp feed. Report rapid vs feed link counts and lengths.
2. Test: flat plate (no features), cut length must be <= 1.2 x the ideal raster length (area / stepover + row
   transitions) and links must be rapids or stepover moves; also a two-boss case where a rapid must lift over a boss
   (assert the rapid height clears the boss CL + margin).
3. Corner rest pass (new function + CLI flag --rest-from <stock.npy-or-zmap-heightfield>): with a PLACEHOLDER 3 mm
   ball, finish only where the 6 mm ball left > 0.5 mm above the part (use a leftover map you compute yourself from
   the engine's own drop-cutter CL of the 6 mm ball vs the 3 mm ball: cells where CL6-derived surface exceeds the part
   by > 0.5 mm; do not import verify/zmap.py). Same gouge-safe nets. Mark the tool as PLACEHOLDER in the G-code header
   comment and in stats; the LNC post must refuse it (tool not in tools/x7_tools.json) - do not add it to the table.
4. Synthetic tests for 1-3 in engine/test_finish.py; probe_clcheck == 0 on each output. Then run the window smoke
   (--window 96.8 136.8 30.8 70.8 --floor 24.765) for links and rest and report times. Do NOT run the full part.
