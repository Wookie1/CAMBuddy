# LNC 5800 (SYIL X7) post spec

This is the output format for `engine/post_lnc.py`. Every rule below is sourced from controller documentation or
from published Fanuc-style ISO conventions. Nothing here is taken from CAM-vendor post processors or their
output. Rules marked **VERIFY** depend on a machine parameter or setting that James must confirm on the X7.
Before anything new runs on the machine, he does a graphics check or a dry run above the part.

## Sources
- **[LNC]** LNC Technology, *LNC Milling Series Software Manual*, 2020/07 V01.00 (parameters, alarms):
  https://abmarketotomasyon.com/wp-content/uploads/2025/08/LNC-Milling-Series_Software_Application_Manual_V01.004408210139_ENG.pdf
- **[LNC-OP]** Advantech-LNC M5800 Series Operation Manual (ManualsLib):
  https://www.manualslib.com/manual/1958254/Advantech-Lnc-M5800-Series.html
- **[LCNC-G]** LinuxCNC G-code reference (open documentation of RS-274/Fanuc-style semantics):
  https://linuxcnc.org/docs/html/gcode/g-code.html
- **[LCNC-M]** LinuxCNC M-code reference: https://linuxcnc.org/docs/html/gcode/m-code.html
- **[LCNC-O]** LinuxCNC G-code overview (comments, `%`, words): https://linuxcnc.org/docs/html/gcode/overview.html
- **[DPI]** Fanuc decimal-point input (parameter 3401 bit 0):
  https://www.mmsonline.com/columns/parameters-can-make-things-interesting and
  https://www.mfgrobots.com/Article/equipment/cnc/46531.html

## Program structure
| # | Rule | Source |
|---|------|--------|
| P1 | The file starts and ends with a `%` line (tape start and end). | [LCNC-O] (`%` demarcation) |
| P2 | The second line is `O<n>` with an integer program number and no decimal point. | [LNC] INT 3010 (no decimal point on integer addresses); Fanuc O-number convention |
| P3 | Comments are `( … )`, in upper case, with no nested parentheses. **VERIFY: LNC parameter 42 (COMMENT TYPE) must be 1.** With the default 0, comments are `/*…*/` and `(…)` is a *functional* format. | [LNC] p.147 (param 42), p.59 (param list) |
| P4 | Safety line: `G90 G94 G17 G40 G49 G80` sets absolute mode, feed per minute, the XY plane, comp off, length comp off and canned cycles off. | [LCNC-G] G90/G94/G17/G40/G49/G80; [LNC] p.156 (G94 = mm/min or in/min) |
| P5 | Units: `G21` (mm) or `G20` (inch) as its own line before any motion. | [LNC] p.151 (power-on unit; G20/G21 switch) |
| P6 | `G53 G00 Z0.` retracts in machine coordinates to Z home before a tool change and at the end. G53 is non-modal. | [LCNC-G] G53; [LNC] param list (G53 motion) |
| P7 | Tool change: `T<n> M06`, with n from 0 to 99 and no decimal point. | [LNC] INT 3135 (T range 0~99); [LCNC-M] M6 |
| P8 | Spindle: `S<rpm> M03` (integer S), then a warm-up dwell `G04`. **VERIFY the dwell unit: Fanuc-style `P` is ms with no decimal point, `X` is seconds.** We emit `G04 X<s>.` unless James confirms `P` ms on the X7. | [LCNC-G] G4; [LNC] p.206-210 (`G04 P_` in the rigid-tap example, unit not stated) |
| P9 | Work offset: `G54` (or G55…G59, or G54 P1…P100) on its own line. | [LNC-OP] (6 + 100 extended work coordinate systems) |
| P10 | Coolant: `M08` on before cutting, `M09` off at the end. | [LCNC-M] M7/M8/M9 |
| P11 | Tool length offset: `G43 Z<clear> H<n>`, with H from 0 to 99 and H = T by default. It is applied on the first Z move at clearance height, after an XY rapid at the current Z. | [LCNC-G] G43; [LNC] INT 3136 (H/D range 0~99) |
| P12 | Cutter radius comp is **off**: engine paths are tool-centre. If comp is ever used, the LNC comp address is D (parameter default 1 = `G41 D1`). A header comment states that comp is off. | [LNC] p.153 (H vs D comp code) |
| P13 | End: `M09`, `M05` (spindle stop, explicit), `G53 G00 Z0.`, `G49`, `G28 G91 X0. Y0.` (home XY through the current point), `G90`, `M30`, `%`. | [LCNC-M] M5/M30; [LCNC-G] G28/G91; [LNC] p.29 (M02/M30 end the program) |

## Words and numbers
| # | Rule | Source |
|---|------|--------|
| N1 | Every axis, arc-centre and feed value carries a decimal point (`X3.`, `F1270.`). Without one, a Fanuc-style control in standard mode reads the value in least input increments (`X10` = 0.010 mm). | [DPI] |
| N2 | Integer-only addresses (O, N, T, H, D, M, S, G) never carry a decimal point; the control alarms otherwise. | [LNC] p.179 INT 3010 "NOT ALLOWABLE DECIMAL POINT" |
| N3 | Coordinates: mm to 3 decimals (0.001 mm) and inch to 4 decimals (0.0001 in), the Fanuc least input increments. Trailing zeros are trimmed but the point is kept (`3.`, `2.6`, `-5.1141`). `-0.` is written `0.`. | [DPI] (least input increment 0.001 mm / 0.0001 in) |
| N4 | Feed: mm/min as an integer with a point (`F1270.`); in/min to 1 decimal (`F50.`, `F135.5`). Below 0.1 in/min is irrelevant for milling. | [LNC] p.156 (G94 units); N1 |
| N5 | Arc centre I/J/K (incremental from the start point) with a point, same precision as coordinates. Arcs only in G17 for now; there are no arcs yet (paths are lines). | [LCNC-G] G2/G3 centre format |
| N6 | Modal: a motion G word is written only when the mode changes, an axis word only when its value changes at output precision, and F only when the feed changes. G00/G01/G02/G03, F and the axis positions are modal. | [LCNC-G] modal groups; [LNC-OP] (G00 stays in effect until G01 is commanded) |
| N7 | Line endings: CRLF (accepted by DOS-based LNC controls over disk/RS232). | [LNC] p.1-2 (DOS update page, disk/RS232 transfer) |

## Open points for James (VERIFY)
1. LNC parameter 42 is 1, so `( )` comments are comments (P3).
2. The `G04` dwell unit: whether he wants `X<s>.` or `P<ms>` (P8).
3. That `M05` before `M30` is wanted. It's harmless, since M30 also stops the spindle (P13).
4. The tool and H/D numbers come from tools/x7_tools.json, his own tool table.
