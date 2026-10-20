# RP0 Results — Core Front T13 fragmentation diagnosis (RT_RP run)

Source: `out/rp0_cf.json` only. 21 levels, 213 regions, 2,342 clip breaks — matches RT2 baseline.
Break categories: **LS** = "link split (tool up, no clip)" (no geometry removed); **ISO** = island/part-offset;
**ISO+TU** = island/part-offset + tool up; **TAIL** = island/part-offset tail dropped (not a break, path remainder discarded);
**ALW** = allowance margin (<0.01). "clip mm" = Adaptive2d cutting length removed by clipping at that level.

| z | regions | breaks | LS | ISO | ISO+TU | TAIL | ALW | clip mm | safe mm² | input mm² | over mm² | under mm² |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 42.354 | 10 | 550 | 550 | 0 | 0 | 0 | 0 | 0.0 | 33062.2 | 37146.5 | 9689.8 | 5605.5 |
| 42.926 | 8 | 8 | 8 | 0 | 0 | 0 | 0 | 0.0 | 4923.2 | 2907.2 | 1020.5 | 3036.5 |
| 47.224 | 5 | 20 | 6 | 13 | 1 | 3 | 0 | 96.2 | 11992.2 | 6500.0 | 0.0 | 5500.5 |
| 47.625 | 5 | 404 | 404 | 0 | 0 | 0 | 0 | 0.0 | 11168.5 | 5505.5 | 0.0 | 5663.0 |
| 35.306 | 5 | 565 | 565 | 0 | 0 | 0 | 0 | 0.0 | 30684.8 | 31588.2 | 6509.0 | 5605.5 |
| 36.449 | 16 | 24 | 9 | 3 | 4 | 173 | 8 | 36.7 | 115.2 | 950.2 | 950.2 | 115.2 |
| 37.082 | 13 | 1 | 1 | 0 | 0 | 72 | 0 | 0.0 | 3.5 | 715.2 | 715.2 | 3.5 |
| 39.605 | 19 | 37 | 5 | 17 | 15 | 499 | 0 | 466.2 | 1239.0 | 3834.8 | 2690.2 | 94.5 |
| 40.289 | 16 | 62 | 54 | 4 | 4 | 296 | 0 | 47.3 | 1594.0 | 5175.8 | 3676.0 | 94.2 |
| 41.91 | 22 | 27 | 6 | 10 | 10 | 93 | 1 | 414.5 | 242.2 | 1188.2 | 1188.2 | 242.2 |
| 43.815 | 11 | 6 | 0 | 2 | 4 | 58 | 0 | 102.5 | 2841.2 | 1499.0 | 645.5 | 1996.0 |
| 45.72 | 9 | 134 | 112 | 11 | 11 | 109 | 0 | 27.9 | 2739.8 | 1038.8 | 413.5 | 2114.5 |
| 25.146 | 4 | 488 | 488 | 0 | 0 | 0 | 0 | 0.0 | 29908.8 | 29883.8 | 5580.5 | 5605.5 |
| 27.051 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 2.0 | 443.0 | 443.0 | 2.0 |
| 28.956 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 2.0 | 444.5 | 444.5 | 2.0 |
| 30.861 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 2.0 | 445.0 | 445.0 | 2.0 |
| 32.766 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 2.0 | 446.0 | 446.0 | 2.0 |
| 34.671 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 2.0 | 446.0 | 446.0 | 2.0 |
| 36.576 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 3.5 | 563.8 | 563.8 | 3.5 |
| 38.481 | 10 | 1 | 1 | 0 | 0 | 75 | 0 | 0.0 | 12.8 | 805.2 | 805.2 | 12.8 |
| 40.386 | 13 | 15 | 4 | 1 | 10 | 44 | 0 | 45.8 | 13.5 | 757.2 | 757.2 | 13.5 |

## Totals (from the file)

- Breaks by cause: LS 2,213 (94.5%); ISO 61; ISO+TU 59; ALW 8 + 1(TU). Clip-caused breaks = **129 (5.5%)**.
- TAIL drops: 1,422 (island/part-offset). Bridged slivers: 15 (island/part-offset), replacing 10.2 mm.
- Length removed by clipping: ISO 633.6 mm + ISO+TU 603.5 mm + ALW 0.0 mm = **1,237.1 mm** of
  **94,186.4 mm** Adaptive2d cutting length = **1.3%**. LS removes 0.0 mm.

## Input boundary vs safe region

**0 of 21 levels have input boundary == safe region.** Every level shows both over (input area outside safe)
and under (safe area not covered by input): e.g. z 42.354 over 9,689.8 / under 5,605.5 mm²; z 36.449 input
950.2 mm² vs safe 115.2 mm² (8.2× larger); perimeters differ too (z 42.354: safe 1,953.5 vs input 1,512.0 mm).
So clipping is indeed a post-pass against a boundary Adaptive2d never saw — that part of the hypothesis holds.

## Verdict on the hypothesis: NO (refuted as the fragmentation mechanism)

- Confirmed premise: clipping runs after Adaptive2d, against a boundary equal to the safe region at 0/21 levels.
- Refuted consequence: the post-pass clip is *not* what fragments the paths. It produces only 129 of 2,342 breaks
  (5.5%) and removes 1.3% of cut length. The other 2,213 breaks are Adaptive2d's own tool-up link splits
  (0 mm clipped), and it already emits 3,218 links internally (e.g. n_links_in 628 at z 42.354, 650 at z 35.306)
  — the fragmentation is in Adaptive2d's link/contour structure, upstream of any clip.
- Expected effect of feeding the safe region as Adaptive2d's boundary: removes all 129 clip breaks, all 1,422 tail
  drops, the 15 bridges (10.2 mm) and the 1,237.1 mm clip loss (clip demoted to assertion), and would let links
  route within safe ground instead of over islands (576 not-clear links, 277 lifts recorded). But it would NOT by
  itself restore round-G's 14 regions: levels with zero clip removal still show the worst splits (z 35.306: 565 LS,
  clip 0.0 mm; z 42.354: 550 LS, clip 0.0 mm), so the dominant lever is Adaptive2d's tool-up linking strategy,
  not the clip post-pass.

STOP.
