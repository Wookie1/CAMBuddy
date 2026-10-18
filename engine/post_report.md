# Post report — `engine/post_lnc.py` (spec-based SyilCNC LNCv2 post)

`engine/post_lnc.py` posts the engine's neutral move lists for James's LNC 5800
(Syil X7) following **`docs/lnc5800_post_spec.md`**. Every convention in the
post cites a rule id from that spec (P1..P13 program structure, N1..N7 words and
numbers); the spec itself is sourced from LNC/Advantech controller documentation
and published Fanuc-style ISO conventions.

Generate the X7 program from the neutral roughing:

```
python -m engine.cli post --in out/core_front_roughG.ngc \
        --out out/core_front_rough_X7.nc --program 1001 --op-name "OVERALL ROUGHING"
```

`rough` also takes `--post lnc [--metric] --program N --op-name "..." --tool-number n`.

## Structure (spec rules implemented)

* **P1/P2** `%` tape markers around `O<n>` (integer program number, no point).
* **P3** upper-case flat `( … )` comments (VERIFY: LNC parameter 42 = 1).
* **P4** safety line `G90 G94 G17 G49 G40 G80`; **P5** units (`G20` inch default,
  `G21` with `--metric`) on its own line before any motion; **P6** `G53 G00 Z0.`
  machine-Z home before the tool change and in the footer.
* **P7-P11** per op: `T<n> M06` / tool description / `S<rpm> M03` / warm-up
  dwell / `G54` / `M08` / first XY rapid at the current Z / `G43 Z<clear> H<n>`.
* **P8** dwell default `G04 P<milliseconds>` (confirmed on James's X7 2026-10-18); `--dwell-x-s` emits `G04 X<seconds>.`
  (the P unit is a VERIFY item on the X7).
* **P12** cutter radius comp off — paths are tool centre, stated in a header
  comment; arcs (`G02/G03`, N5) only if the input path contains them.
* **P13** footer: clearance rapid, blank line, `M09 / M05 / G53 G00 Z0. / G49 /
  G28 G91 X0. Y0. / G90 / M30 / %`. `M05` is the explicit spindle stop (new vs
  the earlier post; harmless since `M30` also stops the spindle).
* **N1-N6** number formats: decimal point on every axis/centre/feed value, inch
  coords 4 dp / mm 3 dp with trailing zeros trimmed (`3.`, `2.6`, `-5.1141`),
  feeds inch 1 dp / mm integer (`F50.` / `F1270.`), `-0.` collapses to `0.`;
  integer-only addresses (O/N/T/H/D/M/S/G) never carry a point; modal
  suppression of motion words, unchanged axes and unchanged feeds.
* **N7** CRLF line endings (`--lf` for LF).

## Tool number resolution

With no `--tool-number`, the post resolves T/H through **`tools/x7_tools.json`**
(James's X7 tool table; match on type + diameter + corner radius within
0.001 mm: bull Ø12.7 CR0.127 → **T3 / H03**). An explicit `--tool-number`
overrides the table; a spec that is not listed with no number given is
**refused** (no silent T1). The posted roughing therefore reads `T3 M06` /
`G43 Z.. H03`.

## Verification

* `engine/test_post.py` — spec conformance on a small synthetic program
  (header/footer order incl. M05, comment form, dwell X/P variants, decimals on
  axes/feeds vs integer addresses, modal suppression, CRLF), number-format
  edge cases, and tool-table lookup / override / refusal.
* zmap equivalence — the posted inch program simulates identically to the
  neutral mm run of `out/core_front_roughG.ngc` (same grid/tool/stock:
  gouges / rapid collisions / over-flute equal; leftover stats within 1e-3 mm;
  cutting length within 1e-3 relative). Residual drift is exactly the G20
  output resolution (1 LSB = 0.0001 in = 0.00254 mm).
* `engine/probe_i_jobs_agree.py` — zmap `--jobs 1` vs `--jobs 4` agree exactly
  on the posted X7 file (leading-Z-unknown header shape).

## VERIFY items for James (from the spec)

1. CONFIRMED 2026-10-18 on James's X7: `( )` comments run (LNC parameter 42 = 1) (P3).
2. CONFIRMED 2026-10-18 on James's X7: dwell `G04 P<milliseconds>` (P8); `--dwell-x-s` remains.
3. `M05` before `M30` is emitted per P13 (spindle stop; M30 also stops).
4. Tool/H/D numbers come from `tools/x7_tools.json`, James's own tool table.
