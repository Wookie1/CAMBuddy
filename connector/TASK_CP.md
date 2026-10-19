# Task CP: check_program connector action - judge a STEVE-posted program with our independent zmap. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT
change any existing gate, threshold or zmap default behaviour (everything new is opt-in); verify/ must NOT import engine/.
Nothing is ever sent to the machine; confirm stays false.
1. verify/zmap.py --strict (new, opt-in; check_program always passes it). zmap already parses G2/G3 in G17/G18/G19 and
   G41/G42 (via --comp-radius); default behaviour stays exactly as is. Under --strict:
   - allowed: G0/G1/G2/G3 in G17 (I/J centre AND R forms; add R-form parsing if missing, incl. negative R = >180 deg),
     G17, G20/G21, G90, G94, G40, G49, G80 (cancel only), G43 H, G53 (machine-coordinate retract lines: judged as
     "leaves the work area upward" only if Z only; anything else unsupported), G54-G59, G28 G91 X0 Y0 home line at the
     end, F, S, T/M06, M03/M04/M05/M08/M09/M30, comments, N numbers, O, %, G04.
   - anything else (G18, G19, G41, G42, G81-G89 canned cycles, G91 outside the G28 home line, G68, G51, M98/M99, #
     variables, unknown words) -> exit non-zero with "unsupported: <code> at line N" (first offender; report all in
     check json "unsupported": [...]). Never skip a line silently.
   - Test: an R-form and an I/J-form G17 arc each give the same gouges/rapid-collision/leftover results as the same arc
     finely linearized as G1 (<= 0.01 mm chord) on a synthetic part; every rejected code above has a test.
2. connector: new catalog action check_program. Inputs: program {"x-steve":"program"}, model {"x-steve":"file",
   "format":"step"}, stock box (same fields as adaptive_rough: orientation, stock_xy, stock_top, stock_bottom),
   optional tool_number override. The tool comes from the program's T word looked up in tools/x7_tools.json (type,
   diameter, corner, flute, shank, holder, stick-out); unknown tool or holder -> run fails (same as today). One program
   = one tool; a program with more than one T -> fail "multi-tool programs not supported yet". Prepare the part, build
   the judge heightfield with the shared builder (STOCK_BOX + TOOL_R), run zmap --strict with the same gates as
   adaptive_rough (gouges, rapid collisions, over-flute/shank, holder, outside grid) plus the engagement report
   (1.2x optimal load if given, else report-only with no threshold), and return check.json + preview.png. No .nc
   upload of anything new; confirm false.
3. connector/README.md + panel: one plain paragraph: what check_program checks (the gates above against your part and
   stock, using your tool table) and what it does not (fixtures/vise, machine travel limits, multi-tool programs,
   cutter comp, canned cycles, other planes, feeds/speeds suitability; still needs the dry run on the X7).
Tests: connector e2e with a small posted program (testdata) passing and one with G81 failing "unsupported";
unit tests for the tool lookup. Run /opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q in the
FOREGROUND until green. Short outputs.
