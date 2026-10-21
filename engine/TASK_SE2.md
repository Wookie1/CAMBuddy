# Task SE2: side entries only through already-cleared material. Do not commit. Budget ~80 changed lines + tests;
STOP the round if it overruns.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/; programmed engagement 2.032, ramp angle default 2 deg; no post-pass; NO new constants (reuse AXIAL_FLOOR from
verify's definition as an engine constant value 0.2 only if the engine has none - name it the same). Report ONLY numbers
you produced this session from files under /Users/James/ai-sandbox. Long runs: nohup + short polling, never end your
turn while one runs. One heavy job at a time. BEFORE any Core Front engine run, wait until the M4's model is idle:
  while pgrep -f 'title task FE4' >/dev/null || pgrep -f 'title task ZE' >/dev/null; do sleep 120; done
WHY: RP2 step 1's side entries (find_shift flank=True) feed sideways from a cleared column into the region start through
whatever standing material is between - a full-width slot of the 12.686 mm flat at up to full stepdown at cut feed. That
is the overload James's 2.032 mm load prevents; it is not allowed.
1. A side entry is used ONLY if the whole sideways feed-in (column -> region start, swept by tool_r) runs through
   material already cleared at that level: max standing stock above the level Z along the swept feed-in <= AXIAL_FLOOR
   (0.2 mm), from the engine's own live stock record (stock model) at that moment. If the engine cannot tell (no stock
   data / outside the record), treat it as NOT clear (fail closed).
2. Otherwise the region uses the existing helix entry at ramp_angle_deg, unchanged. No reduced-feed variant.
3. The column descent stays inside cleared area (keep the existing judge-disk-clear check).
4. Unit tests (engine/test_engine.py): a region whose only side approach crosses a standing wall must helix; a region with
   a cleared approach must side-enter.
5. Report (engine/SE2_RESULTS.md) on Core Front T13 and the test block: side vs helix counts, region-entry feed, mid-region
   re-entry feed, total descending feed, cycle (zmap), rapids, all zmap gates (0). Judge = verify/zmap.py exit + JSON:
     /opt/homebrew/bin/python3 verify/zmap.py <rough.ngc> --part out/cf_hf01_z5b.npy --tool flat --dia 12.686
       --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438 --jobs 6 --out-json <json>
   Rough command: engine.cli rough --step samples/core_front_setup.step --stock -128.651 128.651 -82.55 82.55 0.0 60.96
   --tool flat:12.686:0.0 --floor 24.765 --leave 0.381 --stepdown 19.05 --optimal-load-mm 2.032 --stepup 1.905
   --hf out/core_front_setup_hf.npy --min-rest 0.5 ; test block: the TASK_R6 command.
Engine suites + pytest verify connector engine/test_post.py green (scripts/check_fixtures.py first).

ADDENDUM (supervisor, report only - no new engine scope): in engine/SE2_RESULTS.md list EVERY region that falls back to
a helix with: level Z, helix depth and length, the reason (closed region / feed-in through standing stock / no cleared
column), and whether its boundary touches the blank's outer edge at that level (stock box X +-128.651, Y +-82.55).
