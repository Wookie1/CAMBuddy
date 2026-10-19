# Task Z5b: heightfield grid always covers stock + tool radius + 5 mm (on top of the Z5 changes here). Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT
change any zmap failure (stock-coverage, tess_tol, outside_grid all stay failures exactly as in this worktree);
verify/ must NOT import engine/.
The supervisor ran this worktree's zmap on two real roughs: outside_grid fails them (19,762 / 15,445 moves) because
their heightfields were tight. Decision: keep the failure; fix the grids in ONE shared builder.
1. verify/heightfield.py: new inputs STOCK_BOX="xmin xmax ymin ymax" (env, or --stock-box) and TOOL_R (mm, largest tool
   radius the grid will judge) and MARGIN (default 5.0). When STOCK_BOX is given, the grid covers the union of the part
   bbox and the stock box expanded by TOOL_R + MARGIN on every side (cell-aligned, outer cells are part-free = zmin
   floor as today's PAD cells). PAD keeps working for old callers. Sidecar records "stock_box", "tool_r", "margin" and
   the resulting "pad_mm" per side, plus the grid bounds.
2. connector/runner.py and engine/cli.py prepare: replace the hand-computed PAD values with STOCK_BOX (the run's stock)
   + TOOL_R = max tool radius used in that run (rough and finish) + default MARGIN. Where prepare builds its heightfield
   before the stock is known, compute the stock box first (it is bbox +- stock_xy) and pass it.
3. Tests: builder geometry tested in verify/test_zmap.py via a fake rasteriser or by unit-testing the extent function
   (no FreeCAD needed): grid bounds == stock +- (TOOL_R + MARGIN) when that exceeds the part; sidecar fields present.
   Connector tests still pass. Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q.
Short outputs. The supervisor rebuilds the real heightfields and re-judges.
