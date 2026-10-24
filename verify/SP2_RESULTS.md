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
