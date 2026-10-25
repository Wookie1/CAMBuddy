# LNC 5800 (SYIL X7) post spec

This is the output format for `engine/post_lnc.py`. Every rule below is sourced from controller documentation or
from published Fanuc-style ISO conventions. Nothing here is taken from CAM-vendor post processors or their
output. Rules marked **VERIFY** depend on a machine parameter or setting that James must confirm on the X7.
Before anything new runs on the machine, he does a graphics check or a dry run above the part.

## Sources
- **[LNC-PM]** Advantech-LNC, *A-LNC Milling Machine Series Programming Manual*, 2016/05 V01.02.000
  (James's copy, docs/LNC-Programming Manual.pdf, kept out of git).
- **[LNC-OM]** Advantech-LNC, *A-LNC Milling Machine Series Operation Manual*, V01.00.003 (James's copy,
  docs/LNC-Operation Manual.pdf, kept out of git).
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
| P3 | Comments are `( … )`, in upper case, with no nested parentheses. **CONFIRMED on James's X7, 2026-10-18** (`( )` comments run, so parameter 42 = 1). With parameter 42 = 0, comments are `/*…*/` and `(…)` is a *functional* format; `--comment-style slashstar` covers that case. | [LNC] p.147 (param 42), p.59 (param list); [LNC-PM] p.29 (`/* */` comments in examples) |
| P4 | Safety line: `G90 G94 G17 G40 G49 G80` sets absolute mode, feed per minute, the XY plane, comp off, length comp off and canned cycles off. | [LCNC-G] G90/G94/G17/G40/G49/G80; [LNC] p.156 (G94 = mm/min or in/min) |
| P5 | Units: `G21` (mm) or `G20` (inch) as its own line before any motion. | [LNC] p.151 (power-on unit; G20/G21 switch) |
| P6 | `G53 G00 Z0.` retracts in machine coordinates to Z home before a tool change and at the end. G53 is non-modal. | [LCNC-G] G53; [LNC] param list (G53 motion) |
| P7 | Tool change: `T<n> M06`, with n from 0 to 99 and no decimal point. | [LNC] INT 3135 (T range 0~99); [LCNC-M] M6 |
| P8 | Spindle: `S<rpm> M03` (integer S), then a warm-up dwell `G04 P<ms>`: whole milliseconds, no decimal point (default; **CONFIRMED on James's X7, 2026-10-18**). `G04 X<s>.` (seconds, with a point) is the `--dwell-x-s` option. | [LNC-PM] p.13 (G04: `G04 X100.` = 100 s, `G04 P100` = 0.1 s, P in ms without a decimal point) |
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
| N5 | Arc centre I/J (incremental from the start point) with a point, same precision as coordinates. Arcs only in G17, only with the opt-in `--arcs` post option (default off: paths are lines). Rules A1-A8 below. | [LNC-PM] PDF p.11; [LCNC-G] G2/G3 centre format |
| N6 | Modal: a motion G word is written only when the mode changes, an axis word only when its value changes at output precision, and F only when the feed changes. G00/G01/G02/G03, F and the axis positions are modal. | [LCNC-G] modal groups; [LNC-OP] (G00 stays in effect until G01 is commanded) |
| N7 | Line endings: CRLF (accepted by DOS-based LNC controls over disk/RS232). | [LNC] p.1-2 (DOS update page, disk/RS232 transfer) |

## Arcs: G02/G03 (`--arcs`, default off)
Page refs are PDF pages of [LNC-PM] (printed page in brackets). Facts are paraphrased, not quoted.
| # | Fact / rule | Source |
|---|-------------|--------|
| A1 | G02 is clockwise and G03 counter-clockwise, viewed in the active plane. The plane is G17 (XY), G18 (ZX) or G19 (YZ) and must be set before an arc; parameter 50042 sets the plane after power-on/RESET. The post emits arcs only in G17, which the P4 safety line already selects. | PDF p.11-12 [7-8]; PDF p.21 [17] |
| A2 | Centre form: I, J, K are the X, Y, Z distances from the arc **start point** to the centre, described only as incremental values from the start (G90/G91 is stated to govern the end point, not I/J/K; the manual gives no absolute-centre mode). In G17 the words are X Y with I J. The post writes both I and J on every arc line (they are per-block, not modal) with the coordinate precision and a forced point (N1/N3). | PDF p.11 [7] |
| A3 | R form: R (arc radius) may replace I/J; when R and I/J are all given, the control uses R. The manual does not say how an arc over 180 deg is selected with R (no negative-R rule). The post therefore never emits R; it always uses I/J. | PDF p.11 [7] |
| A4 | Full circles: the manual is silent (no statement that a zero-length I/J arc is a 360 deg circle). The post never emits a full circle: every fitted sweep is split at 180 deg or less. | PDF p.11-12 [7-8] (silent) |
| A5 | Helical: the manual is silent. The G17 format lists only X, Y and I, J (no Z) and nothing describes a linear third axis along an arc. The post emits **no helical arcs**: arcs are fitted only at constant Z, and a G02/G03 move whose Z differs from the start is refused. | PDF p.11 [7] (silent) |
| A6 | End-point check: the control compares the start-to-centre and end-to-centre distances; if they differ by more than parameter 50048 it raises alarm 510204 (end point not on the arc). The manual does **not** give the default value of 50048. The post uses 0.0005 mm as its limit, checked after rounding the start, end and I/J to the posted precision (a fitted arc that misses it after trying the 3x3 nearest-grid centres is posted as its original lines). **VERIFY**: James can read 50048 on the X7. | PDF p.11 [7] |
| A7 | Fit rules (post option, not a manual fact): only runs of 4 or more consecutive G01 moves at one Z and one feed; every original point and every original chord within ARC_TOL = 0.002 mm of the arc (chord check is the vertex residual plus the chord sagitta, conservative); radius 0.1 to 500 mm, otherwise lines; one direction per arc. | engine/arcfit.py |
| A8 | A G02/G03 move with no centre data is a hard error in the post (previously it would have been written without I/J). | engine/post_lnc.py |

## Cutter radius compensation: G40/G41/G42 (facts only; the post keeps G40)
| # | Fact | Source |
|---|------|--------|
| C1 | G41 offsets to the left, G42 to the right, G40 cancels. The comp number is the **D** address, range 1 to 99; D0 cancels comp. The offset plane comes from G17/G18/G19 (XY uses X/Y moves). | [LNC-PM] PDF p.30-31 [26-27] |
| C2 | Comp start: G41/G42 with 0 < D <= the maximum comp number; the start block must be a straight move (G00 or G01), never G02/G03. Start/cancel approach shape is type A or B by parameter 50060. | [LNC-PM] PDF p.31 [27] |
| C3 | While comp is active, more than 8 consecutive blocks with no motion cause over- or under-cut, and changing the plane raises alarm 510393 and stops motion. | [LNC-PM] PDF p.31 [27] |
| C4 | Comp is cancelled by power-on, G40, D0, M02/M30 and RESET. The cancel block must also be a straight move (G00/G01), not an arc. | [LNC-PM] PDF p.31 [27] |
| C5 | Inside/outside corner definitions (above 180 deg = inner edge, 0 to 180 = outer) are given for the comp path shapes. | [LNC-PM] PDF p.32 [28] |
| C6 | **Post decision:** no G41/G42 code. G40 stays in the P4 header and engine paths stay tool-centre (P12), because the independent judge (verify/zmap) simulates tool-centre paths and cannot check a controller-side comp offset. | - |

## Open points for James (VERIFY)
1. ~~Parameter 42 / `( )` comments (P3)~~: confirmed 2026-10-18.
2. ~~`G04` dwell unit (P8)~~: confirmed `P<ms>` 2026-10-18.
3. That `M05` before `M30` is wanted. It's harmless, since M30 also stops the spindle (P13).
4. The tool and H/D numbers come from tools/x7_tools.json, his own tool table.
5. Parameter 50048 (arc end-point tolerance, A6): the manual gives no default; the post assumes 0.0005 mm.
