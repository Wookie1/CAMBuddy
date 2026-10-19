# Task R5 (safety): roughing rapids must clear the live stock. engine/ only. Do not commit.
After R3, the synth_pocket rough (connector/testdata/synth_pocket.step, flat 6, stock -31 31 -31 31 -1 12.4, floor 3,
leave 0.381, stepdown 4, optimal-load 2, stepup 1.905, --hf) has 0 gouges but 6 zmap RAPID COLLISIONS (first at
G-code line 3926). Finishing already verifies rapids against the stock (finish.py link_plan with stock_from, S3b).
Do the same in rough.py: every G0 (and every lift/traverse) is checked against the engine's own LIVE stock model
(StockField as cut so far) and the part: rapid height >= max(stock top, part CL) within the tool radius along the
swept path + margin (default 1.0 mm); otherwise retract to the clearance plane or a verified height. Add a test on
synth_pocket and on a two-level synthetic part asserting no rapid passes through uncut stock (use the engine's own
stock model as the check; do not import verify/zmap.py). Keep rough clcheck, backstop and all engine tests green.
