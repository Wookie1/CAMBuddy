# RP2 step 1 — side entries for OPEN roughing regions

All numbers below were produced this session from files in this repo
(`out/rp2_1_*`); judge = `verify/zmap.py` exit code + JSON, both runs of each
pair on the identical command from the task. Nothing committed.

## Change (engine/rough.py only; +184/−98 raw, +121/−35 ignoring whitespace —
the remainder is dedenting the RP2_0 `rp2_open` classifier)

1. The RP2_0 per-region OPEN/CLOSED classification is now always-on and DRIVES
   entry selection. For an OPEN region `enter_at` first asks `find_shift`
   (new `flank=True`) for a verified descent column beside the region: lift at
   the current point, traverse directly to the column (no detour over the entry
   point), ramp-feed down it, then feed in sideways at Z (flank only). CLOSED
   regions and failed side entries take today's 2-deg helix unchanged.
2. `find_shift flank=True` keeps every existing check — judge-disk-clear column
   (stock ≤ Z+0.04 within R+~1.5 cells), island legality of the whole feed-in
   path at 0.03, stock-box footprint — and replaces the live-stock FLOOR test
   (which can never pass when feeding into the region's own standing slab) with
   the part heightfield backstop (`hf_gouge_violation` on the feed path) plus a
   part-pad-clear descent-column test (`max(stock,part)` within tool_r + rapid
   margin ≤ Z+0.05). Axial removal stays impossible: descent is in a
   judge-disk-clear column, feed-in is horizontal.
3. `offset_down` (shared with the old wide_fail/long-stretch path) now descends
   the verified column by RAMP FEED instead of G0. This fixed a real bug the
   first side-entry run exposed in zmap (1 axial plunge, 1.665 mm): a G0
   descent at the column could be R5-bumped back to traverse height by pad
   material and silently dropped, stranding the diagonal feed-in at ~53 deg.
4. Mid-region re-entries (clip-break `enter_at`) and lift landings reuse the
   same verified side path when their region is OPEN.
5. Entry/re-entry descent feed measured always-on (count + mm at ramp feed
   1270 mm/min); baseline counts came from an instrumented HEAD copy whose NGC
   is byte-identical to the uninstrumented baseline (`NGC_IDENTICAL`).

## Core Front T13 (out/rp2_1_base_cf*.json vs out/rp2_1_new_cf*.json)

| metric | before | after |
|---|---:|---:|
| region-entry feed (213 regions) | 53,446 mm = 42.1 min (201 descents) | 29,404 mm = **23.2 min** (208) |
| mid-region re-entries / lift descents | 29,911 mm = 23.5 min (160) | 15,410 mm = **12.1 min** (159) |
| total descending feed | 83,362 mm = 65.6 min | 44,819 mm = **35.3 min** (−30.3 min) |
| total cycle (zmap) | 104.1 min | **73.9 min** |
| rapids (zmap) | 24.52 m | **23.95 m** (≤ 24.4 ✓) |
| gouges / rapid collisions / axial / outside-grid | 0 / 0 / 0 / 0 | **0 / 0 / 0 / 0** |

Regions unchanged: 213 executed = 205 OPEN + 8 CLOSED (same classification as
RP2_0). Side entries used: **187/213**; helix fallback: 26 OPEN + 8 CLOSED.
Engagement (report, not a gate here): spikes >2.438 mm 14,874 → 12,181;
descending-entry moves 10,478 → 6,750; horizontal p95 2.415 → 2.416, p99
12.686 both (pre-existing loop-crossing steps, unchanged class).

## Test block (TASK_R6 command; out/rp2_1_base_tb* vs out/rp2_1_new_tb*)

| metric | before | after |
|---|---:|---:|
| region-entry feed (11 regions) | 2,277 mm = 107.6 s (8) | 970 mm = **45.8 s** (10) |
| re-entries / lift descents | 1,749 mm = 82.6 s (14) | 1,327 mm = **62.7 s** (14) |
| total descending feed | 4,026 mm = 190.1 s | 2,297 mm = **108.5 s** |
| total cycle (zmap) | 6.4 min | **5.0 min** |
| rapids | 1.07 m | 1.04 m |
| gouges / rapid collisions / axial / outside-grid | 0 / 0 / 0 / 0 | **0 / 0 / 0 / 0** |

## Tests

`scripts/check_fixtures.py`: 10 ok, 0 bad. `engine/test_engine.py`: 0 failures.
`engine/test_finish.py`: ALL PASSED. `pytest verify engine/test_post.py`:
109 passed. (Task's "connector engine/test_post.py" — no test_post.py exists
under connector/; ran the engine one.)

## Notes

- Programmed engagement 2.032 and default ramp angle 2 deg untouched; no
  bypass flags; verify/ untouched; no post-pass — entries are generated inline,
  nothing is edited or replayed after Adaptive2d.
- Baseline rapids measured 24.52 m this session (task quoted 24.4); the final
  path is below both.
- Not committed.
