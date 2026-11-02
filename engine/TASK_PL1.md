TASK PL1: run the Core Front rough's "pass-opener" levels' Adaptive2d ahead of time on extra cores (engine/rough.py,
engine/cli.py, one new test file). Two items, in order. Item 1 must be committed and green before item 2 starts.

CONTEXT (measured by the supervisor on Core Front, 2026-11-01; do NOT re-measure Core Front yourself)
- engine/rough.py rough() plans its levels in `order` (plan_stepup_levels + mandatory flat levels), then runs ONE level
  at a time in `for z in order:` (~line 2358). For each level it builds the Adaptive2d inputs from the LIVE stock
  model (stock.region_mask -> dilate -> contours -> outer filter -> hole filter, islands from isl_cache) and calls
  `_run_a2d(outers, holes, isl_in, tool_r, leave, stepover, tolerance, keep_tool_down, helix_dia, z, stats)`
  (~line 2620). `_run_a2d` is a pure function of those arguments (plus stats counters) and returns picklable region
  dicts; Adaptive2d gets no cleared-stock input.
- Core Front has 34 levels; Adaptive2d is ~335 s of the ~552 s rough, on one core. Three levels are "pass openers":
  levels whose Z is LOWER than every level before them in `order` (Z 42.354 first, then 35.306, then 25.146). For a
  pass opener, every earlier level cut only ABOVE it, so its live-stock inputs equal the inputs built from the INITIAL
  stock (proved: identical masks). Their Adaptive2d takes ~80 s, ~51 s and ~39 s. Every other level re-clears what
  earlier levels left and must stay sequential.
- Goal: before the loop, build the 2nd, 3rd, ... pass openers' inputs (stock still initial) and run their `_run_a2d`
  in a process pool while the loop works through the earlier levels; at an opener, use the pooled result ONLY if the
  inputs the loop builds are exactly equal to the precomputed ones, else run inline as today. Expected ~90 s saved.
- Adaptive2d's link search runs on a CPU clock budget, so a pooled result can differ from an inline one under load;
  that is acceptable (proofs are gates-equal), but with the pool OFF the output must stay byte-identical to today.

ITEM 1 - extract the per-level input building (no behaviour change)
- Move the code that builds one level's Adaptive2d inputs (loop start -> just before `_run_a2d`) into a nested
  function inside rough(), e.g. `_level_a2d_inputs(z)`, that returns everything the rest of the loop body uses
  (outers, holes, isl_in, mask/area values, grown, flags, ...) or a "skip" result. It must have NO side effects on
  stock, moves, prev or stats: the loop keeps doing every stats append (skipped-level entries, t_islands, rp
  diagnostics) and every `continue` exactly where and in the order it does now, using what the helper returns.
- Closures defined in that span that the later loop body uses (rp2_open, corridor_ok, ...) stay defined in the loop
  (or are returned) so the rest of the loop is unchanged.
- Acceptance for item 1: the whole existing engine suite passes unedited (run each engine/test_*.py file with
  VibeCAD python, FOREGROUND, one at a time); a Test Block rough before/after is byte-identical (the supervisor also
  checks Core Front). Commit item 1 on its own (explicit paths) before starting item 2.

ITEM 2 - the pass-opener pool, verify-and-fallback
- After the island pool has closed and before `for z in order:`, find the pass openers after the first (a level is an
  opener when its Z < min(Z of all levels before it in `order`)). For each, build its inputs with `_level_a2d_inputs`
  on the untouched stock and submit a job to ONE ProcessPoolExecutor (spawn context, workers = min(#openers,
  ISLAND_POOL)). The job runs `_run_a2d` on a private stats dict and returns (regions, a2d_spnf delta,
  a2d_dropped_outers list) - the parent applies those to its stats when the result is used, in the same place the
  inline call would.
- At an opener inside the loop: build the inputs as today; if outers, holes and isl_in are EXACTLY equal to the
  precomputed ones (==), wait for the future and use it; otherwise discard it and run `_run_a2d` inline. Never use a
  result whose inputs differ.
- Off switch: `engine.cli rough --a2d-pool 0` and env `ENGINE_A2D_POOL=0` give today's path byte-for-byte (default
  on). Record `stats["pl1"] = {"openers": n, "precomputed": n, "used": n, "fallback": n, "t_wait_s": s}`. Shut the pool
  down at the end of rough(). Total processes never exceed ENGINE_WORKERS / ISLAND_POOL at any time.

FILES (LOCKS): engine/rough.py, engine/cli.py (the flag only), NEW engine/test_pl1.py. Nothing else. Do not edit,
delete or rewrite ANY existing test; if a requirement conflicts with an existing test, stop and write why in the
results file.

TESTS (new file engine/test_pl1.py, VibeCAD python, runnable directly; use small synthetic/TB scenes only)
(a) opener detection: a unit test of the opener rule on a hand-made `order` list (e.g. [42.4, 42.9, 47.2, 35.3, 36.4,
    25.1, 27.0] -> openers 35.3 and 25.1 after the first).
(b) pool on vs off on synth_pocket (connector/testdata/synth_pocket.step via engine.cli prepare + rough, as
    engine/test_sp_hf1b.py does) and on the BS1d scene of engine/test_engine.py test_bs1d_a2d_drop_counted:
    pool off == today (byte-identical G-code vs a run with ENGINE_A2D_POOL=0 is the same code path; compare
    against the inline result), pool on gives the same gates (no axial plunge, clcheck 0) and stats["pl1"]["used"]
    >= 1 where the scene has a second opener.
(c) fallback: monkeypatch so one precomputed input differs (e.g. drop a point from a precomputed outer); the loop must
    take the fallback (stats["pl1"]["fallback"] >= 1) and the program must equal the pool-off program.
MUTATION (required, record the measured failure in the results file): make the loop use the precomputed result even
when inputs differ; test (c) must FAIL. Restore the code byte-for-byte afterwards (cmp).

HARD RULES
- Running any Core Front job voids the round: the supervisor runs all Core Front jobs. Test Block / synthetic only.
- No change to cutting data, tolerances, feeds, entries, gates, SK1/SKN/M1/M2 logic or any check. Item 1 is a pure
  refactor; item 2 only changes WHEN Adaptive2d runs for opener levels, never what it is given.
- Tests run in the FOREGROUND, one file at a time; never background a test. 2 h cap.
- Commit with explicit paths (`git commit -- path ...`); no stash/reset/rebase/checkout of files.
- Write your progress and every test result (and the mutation result) to the results file you were given as you go.
