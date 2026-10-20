# Task RP2 step 1: side entries for OPEN roughing regions. Do not commit. Under ~250 lines. No post-pass.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT edit
verify/; programmed engagement 2.032, ramp angle default 2 deg. Report ONLY numbers you produced this session from
files under /Users/James/ai-sandbox. Long runs: nohup + short polling, never end your turn while one runs. One heavy job
at a time.
JUDGE = verify/zmap.py exit code + JSON only:
  /opt/homebrew/bin/python3 verify/zmap.py <rough.ngc> --part out/cf_hf01_z5b.npy --tool flat --dia 12.686
    --stock -128.651 128.651 -82.55 82.55 0 60.96 --engage-max 2.438 --jobs 6 --out-json <json>
Rough command (Core Front T13): engine.cli rough --step samples/core_front_setup.step --stock -128.651 128.651 -82.55
  82.55 0.0 60.96 --tool flat:12.686:0.0 --floor 24.765 --leave 0.381 --stepdown 19.05 --optimal-load-mm 2.032
  --stepup 1.905 --hf out/core_front_setup_hf.npy --min-rest 0.5 ; test block: the TASK_R6 command.
Baseline = this branch (main RP1a): rapids 24.4 m; region-entry feed 53.5 m = 42.1 min; total descending feed about
83.4 m = 65.6 min, i.e. about 30 m / 24 min of it is MID-REGION re-entries and lift descents (engine/RP2_0_RESULTS.md,
out/rp2_0_cf.json: 205 OPEN / 8 CLOSED regions, RT_RP2 instrumentation already here).
1. OPEN regions enter through the existing verified find_shift / feed_down offset-descent path FIRST: descend in cleared
   stock or air beside the region (live stock + part checks as today), then feed in sideways at depth with flank-only
   engagement. If that path fails its checks for a region, fall back to today's 2-deg helix. The 8 CLOSED regions keep
   2-deg helixes. No axial removal anywhere (zmap axial gate must stay 0).
2. Mid-region re-entries / lift descents (~24 min): measure them separately (count, length, time) before and after, and
   reduce them where the same verified side-entry or at-depth link applies; report on their own line.
3. Report before/after on Core Front T13 AND the test block: region-entry time, re-entry time, total descending-feed
   time, total cycle (zmap), rapids (must stay <= 24.4 m on CF), gouges/rapid collisions/axial/outside-grid (0).
   Engine suites + pytest verify connector engine/test_post.py green (scripts/check_fixtures.py first).
STOP and report (engine/RP2_1_RESULTS.md) if a target can't be met without workarounds.
