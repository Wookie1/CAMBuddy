# Task CPc: check_program judges up to three programs in sequence, carrying the stock. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT change
any gate, threshold or zmap behaviour; verify/ must NOT import engine/. Nothing goes to the machine; confirm false.
1. catalog.py check_program: keep "program" (required, judged first) and add optional "program_2" and "program_3"
   ({"x-steve":"program"}), judged in that order. (Plain fields, not an array: the input-download loop handles fields.)
   connector.py download loop: each program field saved to its own file (program.nc, program_2.nc, program_3.nc) -
   never overwriting another input; add a test for that.
2. runner.run_check_program: for each program in order: its own tool from its own T word (one T per program; the
   existing tool_number override applies to "program" only, and must still match its T), its own holder; zmap --strict
   with --stock-in = the previous program's --stock-out (first program: full stock box), and --stock-out for the next.
   _check_zmap_gates on EVERY program; the first failing program fails the run and is named in the error.
   check.json: {"programs": [{"name": "program", "tool": {...}, "check": <zmap report>}, ...]} plus the existing
   top-level keys for the first program kept as they are (so single-program callers see no change).
   preview.png = leftover after the LAST program.
3. README + panel paragraph: one sentence that up to three programs can be checked in order (e.g. rough, finish, rest).
4. Tests: a two-program e2e (rough-like then a lighter pass) where the second is judged on the first's stock (assert the
   second's check uses stock-in, and that judging it alone from raw stock would differ); a failing second program fails
   the run and names program_2; existing check_program tests unchanged.
Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q in the FOREGROUND until green. Short outputs.
