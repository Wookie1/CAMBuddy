# Task ZE2B: implement verify/ZE2B_DESIGN.md (ball-tool engagement, report-only). Build, then report. Do not commit.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase; no bypass flags; never relax or delete tests; do NOT touch
engine/ or opencode.json; verify/ must not import engine code. Edit verify/zmap.py and verify/test_zmap.py only.
Flat/bull tool output must stay BYTE-IDENTICAL (ZE2 keys and the whole --out-json). Report-only: ZE2B never changes an
exit code. BUDGET: <= 150 changed non-test lines in verify/zmap.py vs b1688b8 (numstat adds + dels), STOP at ~200.
HARD CAP 2 h; if the same test fails ~3 times with no new idea, stop and write the results file.
Worktree /Users/James/ai-sandbox/stevecam-ze2b, branch ze2b (b1688b8 = main 6b931ae + the design note). Read
verify/ZE2B_DESIGN.md first (approved: BOTH widths - w_plan vs c(a) for the full-width flag, ae_eq vs --engage-max for
load). Cite only commits that exist. NEVER print NGC/G-code or large outputs; rg / sed -n line ranges, never read big
files whole. Runs: small synthetic tests via
/private/tmp/claude-502/-Users-James-ai-sandbox-Assistr/adf268db-8f62-488c-bbb0-7ba55042f4d7/scratchpad/slot_m4.sh
(`/opt/homebrew/bin/python3 -m pytest verify -q`). NO Core Front or other real-part zmap job - the supervisor runs ZE2B
on the chain programs afterwards.

## Do
- implement the per-move sampling, windows, the two widths, theta, descent tagging, flags and the `engagement.ze2b` block +
  `--ae2b-dump`, exactly as the design note; ball only.
- tests in verify/test_zmap.py: the design note's cases 1-5 (analytic expectations: side pass ae_eq ~1.905 +-5% and
  w_plan/c(a) ~0.62; full slot w_plan ~7.76 flagged, ae_eq ~5.44; 45 deg skim not flagged; 2 deg helix finite and tagged
  descent where vertical; flat program JSON byte-identical to b1688b8's zmap - run both and cmp) and case 6, the mutation
  proof (c(a) -> D via a monkeypatch/wrapper, never an edit; the test must FAIL BY ASSERTION; `git diff --exit-code`
  after).
- full `/opt/homebrew/bin/python3 -m pytest verify connector engine/test_post.py -q` green at the end.

## verify/ZE2B_RESULTS.md (required)
(1) line count (`git diff --numstat b1688b8`, non-test vs test); (2) what changed with file:line; every test with exit
codes; the mutation proof; the flat byte-identity proof; (3) anything not done and why. Then stop.
