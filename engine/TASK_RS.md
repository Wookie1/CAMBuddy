# Task RS: roughing must clip its cutting region to the stock box, whatever the --hf grid extent. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do not edit
verify/. Supervisor finding: when prepare's part_hf.npy (the --hf clip grid) was built padded past the stock (stock +
tool radius + 5 mm), the adaptive roughing cut over the whole grid: 3,479 moves with tool footprints beyond stock +
R + 5 mm (connector e2e test, zmap outside_grid). The cutting region must come from the --stock box (minus nothing,
plus at most the tool radius for edge clean-up), never from the heightfield bounds.
1. Find where engine/rough.py derives the level regions/outer boundary from the hf grid and clip it to the stock box.
2. Test (engine/test_engine.py, VibeCAD python): rough the test block with its normal --hf and with a copy of that hf
   padded by 20 mm of empty floor on every side: both outputs keep every tool-centre XY within stock +- tool radius
   (+0.01), and the cut length differs by < 1 %.
Run /Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_engine.py and
/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q in the FOREGROUND (don't end your turn with
background jobs). Short outputs.
