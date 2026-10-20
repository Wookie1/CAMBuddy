# RT step 0 — BEFORE: straight feed-down moves, Core Front rough (current code)

Command (VibeCAD python, compute 677 s, 196,398 moves):
`engine.cli rough --step samples/core_front_setup.step --stock -128.651 128.651
-82.55 82.55 0.0 60.96 --tool flat:12.686:0.0 --floor 24.765 --leave 0.381
--stepdown 19.05 --optimal-load-mm 2.032 --stepup 1.905
--hf out/core_front_setup_hf.npy --min-rest 0.5`
(output out/core_front_roughRT_before.ngc; classification via
engine/probe_rt_plunge.py, live stock replay vs out/core_front_setup_hf.npy)

Straight feed-down moves (vertical G1):
- axial      = 386   (stock stands above the move's end Z within the flat
                      bottom disk -> the flat bottom cuts stock axially;
                      worst 25.65 mm of axial depth in ONE move)
- wall-only  =   0   (no descent brushes only walls: every non-air descent
                      engages stock under the flat bottom)
- air        = 2378  (footprint already cleared - the whole descent at ramp
                      feed 1270 mm/min is wasted time)

Descent length: axial 8,085.9 mm + air 31,588.0 mm = 39,673.9 mm
-> est. plunge time at ramp feed: 31.2 min (supervisor's run: 43.8 min /
2,966 plunges - same picture, more levels cut on the full connector run).

Other stats (before): rapids 106,385 mm, retracts 976, notclear links 1,349,
lifts 1,791, regions 244, clip breaks 75,833, clcheck 0.

Conclusion: (1) long air descents from the clearance plane must be G0 down to
a verified-clear height, feeding only the last ~mm; (2) retracts must go to the
minimum verified-clear height over the link, not stock-top+2; (3) the 386 axial
plunges must become helix/ramp entries (target n_axial_plunge = 0).
