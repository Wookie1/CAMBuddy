# Task MENUBAR: SteveCAM menu-bar app + LaunchAgent + connector pidfile/status. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough or chain, and no engine run at all in this task. NOTHING longer than 10 minutes goes on the small lane
(slot_m4.sh). If a run would exceed 10 min, don't start it; write what you would have run into the results file.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
SCOPE (hard): you may edit ONLY connector/connector.py (pidfile + status file, nothing else) and add NEW files under menubar/
and the one new test file connector/test_pidstatus.py. Do NOT edit connector/runner.py, connector/panel/, connector/catalog.py,
anything in engine/ or verify/, or opencode.json.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; install NOTHING (no pip/brew); do NOT
run make_app.sh into ~/Applications, do NOT write to ~/Library/LaunchAgents, do NOT run launchctl bootstrap/bootout/kickstart/load,
do NOT touch ~/.stevecam or the running connector (never kill, pkill or killall anything you did not start yourself in this
task; stop your own test processes by their exact PID). Never print, log or store keys, tokens or pairing codes. Do not touch
/Applications/VibeCAD.app. Do not copy code from any other project on this Mac (write it fresh).
SCRATCH: scratch files only in /Users/James/ai-sandbox/stevecam-mb/scratch/ - never /tmp. Tests use temp dirs (pytest tmp_path).
RESULTS: create menubar/MENUBAR_RESULTS.md EARLY and keep it current: after EVERY test run append the command, its exit code and
what it printed. Report only numbers you measured, name only tests that exist, give real clock times (`date`).
FRESH session, TIME BUDGET 75 min, HARD STOP 110 min (run `date` at start and check it). Worktree /Users/James/ai-sandbox/stevecam-mb,
branch menubar at the commit carrying this brief (= main 7de85a4 + brief). Report changed non-test line counts per file.
Small tests ONLY through /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh <command>:
  /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"
Swift: /usr/bin/swiftc (Apple Swift 6.4, already installed). Build ONLY into scratch/, e.g.
  /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /usr/bin/swiftc -O -swift-version 5 -parse-as-library menubar/SteveCAM.swift -o scratch/SteveCAM

## Facts (supervisor)
- The connector runs today as `cd ~/ai-sandbox/stevecam && nohup /opt/homebrew/bin/python3 connector/connector.py` (cwd = repo root,
  log ~/.stevecam/connector.log). Its home is config.state_dir() (~/.stevecam, or --home / STEVECAM_HOME for tests).
- connector.py: Connector.__init__ (~L62), emit_state (~L183, posts engine_state {state, action, progress}), record_run_end
  (~L338), run_forever (~L608; SIGTERM -> stop() -> loop ends after the current long-poll, up to ~30 s), main (~L644; returns 0).
  So SIGTERM gives exit code 0; a crash gives non-zero. Tests build a Connector as connector_mod.Connector(str(home))
  (test_show3d.py ~L41, test_connector.py ~L555) - reuse that pattern with the client's network calls stubbed.
- state.json keeps {enrolled, fingerprint, cursor, steve_keys}; identity.key holds the private key. Neither may be copied into
  the new status file.

## Items
1. connector.py, pidfile (<home>/connector.pid): module-level acquire_pidfile(home) -> (ok, other_pid) and release_pidfile(home).
   acquire: if the pidfile names a PID that is alive AND whose command line (`ps -o command= -p PID`) contains "connector.py"
   AND is not os.getpid() -> (False, PID). Otherwise (no file, unreadable, dead PID, or a live PID that is some other program)
   write os.getpid() atomically (tmp + os.replace) -> (True, None). release removes the file ONLY if it holds os.getpid().
   main(): call acquire before building the Connector; on (False, P) print exactly
   "connector already running (pid P); not starting a second one" and return 0 (exit 0, so launchd does not respawn it).
   Release in a finally around run_forever.
2. connector.py, status file (<home>/status.json, written atomically): {pid, state, action, progress, updated (UTC ISO),
   fingerprint, connector_name, commit, last_run}. commit = `git -C <repo_root> rev-parse --short HEAD` computed once at start
   ("" on any failure). Written by emit_state (every call, even when the event is unchanged or posting fails), "starting" at the
   top of run_forever, "off" when run_forever ends. last_run = the newest entry of _last_runs_data()["runs"] (or null), refreshed
   in record_run_end. Never raises into the run loop. NEVER contains keys, steve_keys, tokens, identity or pairing code.
