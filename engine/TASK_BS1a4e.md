# Task BS1a4e: band._simulate measures at zmap's resolution; the alignment bar as written. Do not commit.
(DRAFT - starts after BS1a4d is reviewed; base = BS1a4d's commit.)
Same LOCKS / TESTS / HARD RULES / FOREGROUND RULE as TASK_BS1a4d.md. BUDGET <= 25 changed non-test lines vs the
BS1a4d commit, STOP at ~40. FRESH session, HARD CAP 2 h.
## Change
(b) band._simulate measures at zmap's resolution: a 0.1 mm grid (or equivalent sub-cell sampling) over each region's
    local bbox, for BAND PLANNING only (the 0.5 mm live stock stays the planning stock). Report band planning time on
    the test block before vs after (the supervisor measures Core Front; flag > 60 s growth there).
## Bars
- The alignment test passes AS WRITTEN: in every window the engine is never more than 0.15 mm below zmap, on the test
  block; over-read reported (max + 5 worst).
- test_bs1a_lshaped_channel passes UNCHANGED. Full engine/test_engine.py green. New assertions fail on e5e783e.
## engine/BS1a4_RESULTS.md - add section (13) BS1a4e. Then stop.
