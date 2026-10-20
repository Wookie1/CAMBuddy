# Task RP step 0: DIAGNOSIS ONLY - why roughing fragments into 213 regions / 2,342 clip breaks. No code changes to the
generator (instrumentation behind an env flag or a separate engine/probe_rp.py is fine; nothing committed).
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; do not edit verify/; no gate changes.
Context: RT2 on Core Front T13 (out/rt2_after.ngc, branch rough-travel-2) passes zmap with 0 axial plunges but has 213
regions / 2,342 clip breaks; round G had 14 regions, rapids 38.2 m, p99 5.03 (but axial plunges). Rapids 78.7 m, entry
time and p99 12.686 scale with the fragmentation.
Hypothesis to confirm or refute WITH NUMBERS: Adaptive2d's output is clipped after the fact against the safe boundary
(part offset / CL-grid islands / allowance / stock box / RS stock clip), which acts as a post-pass and fragments the
paths. The alternative: hand Adaptive2d the safe region itself as its input boundary so its paths need no clipping, and
keep the clip only as an assertion that fails if it would remove more than a trace.
Report per Z level (engine/RP0_RESULTS.md, < 80 lines): regions, clip breaks, and for each clip break WHICH clip produced
it (island/part-offset, allowance, stock box/RS, link-not-clear split, other) with counts and total clipped length; how
much Adaptive2d path length each clip removes; whether Adaptive2d's input boundary already equals the safe region (and if
not, how they differ - area/perimeter per level). End with a yes/no on the hypothesis and the expected effect of feeding
the safe region as the Adaptive2d boundary. Then STOP.
