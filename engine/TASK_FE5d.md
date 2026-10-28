# Task FE5d: why did FE5 not ramp ONE entry that had the run? DIAGNOSE, then stop (~40 lines of findings, no fix).
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; do NOT edit engine/ or verify/ (read only; scripts under
out/ only). Do NOT touch opencode.json. You run on this Mac's own model: you must NOT run any Core Front engine or zmap
job - work only from the files already in out/ and from reading the code. NEVER print NGC/G-code contents or large
outputs into your context (use grep -n for one line, sed -n 'Np' for a single line, wc, head -3). Cite only files that
exist and commits `git log` shows. If blocked, write the question into engine/FE5d_RESULTS.md and stop.

## The case (supervisor's measurement)
out/fe5_finish.nc (FE5-ramped interim finish, branch fe5 4cc49d9): ZB flags a ball axial plunge at NC line 52593,
XY (-8.68, 17.19), depth 2.826 mm. The contiguous feed run at that pass's Z after the entry is 81.6 mm; a 2-degree ramp
needs L = depth / tan(2 deg) = 80.9 mm. So the run existed, yet the entry was not ramped (or the ramp failed).
## Find out which (file:line for each claim; the NC line numbers involved)
- did the FE5 estimator (engine/entry_depth.py) flag this entry (depth > 0.25)? see out/fe5_est_finish_entries.json /
  out/fe5_est_finish_ramped_entries.json and out/t_fingen_track*.log
- was the ramp skipped in engine/finish.py (which condition), or emitted but with a segment steeper than 15 deg
  (ZB's MAX_RAMP_DEG), or emitted on a different run than the one the entry descends onto?
- is the run measured differently by the ramp code (vertex run, s_run) than by the supervisor's contiguous-Z run?
Write engine/FE5d_RESULTS.md with the findings. Then stop.
