# Task Z2: zmap shank/over-flute check (verify/ only; numpy only, no ocl/engine imports). Do not commit.
Today --flute only compares the stock under the tool CENTRE at a move's endpoints with the tip. That misses a ball
riding beside a deep wall: the shank above the flute rubs the wall. New check, enabled by --flute F
[--shank-dia S (default = tool dia)]:
for every cutting sample (same sampling as the cut), the shank occupies z > tip + F within radius S/2 of the
centre; it is a HIT if the max of (current stock, part) over cells within S/2 exceeds tip + F + 0.01 mm. Report
over_flute: {count (cutting moves with a hit), max_depth (max excess mm), worst_xy, first_line} and keep the old
counter as "plunge_over_flute". Tests (synthetic, 0.1 mm cells): ball D=6 F=15 next to a 22 mm wall at exactly r ->
hit with excess ~7 mm; same wall 10 mm high -> no hit; far from walls -> no hit; S < D (necked) reduces hits.
Run /opt/homebrew/bin/python3 -m pytest verify -q.
