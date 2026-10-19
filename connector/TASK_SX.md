# Task SX: per-axis stock margins (stock_x, stock_y). Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; NO gate or
threshold change; verify/ must NOT import engine/.
Today the stock box = part bbox +- stock_xy in X and Y (+ stock_top / stock_bottom in Z): engine/cli.py prepare
(--stock-xy) computes it; connector/runner.py passes values["stock_xy"] in adaptive_rough, slope_split_finish and
check_program. James's real Core Front blank is 2.286 mm per side in X but 12.7 mm in Y.
1. engine/cli.py prepare: optional --stock-x / --stock-y (mm per side), each defaulting to --stock-xy. Negative values
   -> SystemExit with a clear message. Put the box arithmetic in one small pure function (stock_box(bbox, sx, sy, top,
   bottom)) so it is unit-testable without FreeCAD.
2. connector/catalog.py: optional "stock_x" and "stock_y" (number, minimum 0) on adaptive_rough, slope_split_finish
   and check_program, description in plain words: "Extra stock on each side in X (defaults to the XY value)" / same
   for Y. connector/runner.py: pass --stock-x/--stock-y to prepare only when given; every judge heightfield
   (STOCK_BOX + TOOL_R + 5 mm) is computed from the resulting per-axis box, as today.
3. README + panel: one plain sentence each.
4. Tests (no FreeCAD): stock_box with Core Front's bbox [-126.365, 126.365, -69.85, 69.85, 0.0, 47.06239] and
   sx 2.286, sy 12.7, top 13.89761, bottom 0 == [-128.651, 128.651, -82.55, 82.55, 0.0, 60.96] (to 1e-6);
   stock_x/stock_y absent -> exactly the same box as stock_xy-only (identical floats); negative -> error; catalog
   accepts/rejects as above; runner passes --stock-x/--stock-y only when given (fake _spawn, existing pattern), and the
   judge heightfield STOCK_BOX env equals the per-axis box.
Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q in the FOREGROUND until green. Short outputs.
