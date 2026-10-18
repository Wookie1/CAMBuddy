# GATES_NOTES.md — Engine Gate Findings

## synth_pocket rough rapid collisions

The e2e test `TestSlopeSplitFinish::test_e2e_chain_rough_then_finish` triggers
a zmap gate failure on the roughing pass for `connector/testdata/synth_pocket.step`.

- **Part**: `synth_pocket.step`
- **Stage**: roughing (adaptive_rough)
- **Gate**: `rapid_collisions["rough"]` > 0
- **Cause**: The 0.1 mm zmap heightfield is more sensitive than the 0.5 mm
  roughing clip grid, so rapid moves (G0) into stock regions that the coarser
  grid didn't flag show up as collisions.
- **Impact**: The gate correctly rejects the run (state=failed, no .nc uploaded).
  The e2e test is marked `xfail(strict=True)` so it flips to pass once the engine
  is fixed to avoid these rapid collisions.

Run the test without `xfail` to capture exact counts, first line, and XY:
```
cd connector && python3 -c "
# inspect the check.json from a failed run for rapid_collisions details
"
```

## Resolved (2026-10-18)
After merging the S3/S3b engine work (stock-aware verified rapids) into main, the synth_pocket chain
has 0 rough rapid collisions: the strict xfail flipped to XPASS and the marker was removed.