3. menubar/SteveCAM.swift (SwiftUI, macOS 13+, MenuBarExtra + a small Settings window), compiled with swiftc -parse-as-library:
   - Menu: status line ("Running, pid N" / "Working: <action> NN%" / "Stopped"), "main <commit>", connector name + short
     fingerprint, last run (action + time) if any; then Start, Stop, Restart, Open log, Settings..., Quit SteveCAM.
     Read status from ~/.stevecam/status.json and liveness from ~/.stevecam/connector.pid (PID alive AND `ps` command contains
     connector.py); refresh every 3 s.
   - Start: `/bin/launchctl kickstart gui/<uid>/com.stevecam.connector` (only when not already running).
   - Stop: SIGTERM to the EXACT PID from the pidfile, only after re-checking that PID's command contains connector.py; wait up to
     45 s for it to exit. Never kill by name. Restart = Stop, then Start.
   - Open log: open ~/.stevecam/connector.log. Quit quits the app only (the connector keeps running).
   - URL scheme stevecam://start, stevecam://stop, stevecam://restart -> the same actions.
   - Settings window: "Start at login" toggle (rewrites RunAtLoad in ~/Library/LaunchAgents/com.stevecam.connector.plist; takes
     effect at next login), "Turn off after" picker [Never (default), 30 min, 2 h, 8 h] saved in ~/.stevecam/menubar.json; when
     not Never, the app Stops the connector once status.json has said idle for that long.
   - Never shows or stores pairing codes or keys. The repo path comes from Info.plist key SCRepo.
4. menubar/com.stevecam.connector.plist.in (template, @REPO@ and @HOME@ placeholders): Label com.stevecam.connector;
   ProgramArguments [/opt/homebrew/bin/python3, @REPO@/connector/connector.py]; WorkingDirectory @REPO@; RunAtLoad true;
   KeepAlive {SuccessfulExit false}; ThrottleInterval 10; StandardOutPath and StandardErrorPath @HOME@/.stevecam/connector.log;
   EnvironmentVariables PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin and HOME=@HOME@. It must NOT set ZMAP_NO_CKERN,
   STEVECAM_NO_CKERN or ZMAP_JOBS (the C kernels auto-build with /usr/bin/cc and ZMAP_JOBS lives in runner.py).
5. menubar/make_app.sh (builds ~/Applications/SteveCAM.app with swiftc: Info.plist with LSUIElement true, CFBundleIdentifier
   studio.stevecam.menubar, URL scheme stevecam, SCRepo = repo root; build log ~/.stevecam/app-build.log; exits non-zero on a
   failed build), menubar/install_agent.sh (renders the template into ~/Library/LaunchAgents/com.stevecam.connector.plist,
   `plutil -lint`s it, then `launchctl bootstrap gui/$(id -u)` it only if the label is not already loaded; refuses with a message
   if connector.pid names a live connector.py that launchd did not start), menubar/uninstall_agent.sh (bootout + remove the plist).
   You WRITE these scripts; you do NOT run make_app.sh's install step, install_agent.sh or uninstall_agent.sh.
   menubar/README.md: build, install, uninstall, what each menu item does (short).
RED TESTS (write first, run on the UNCHANGED code, paste numbers):
 (a) connector/test_pidstatus.py::test_second_connector_refuses: start a dummy live process whose command line contains
     "connector/connector.py" (e.g. python3 -c "import time; time.sleep(60)" connector/connector.py), write its PID into
     <tmp home>/connector.pid, then run `python3 connector/connector.py --home <tmp home>` with STEVE_BASE_URL=http://127.0.0.1:9
     and a 15 s timeout: it must exit 0 within the timeout, print the exact refusal line, and leave the pidfile holding the
     dummy's PID. Kill the dummy by its exact PID afterwards. (On main it does not refuse: measure and paste what happens.)
 (b) ::test_stale_pidfile_is_taken_over: pidfile with a dead PID, and separately with the live PID of a non-connector process
     (`sleep 60`, killed by exact PID afterwards) -> acquire_pidfile returns (True, None) and the file holds os.getpid();
     release_pidfile removes it; release does nothing when the file holds another PID.
 (c) ::test_status_file: Connector(tmp home) with network calls stubbed; emit_state("busy", "adaptive_rough", 0.42) -> status.json
     has state/action/progress/pid/updated/commit/fingerprint; then a failing post_event still updates status.json; the file text
     contains none of: the identity key's base64, any steve_keys value, "steve_keys", "token", "pairing".
 (d) menubar/test_menubar_files.py (pytest): the rendered plist template passes `plutil -lint`; ProgramArguments, KeepAlive
     {SuccessfulExit: false}, RunAtLoad true, PATH contains /usr/bin and /opt/homebrew/bin; no ZMAP_NO_CKERN/STEVECAM_NO_CKERN/
     ZMAP_JOBS anywhere in menubar/; `swiftc -typecheck -parse-as-library menubar/SteveCAM.swift` exits 0; SteveCAM.swift
     contains no "pkill", "killall" or "kill -9"; the sh scripts pass `bash -n`.
MUTATIONS (scratch copies; each must make a test fail by a MEASURED value - paste it): M1 drop the "connector.py" command check
in acquire (any live PID blocks), M2 make release remove the file whatever PID it holds, M3 write steve_keys into status.json.
AT-RISK (must stay green; run ALL, paste exit codes): connector/test_connector.py, connector/test_show3d.py,
connector/test_view3d.py, connector/test_units_publish.py, connector/test_toollib.py.
## menubar/MENUBAR_RESULTS.md: change (file:line), line counts, red tests before/after, mutation table, PASTED exit codes, the
swiftc build result (scratch/SteveCAM binary size). Then stop.
