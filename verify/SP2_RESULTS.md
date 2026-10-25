# Task SP2 results — zmap per-move speed-up, byte-identical JSON

Started: Sat Oct 24 2026, 13:22 MST (`date`). Base: e5e783e (= current verify/zmap.py,
`git diff --numstat e5e783e -- verify/zmap.py` empty at start). Branch sp2 @ c62427e.

## Status log (kept current per RESULTS RULE)

- 13:2x — worktree verified clean vs e5e783e for verify/zmap.py; `git show a6fc8c7 --stat`
  read: ze2b touches verify/zmap.py at L76 (ZE2B_DESCENT_FRAC const) and inserts ~150 lines
  after `_ae2_engagement_keys` (~L1154); 0 deletions. Plan: keep edits inside `simulate`'s
  sample loop (L1540-1600) and `tool_dz` (L417-435) away from those anchors.
- Baseline (before) extraction: `git archive e5e783e` → /private/tmp/claude-502/sp2_base
  (never checkout). Runs use the base script directly; after-runs use the worktree.

## Plan

Hot path: `simulate` sample loop — per sample: np.meshgrid (2 arrays), np.hypot, mask,
closure dz (5 temporaries), where/subtract/clip/sum reductions. All element-wise IEEE ops
→ batching/broadcasting with identical op order and dtype is bit-exact; pairwise-sum shapes
and every comparison kept identical.

## Test/run record

(to be appended after each run)

### Supervisor verification (2026-10-24/25, from frozen detached copies)
- verify suite at the sp2 merge fix 4ab9320: 115 passed.
- Test block, sp2 vs main 681f551: fin, rough, rr, fin with ZE2B (--engage-max 2.286), rr with ZE2B: all 5
  judge JSONs byte-identical.
- Core Front: 18/18 judge JSONs byte-identical, sp2 4ab9320 vs main 681f551, every judge rc 0/0. Inputs:
  chain..chain4 x (rr, t33, fin_after, fin_before), the bs1a3 CF flat rough, and the chain4 finish under ZE2B.
- Timing: each input was judged back to back on one lane (main, then sp2). Two pairs overlapped a contended window
  (2026-10-24 19:23-20:02, stray background sessions) and are excluded. The 16 uncontended pairs:
  main 11230 s, sp2 9721 s, 13.4 % less in total, mean per-pair saving 15.4 %. The 8 pairs of 60 s or more: mean
  13.4 % (10.1-17.8 %). One short pair (chain4 rr, 9 s vs 9 s) showed no saving at 1 s resolution.
- Peak RSS: at most +0.45 GB (bs1a3 CF rough, 2.24 -> 2.69 GB); the ZE2B finish went 4.77 -> 4.60 GB.
