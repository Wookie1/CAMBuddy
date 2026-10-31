# Task PANELCANCEL5: bounded shutdown (< 30 s even if a child ignores SIGTERM) + plist ExitTimeOut 30. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: no Core Front and no real engine run. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh). Do NOT run
the whole connector/test_connector.py (~25 min); the supervisor runs full suites.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/timeouts. Add NEW tests only (append to
connector/test_panelcancel.py and menubar/test_menubar_files.py).
SCOPE (hard): edit ONLY connector/connector.py, menubar/com.stevecam.connector.plist.in, menubar/README.md (one line), the two
test files above (append), and a "## PANELCANCEL5" results section in connector/PANELCANCEL_RESULTS.md. Do NOT edit
connector/runner.py (the speed thread owns it), mock_steve.py, errors.py, catalog.py, panel/, engine/, verify/, the Swift app,
the shell scripts or opencode.json.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; install NOTHING; do NOT run
install_agent.sh, uninstall_agent.sh, make_app.sh or ANY launchctl command; do NOT touch ~/.stevecam, ~/Library/LaunchAgents or
the running connector; stop only processes you started, by exact PID (never pkill/killall). Never print or store keys, tokens
or pairing codes.
SCRATCH: /Users/James/ai-sandbox/stevecam-pc/scratch/ only - never /tmp. Tests use pytest tmp_path.
RESULTS: append "## PANELCANCEL5" to connector/PANELCANCEL_RESULTS.md EARLY and keep it current (command, exit code, `date`).
FRESH session, TIME BUDGET 40 min, HARD STOP 60 min. Worktree /Users/James/ai-sandbox/stevecam-pc, branch panel-cancel at the
commit carrying this brief (86ae1f8 = PANELCANCEL..4 work, + this brief).
Small tests ONLY via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"

## Facts (supervisor)
- launchd sends SIGTERM at logout/stop and SIGKILLs after ExitTimeOut (default 20 s; our plist sets none). The connector's
  shutdown tail = up to one POLL_INTERRUPT (10 s) + the active job's cancel + worker join(timeout=60) + queued rejects +
  "off". The engine children run in their own sessions (runner _spawn start_new_session=True), so a SIGKILLed connector
  leaves them orphaned.
- runner.py on THIS branch (main 2da9125): EngineRun keeps one live Popen in `self._proc`; cancel() only SIGTERMs its process
  group. The speed thread's pending sp-p3c changes runner.py to keep a set `self._procs` and cancel() SIGKILLs after 5 s.
  The speed thread may also add a PUBLIC EngineRun method - either `live_pgids()` (returns process-group ids) or
  `kill_all(sig)` - name not final. The connector must work with every shape without editing runner.py, in this order:
  public live_pgids() -> killpg each with SIGKILL; else public kill_all -> kill_all(signal.SIGKILL); else
  getattr(engine, "_procs", None) (a set of Popen); else getattr(engine, "_proc", None); live = poll() is None.
  Put this lookup in ONE small helper (e.g. _kill_engine_groups(engine)).
## Items
1. Plist: add `<key>ExitTimeOut</key><integer>30</integer>` to menubar/com.stevecam.connector.plist.in. README: one line
   saying the connector gets 30 s to shut down cleanly.
2. Bounded shutdown in connector.py's run_forever tail: after the active job's cancel, join the worker for a GRACE of 8 s
   (not 60); if it is still alive, SIGKILL every live process group of the active EngineRun (os.killpg(os.getpgid(p.pid),
   SIGKILL), ProcessLookupError/PermissionError -> p.kill(), OSError ignored), then join up to 4 s more; then queued rejects
   and "off" regardless. Worst case from SIGTERM to exit must be < 30 s: state your arithmetic (poll slice + grace + kill join
   + tail). Named constants, not magic numbers.
## Tests
 a. menubar/test_menubar_files.py::test_plist_exit_timeout: parse the RENDERED template (plistlib after substituting @REPO@
    and @HOME@ as test_plist_template_renders_and_lints does) and assert ExitTimeOut is an int >= 30.
 b. connector/test_panelcancel.py::test_shutdown_kills_child_ignoring_sigterm: a real connector subprocess whose fake run
    starts, through the REAL runner _spawn, a child `/bin/sh -c 'trap "" TERM; sleep 120'` (so cancel's SIGTERM is ignored);
    wait for "running"; SIGTERM the connector; assert exit 0 within 25 s (measure, state it), the child PID is gone
    (os.kill(pid, 0) -> ProcessLookupError; record the child's pid from the fake), pidfile removed, status "off". Always
    kill your own child by exact PID in a finally.
 d. connector/test_panelcancel.py::test_engine_kill_hook_exists: the REAL runner.EngineRun (no monkeypatch) - instantiate it
    (cfg + tmp work dir, as test_connector does) and assert at least one of live_pgids / kill_all / _procs / _proc exists on
    it, with a message naming all four, so a future rename fails loudly instead of silently dropping the SIGKILL backstop.
    Also a pure unit test of the helper with four fake engine objects (one per shape) that records which path was used.
 c. MUTATION M4 (scratch copy only): drop the SIGKILL step -> (b) red (connector waits out the grace, child survives).
    Record the measured result.
AT-RISK (must stay green; paste exit codes): connector/test_panelcancel.py (all), connector/test_pidstatus.py (all),
menubar/test_menubar_files.py (all), connector/test_show3d.py.
## Results: what changed (+ line counts), the worst-case arithmetic, (b) measured time, M4 measured. Then stop.
