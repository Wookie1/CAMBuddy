# RR1c-4b RESULTS — bore entry for top-down levels + fragment merge within D

## (1) Line count
`git diff --numstat c807939 -- engine/rest_rough.py` = **67 adds + 11 dels = 78**
changed non-test lines (target <= 60, hard stop ~80: over target, under the
stop - the descent ladder, the link_clear bridge and their comments are the
bulk). `engine/test_engine.py`: +157/-1 (two NEW tests + one helper + the
_main registrations; no existing test, assertion or tolerance touched).
`opencode.json` and `verify/` untouched (the pre-existing working-tree edit
of opencode.json predates this session and was not modified).

## (2) The change (engine/rest_rough.py, working tree on rr1b @ c807939)

### A. Bore entry (every multi-level zone)
- `rest_rough.py:600-609` - the ladder tries the BORE FIRST at the highest
  level of a multi-level zone: the same `helix_entry` (same 2-deg helix +
  floor circle) is run from the live disk-top down to `levels[0][0]`, the
  LOWEST legal level (cl_ok_path over the whole helix + live d0 <= zb_floor
  at the top, exactly as before); `mode = "bore"`. Helix time does not grow
  (same pitch, same radius rule; the depth equals what d46a04a already cut).
- `rest_rough.py:631-635` - single-level zones / fallback: unchanged helix
  to the entered level; a zone with no legal helix site still fails closed
  via the unchanged ladder -> `no_entry` report (`:637-649`).
- `rest_rough.py:660-668` - bore mode: prev = helix bottom; the step-5
  floor circle is cut at `tb` = lowest level.
- `rest_rough.py:680-684` - rise INSIDE the cleared bore to the entered top
  level (`g1` vertical at the bore point, ramp feed).
- `rest_rough.py:685-704` - each lower level is entered by a real descent
  INSIDE the bore at (cx + r_h, cy): horizontal link checked with
  `cl_ok_path`, then step drops of <= zb_floor - 0.05; every drop point
  passes the exact CL (`cl_ok`) AND the live ZB floor
  (`live.disk_depth <= zb_floor` on the LIVE stamped grid - never assumed
  air); a refused descent falls back to the unchanged enter() ladder path.
  Recorded as entry step 5 kind "bore-descent". Rings stay inside-out from
  the bore (c807939 `rings.reverse()` + `ring_seq` unchanged).
- Ladder steps 1/2/4 remain first choice for single-level zones, so
  rr1c/rr1c2/rr1c3 entry tests keep their recorded step numbers.

### B. Fragment merge distance
- `find_zones` (`rest_rough.py:102-103, 126-141`): merge radius is the tool
  DIAMETER `tool_d` (not R), and a merge happens ONLY if the callback
  `link_ok(fragment, zone)` accepts the bridge; otherwise the fragment stays
  a mini-zone (`fragment: True`, entered or reported downstream - nothing
  dropped silently, unchanged).
- `rest_rough.py:269-287` `link_clear(fr, zn)`: bridge = nearest
  fragment-cell to nearest zone-cell straight line, sampled every CELL/2 at
  the fragment's cutting Z (`fr.stockmax - rest_leave`); every point must be
  exact-CL-legal (batch_drop <= z + 0.005) AND stock-clear
  (`live.disk_top <= z + zb_floor`; inf fails closed).
- call site `rest_rough.py:289-290`: `tool_d=dia, link_ok=link_clear`.

## (3) Tests - pasted exit codes (all via slot_m4.sh, ENGINE_WORKERS<=4)

New code (/Users/James/ai-sandbox/stevecam-rr1b):
- test_rr1b_rest_rough_synth_pocket (conflict A, UNCHANGED): `EXIT=0`
  ("PASS rr1b_synth_pocket") - bore enters t=24.2, 3 levels cut top-down.
- test_rr1c3_curved_thin_band_centre_line (conflict B, UNCHANGED): `EXIT=0`
  ("PASS curved_band") - end caps now merge within D (link-clear bridge),
  len(zones)==1 again.
- batch of 5 existing rest tests (reports_small_pocket, thin_band_inpass_
  ramp, narrow_pocket_side_entry, cf_rapid_shapes, bay_deep_groove):
  `EXIT=0` (all 5 printed PASS).
- NEW test_rr1c4b_closed_pocket_bore_levels: `EXIT=0` ("PASS
  closed_pocket_bore").
- NEW test_rr1c4b_plateau_topdown_axial_load: `EXIT=0` ("PASS plateau")
  (interim runs during scene tuning failed the zmap wide-slot assertion with
  "ZE2B: 144.7/71.3 mm ..." - exit 1 - until the bore-first entry made all
  deep cutting-feed windows <= 2.286; final run `EXIT=0`).
- FULL suite `engine/test_engine.py`: `EXIT=0`, ledger tail `0 failure(s)`
  (includes both conflict tests and both new tests via _main).

Fail-on-d46a04a proof (`git archive d46a04a` extract to
/private/var/folders/.../opencode/rr1c4b_base, new test file copied in,
NEVER checked out):
```
FAIL-BY-ASSERTION test_rr1c4b_plateau_topdown_axial_load : plateau must be
    entered by the bore helix: {'bbox': (14.1..., 25.9..., ...)}   # helix=0
FAIL-BY-ASSERTION test_rr1c4b_closed_pocket_bore_levels : lower levels not
    re-entered through the bore: [{'zone': 0, 't': 24.2, 'step': 5,
    'kind': 'helix 2.0 deg r=4.16...'}]                            # no descents
EXIT=0   (runner exits 0 only when BOTH new tests failed by assertion)
```
Baseline diagnostics: plateau entered by SE2 (`helix 0.0`, step 4) and cuts
Z 26.8 (lowest) first; closed pocket records a single entry (helix at the
lowest level) and no descents below the top - exactly the behaviours the new
tests forbid.

## (4) Not done / caveats
- Plateau scene interpretation: "flat floor with a rest block over it and a
  lower legal entry pocket" is realized as a 12x12x3.4 mm stock block over a
  flat part floor whose LOWEST level is the legal helix entry (the SE2/low
  entry the old code took there). A recessed sub-pocket with vertical walls
  was rejected after measurement: its unreachable wall strips read full-width
  engagement at every level, which would make the ZE2B bar unachievable in
  the scene itself.
- zmap (verify/zmap.py, read-only, padded part grid, --engage-max 2.286
  equivalent): the test asserts 0 mm of wide SLOTS (ae_eff > 2.286 AND
  a > 0.5, the ZE load class that produced Core Front's 41.6 mm finding) at
  cutting feed and `full_width_slots_ae2_cutting_feed.count == 0`. Shallow
  concentric re-cut films (a <= 0.25, zmap "skim" class) are listed
  separately by design and not asserted at 0; the axial-engagement assertion
  (<= stepdown + 0.05 via live disk_top) guards the load directly and both
  new tests additionally pin bore entry + top-down cut order, which is where
  d46a04a provably fails.
- Line budget: 78 vs the <= 60 target (under the ~80 stop).
- No Core Front engine or zmap job was run; no commit made; no locks,
  tests, tolerances, verify/ or opencode.json touched.
