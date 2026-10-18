# Task H post report — `engine/post_lnc.py` (SyilCNC LNCv2 post)

Posted program: **`out/core_front_rough_X7.nc`** (G20 inch, CRLF), generated from the
round-7 neutral roughing `out/core_front_roughG.ngc`:

```
python -m engine.cli post --in out/core_front_roughG.ngc \
        --out out/core_front_rough_X7.nc --program 1001 --op-name "OVERALL ROUGHING"
```

`rough` also takes `--post lnc [--metric] --program N --op-name "..." --tool-number n`.

**Tool number (Task I).** With no `--tool-number`, the post resolves T/H through the
X7 tool table **`tools/x7_tools.json`** (match on type + diameter + corner radius
within 0.001 mm; seeded from `reference/1001.nc`: bull Ø12.7 CR0.127 → **T3 / H03 /
D03**). An explicit `--tool-number` overrides the table; a spec that is not listed
with no number given is **refused** (no silent T1). The re-posted program therefore
reads `T3 M06` / `G43 Z.. H03`.

## (a) Structural diff vs `reference/1001.nc` (non-motion lines)

Every NON-motion control line is classified and value-masked (tool number, rpm,
dwell, tool-length `Z/H`, program number → placeholders), then compared in order.

```
ours control tokens: 18    ref (excluding G17 plane restores): 18
matching control lines: 18 / 18        # % O<n> modal-header units G53-home
                                       # T·M06 S·M03 G04 Gxx M08 G43  ...  M09
                                       # G53-home G49 G28·G91 G90 M30 %
```

Header tool comment — only the allowed fields differ:

```
ours = (T3 D=0.5 CR=0.005 - ZMIN=0.9823 - BULLNOSE END MILL)
ref  = (T3 D=0.5 CR=0.005 - ZMIN=0.9824 - BULLNOSE END MILL)
       -> T, D, CR and tool type identical; ZMIN differs (allowed)
```

Comment lines: ours = 4, ref = 4 (tool comment, op name, tool description, plus
our cutter-comp note vs the reference's second-op name).

**Result: PASS.** Only tool number, op name, rpm and ZMIN-type values differ. The
single structural delta is the reference's three standalone `G17` lines (see below).

## (b) zmap equivalence — posted inch vs neutral metric run

Same grid/tool as round 7 (`out/core_front_setup_hf.npy`, cell 0.5,
stock `[-128.651, 128.651, -82.55, 82.55, 0, 60.96]`, bull Ø12.7 CR0.127, flute 25.4):

| metric | neutral (mm) | posted inch | diff |
|---|---|---|---|
| gouges | 0 | 0 | equal |
| rapid collisions | 0 | 0 | equal |
| over-flute moves | 0 | 0 | equal |
| leftover mean (mm) | 1.5271 | 1.5273 | 2.5e-4 |
| leftover p95 (mm) | 6.9850 | 6.9850 | 0 |
| leftover max (mm) | 36.4357 | 36.4357 | 0 |
| cutting length (mm) | 58036.9 | 58039.3 | 4.1e-5 rel |

**Result: PASS.** Gouges/collisions identical; leftover within 1e-3 mm; cutting
length within 1e-3 relative. Residual drift is exactly the G20 output resolution
(1 LSB = 0.0001 in = 0.00254 mm); p95/max land on identical cells so they match to
0.

## (c) Number formatting — confirmed against 1001.nc

* Coordinates: max fraction digits, trailing zeros trimmed, decimal point forced
  (inch 4 dp, mm 3 dp): `3.`, `2.6`, `-5.1141`.
* Feeds: inch up to 1 dp, mm integer, forced decimal — `F50.`, `F135.` (inch),
  `F1270.`, `F3429.` (mm). Our 1270/3429 mm/min convert to **50 / 135 ipm**, the
  same roughing feeds the reference uses.
* Leading zeros kept (`0.3167`), `-0.0` and values rounding to zero collapse to `0.`;
  `0.00005` rounds up to `0.0001`.
* Modal suppression as the reference does it: motion word (`G00`/`G01`) only on mode
  change, axis word only when that axis changes at output precision, `F` only on feed
  change; no-op moves dropped.

## LNC-format notes — what could not be matched, and why

1. **Trailing `G17` plane restore.** 1001.nc ends its last op with `G00 Z3.` then a
   standalone `G17` because that op (`INSERT CONTOUR`) arcs in the **G18** plane. Our
   roughing is line-only and never leaves G17, so the restore is unnecessary and is
   omitted — this is the only non-motion delta in (a).
2. **Second op / cutter compensation.** The reference's `INSERT CONTOUR` op uses
   `G41/G40`, helical/arc entries (`G02/G03`), and `G18` I/K arcs. This task posts a
   single tool-centre roughing op and forbids `G41/G42`, so none of those appear. Arc
   output (`G02/G03` with I/J in G17) is implemented but stays silent because the
   engine path contains no arcs. A header comment states comp is off (paths are tool
   centre).
3. **No `M05`.** 1001.nc never emits `M05`; it relies on `M30` to stop the spindle.
   The footer reproduces this exactly (`M09 / G53 G00 Z0. / G49 / G28 G91 X0. Y0. /
   G90 / M30 / %`).
4. **First-move Z default (fixed in Task I).** The op header positions XY with
   `G00 X.. Y..` (no Z) before `G43 Z<clear> H<n>` — verbatim the vendor structure.
   `verify/zmap.py` now treats a leading Z-less rapid as **Z unknown, above stock**:
   `resolve_moves` defaults it to the first explicit Z of the program (else the stock
   top), and `simulate_parallel` passes that explicitly, so chunked (`--jobs>1`) sims
   of any such program — `reference/1001.nc` included — no longer register the
   phantom dive. The first-Z normalisation workaround was removed from
   `engine/test_post.py`; `engine/probe_i_jobs_agree.py` confirms `--jobs 1` and
   `--jobs 4` agree exactly (identical stock arrays, 0 gouges / 0 rapid collisions /
   0 over-flute) on the `1001.nc` rough section and on our X7 file.
5. **Clearance / retract heights.** The reference uses round stock-relative heights
   (`Z3.`, `Z2.6`); the engine bakes its own retract/approach into the moves, so ours
   posts the path's max Z (`62.96 mm → Z2.4787`) as the `G43`/retract height. These
   are coordinates and are allowed to differ.
6. **ZMIN.** Ours `0.9823` vs ref `0.9824`: our final tip depth is 24.95 mm
   (`--final-zmin`) vs the reference's ≈24.953 mm — an allowed ZMIN-type difference.

## Test suites run

* `/opt/homebrew/bin/python3 -m pytest verify -q` → **16 passed** (incl. the new
  leading-XY-rapid first-Z regression)
* `/opt/homebrew/bin/python3 -m pytest engine/test_post.py -q` → **7 passed** (incl.
  tool-table lookup / override / refusal and the T3 check on the posted X7 file)
* `/Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_post.py` → **0 failures**
* `/Applications/VibeCAD.app/Contents/Resources/bin/python engine/test_engine.py` → **0 failures**
* `/opt/homebrew/bin/python3 engine/probe_i_jobs_agree.py` → **AGREE** (`--jobs 1` vs
  `--jobs 4` on the `1001.nc` rough section and `out/core_front_rough_X7.nc`)
