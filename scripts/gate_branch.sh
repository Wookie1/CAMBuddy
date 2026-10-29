#!/bin/bash
# Merge gate for the checkout this script lives in (run it from a DETACHED worktree at the sha under test, inside a lane:
# slot2.sh or slot_m4.sh). (a) fixtures, (b) every engine test file standalone with VibeCAD python, (c) connector
# suite + verify/test_zmap.py (a pytest suite) with homebrew pytest, (d) each failure is re-run on a detached worktree of main and
# labelled NEW or PRE-EXISTING, (e) prints GATE_GREEN (all rc 0 or every failure PRE-EXISTING) else GATE_RED.
# No destructive git: the main worktree is only added (detached) and is left in place for inspection.
VPY=/Applications/VibeCAD.app/Contents/Resources/bin/python
HPY=/opt/homebrew/bin/python3
ROOT=$(cd "$(dirname "$0")/.." && pwd)
MAINREPO=$(cd "$ROOT" && cd "$(git rev-parse --git-common-dir)/.." && pwd)
SHA=$(git -C "$ROOT" rev-parse --short HEAD); MSHA=$(git -C "$ROOT" rev-parse --short main)
LOG=${GATE_LOG:-$ROOT/scratch/gate_$SHA}; mkdir -p "$LOG"
fixtures() { [ -d "$1/out" ] || cp -c -R "$MAINREPO/out" "$1/out"; }   # untracked fixtures, APFS clone
run_engine() {   # $1 root, $2 test file, $3 log -> rc
  (cd "$1" && ENGINE_WORKERS=4 "$VPY" "$2" > "$3" 2>&1); }
run_conn() {     # $1 root, $2 log, [$3 node id] -> rc
  (cd "$1" && "$HPY" -m pytest ${3:-connector} -q -rf -p no:cacheprovider > "$2" 2>&1); }

echo "gate $SHA (main $MSHA) logs $LOG"
fixtures "$ROOT"
FAILS=()
(cd "$ROOT" && "$HPY" scripts/check_fixtures.py) > "$LOG/fixtures.log" 2>&1 || {
  echo "fixtures rc=1 (see $LOG/fixtures.log)"; echo GATE_RED fixtures; exit 1; }
echo "fixtures rc=0"
for t in $(cd "$ROOT" && ls engine/test_*.py); do
  s=$(date +%s); run_engine "$ROOT" "$t" "$LOG/$(basename "$t" .py).log"; rc=$?
  echo "$t rc=$rc $(( $(date +%s) - s ))s"; [ $rc = 0 ] || FAILS+=("engine:$t")
done
s=$(date +%s); run_conn "$ROOT" "$LOG/connector.log" "connector verify/test_zmap.py"; rc=$?
echo "connector+verify/test_zmap(pytest) rc=$rc $(( $(date +%s) - s ))s"
if [ $rc != 0 ]; then
  ids=$(grep -E '^FAILED ' "$LOG/connector.log" | awk '{print $2}')
  [ -n "$ids" ] || ids=connector   # collection error etc.: compare the whole suite
  for i in $ids; do FAILS+=("conn:$i"); done
fi
[ ${#FAILS[@]} = 0 ] && { echo GATE_GREEN; exit 0; }

MW=${GATE_MAIN_WT:-$(dirname "$MAINREPO")/stevecam-wt/gate-main-$MSHA}
[ -d "$MW" ] || git -C "$MAINREPO" worktree add --detach "$MW" main > /dev/null 2>&1 || {
  echo "cannot add main worktree $MW"; echo GATE_RED "${FAILS[@]}"; exit 1; }
fixtures "$MW"
NEW=()
for f in "${FAILS[@]}"; do
  k=${f%%:*}; t=${f#*:}; ml="$LOG/main_$(echo "$t" | tr '/:' '__').log"
  if [ "$k" = engine ]; then
    if [ -e "$MW/$t" ]; then run_engine "$MW" "$t" "$ml"; mrc=$?; else mrc=0; fi   # new file: NEW
  else
    run_conn "$MW" "$ml" "$t"; mrc=$?
    case $mrc in 4|5) mrc=0;; esac   # test not on main (not found / none collected): NEW
  fi
  if [ $mrc = 0 ]; then echo "NEW          $t"; NEW+=("$t"); else echo "PRE-EXISTING $t (main rc=$mrc)"; fi
done
[ ${#NEW[@]} = 0 ] && { echo GATE_GREEN; exit 0; }
echo GATE_RED "${NEW[@]}"; exit 1
