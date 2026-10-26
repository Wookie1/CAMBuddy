# BS1a4d4 results

Session start: Sat Oct 24 16:08 MST (hard cap ~18:08). Worktree
`/Users/James/ai-sandbox/stevecam-bs1a4d4`, branch bs1a4d4 @ 76f968f (code =
6793ad9). No commits. No Core Front job. Everything foreground. Finished
17:45 MST, inside the cap.

NOTE: `slot_m4.sh` does not exist anywhere on this machine (searched PATH,
~/bin, ~/.local/bin, /Users/James/ai-sandbox/**, mdfind). Tests were run
directly with the VibeCAD python
(/Applications/VibeCAD.app/Contents/Resources/bin/python), one targeted test
in the FOREGROUND at a time - never the full suite, no Core Front job.

## (1) Change (file:line on the final tree)

engine/band.py (channel_regions, after the region's credit is set):
- band.py:473-478 - when `borefn` (the bore predictor installed via
  band.bore_context) is active and the piece carries credit > 0, evaluate
  the predictor AT THE PIECE START and store the accepted bore:
  `res["bore"] = (sx, sy, cx, cy, r)` (start evaluated, centre, radius;
  direction is fixed - helix_entry's a0 = atan2(entry - centre), exactly the
  phase _bore_pred used). +6 lines.

engine/rough.py:
- rough.py:1251 - `helix_entry(..., bore=None)`.
- rough.py:1390-1395 - stored bore branch: try_cand(centre, radius) with NO
  re-search; on any emit-time check failure
  `raise RuntimeError("band credit bore rejected at emit: (x, y)")` - never
  substitutes another entry. The stored bore IS the centred geometry, so the
  bore entry keeps the centred start-side (bore OPPOSITE the entry, the
  BS1a4d2b emit shape - see (4): passing centred=False here changed the
  pre-clear sequence and broke test_bs1a4b_windows_align_zmap by one zmap
  window; with the fix the emitted TB entry is byte-identical to the
  baseline's).
- rough.py:1554,1580-1581 - feed_down threads `bore`; `centred or bore is
  not None` gives the stored bore its opposite-side start.
- rough.py:1691,1740 - enter_at threads `bore` to the tier-4 descent.
- rough.py:2129-2131 - band entry pins `entry = res["bore"][:2]` so the
  emitted entry is exactly the stored start (the predictor's XY).
- rough.py:2137-2138 - `centred="credit" in res` (always True - band.py:471
  sets credit on every region) REPLACED by `bore=res.get("bore")`: with a
  stored bore, enter with exactly that bore; without one, the NORMAL full-
  tier ladder (centred=False), as before BS1a4d2b.
+15/-6 lines.

Line count: `git diff --numstat 6793ad9 -- engine/band.py engine/rough.py`
= `6 0 band.py` + `15 6 rough.py` = **27 adds+dels** (budget <= 30, stop 45).
engine/test_engine.py: +160/-1 (NEW test only + one _main() registration;
no existing test touched).

## (2) Test scene and credited regions

test_bs1a4d4_credit_entry_matches_prediction: L channel + island box
`_box_tris(5.5, 9.5, 12.0, 16.0, 0.0, 18.0)` beside the vertical arm.
- rough generates; **24 band regions, all entry_credit = tool_r 6.343**.
- **15 regions carry a stored bore** (res['bore']); **7 of them
  helix-entered with exactly their stored bore** - centres captured EXACTLY
  (wrapped engine.rough._helix_moves) match res['bore'] centre < 1e-6 and
  radius < 1e-9. Entries: (-18.724,0.685) bore c=(-16.8711,0.6852) r=1.9029;
  (-4.783,-1.595) c=(-5.2326,-1.5955) r=0.5; (-4.825,-1.998)
  c=(-5.2405,-1.8255) r=0.5; (-6.272,3.523) c=(-6.0997,3.1074) r=0.5;
  (-4.902,-2.621) c=(-4.9589,-2.4822) r=0.2; (-6.755,3.165)
  c=(-6.0457,1.4535) r=1.9029; (-6.354,3.383) c=(-6.3542,2.9327) r=0.5.
- **2 credited regions whose starts hug the inner-corner block have NO
  centred bore that fits** (predictor None - the brief's "credit 0 there" =
  the predictor's bore credit is 0; entry_credit is tool_r, exactly the Core
  Front failure class): (-4.765,-2.253) and (-6.042,3.689) @Z0.381. Both
  descend via the NORMAL ladder (bore centre 3.0 mm from the entry,
  |centre dist - r| = 0.17, the centred-only signature is 0.05) - asserted.
- clcheck 0, n_axial_plunge 0 (gates: allowance/CLCHECK are hard - rough
  raises; rough generated).
- On 6793ad9 an instrumented baseline prints CENTRED-LADDER-EXHAUSTED at
  exactly those two entries (all 96 centred candidates rejected - the Core
  Front failure, one step from failing closed; baseline survives only via
  offset descent).

## (3) Fail-on-6793ad9 (git archive export, test appended verbatim, never
checked out) - FAILS BY ASSERTION:

    FAIL BY ASSERTION: no band region carries the bore its planner accepted:
    the credit and the emitted entry are still two separate decisions
    EXIT=1

On this tree the same test: PASS, EXIT=0 (output in (4)).

## (4) Exit codes (all foreground, VibeCAD python; ALL re-run after the
final engine edit, final numstat above)

    test_bs1a4d4_credit_entry_matches_prediction  EXIT=0   (new test, this tree)
    test_bs1a4d4_credit_entry_matches_prediction  EXIT=1   (6793ad9, by assertion, (3))
    test_bs1a4b_failed_region_lightest            EXIT=0
    test_bs1a4b_windows_align_zmap                EXIT=0
    test_bs1a4c_fix_no_post_entry_helix           EXIT=0
    test_bs1a4c_backed_credit                     EXIT=0
    test_bs1a4c2_band_chord_cl_checked            EXIT=0
    test_bs1a4d_credit0_lightest_option           EXIT=0
    test_bs1a4d_credit_real_bore                  EXIT=0
    test_bs1a4d2b_centred_entry_bore              EXIT=1   <-- SEE (5)
    test_bs1a4d3_links_measured_as_cuts           EXIT=0
    test_bs1a_lshaped_channel                     EXIT=0
    test_bs1a_straight_channel                    EXIT=0
    test_bs1a3_no_band_after_a2d                  EXIT=0

Debug trail (not part of the suite): an intermediate version of the change
passed centred=False with a stored bore; that flipped the bore's START side
(near instead of opposite the entry), changed the TB pre-clear sequence and
made test_bs1a4b_windows_align_zmap fail "engine 791 vs zmap 790" (baseline
EXIT=0, fixed tree EXIT=0). Diagnosed via instrumented baseline/new runs
(entry G0 lands (6.226,-2.0778) vs baseline (12.5587,-1.8226) around the
SAME centre (9.3975,-2.0778) r=3.1715) and fixed by `centred or bore is not
None` in feed_down's helix_entry call.

## (5) test_bs1a4d2b_centred_entry_bore - FAILS on the new tree, inherent to
the brief; supervisor decision needed (I must not rewrite existing tests):

    AssertionError: bs1a4d2b_lshape: entry bore at (-4.765,-2.253)@Z0.381
    is not centred on the start: centre (-7.06,0.04) is 3.24 mm away > r + 0.3
    EXIT=1

That region has entry_credit = tool_r but NO predicted centred bore (the
predictor declines there - it is the Core Front failure class). Brief
change #2 mandates exactly this: "Otherwise use the normal entry ladder with
all tiers (centred=False), as before BS1a4d2b" - so its entry now bores on
the normal ladder (centre 3.0 mm away, disk fully cleared by the return
feed, clcheck/axial 0), while d2b's assertion "every credited band entry
that bored is centred on the start" still encodes the pre-BS1a4d4 rule that
this task supersedes. The rest of d2b holds (no fresh stock under any start
disk; the bore-predicted entries are centred; its TB/L non-vacuity asserts
are met up to this assertion). NOT a gate relaxation: the test is untouched
and reported failing.

## (6) Fixture note (environment, not code)
out/ was absent from this worktree; three at-risk tests need
out/test_block.stl + test_block_hf_0.1/0.5(.npy/.json). Regenerated the STL
per fixtures/manifest.json (engine.model.step_to_stl('samples/test_block.step',
tol=0.01)) - sha256 MATCHES the manifest - and copied the two hf fixture
pairs from sibling worktree /Users/James/ai-sandbox/stevecam-bs1a4d (sha256
matches the manifest for hf_0.5; hf_0.1 identical across sibling worktrees).
These are untracked data files under out/, not engine or test edits.

## (7) State at finish
- Uncommitted (per brief): M engine/band.py, M engine/rough.py,
  M engine/test_engine.py, new engine/BS1a4d4_RESULTS.md. (M opencode.json
  predates this session.)
- No lock/prio/busy file touched; no git stash/reset/clean/restore/checkout/
  rebase/cherry-pick; no verify/ edit; no bypass flags; no margin/leave/feed
  change; engine imports no zmap/verify.
