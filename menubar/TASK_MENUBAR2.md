# Task MENUBAR2: SIGTERM exit-0 test + "run in progress" guard in the menu-bar app. Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: Core Front (core_front_setup) jobs run ONLY on the CF lane, which is the supervisor's - you never run a Core Front
rough/finish/rest-rough or chain, and no engine run at all in this task. NOTHING longer than 10 minutes goes on the small lane
(slot_m4.sh). If a run would exceed 10 min, don't start it; write what you would have run into the results file.
In particular do NOT run the whole connector/test_connector.py (it takes ~25 min); the supervisor runs full suites on the CF lane.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions/tolerances. Add NEW tests only.
SCOPE (hard): edit ONLY menubar/SteveCAM.swift and menubar/README.md, and ADD new tests to connector/test_pidstatus.py (append;
do not change its existing four tests). connector/connector.py may change ONLY if a red test proves it necessary - say so.
Do NOT edit connector/runner.py, connector/panel/, connector/catalog.py, engine/, verify/ or opencode.json.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; no bypass flags; install NOTHING; do NOT run make_app.sh,
install_agent.sh, uninstall_agent.sh or any launchctl command; do NOT touch ~/.stevecam, ~/Library/LaunchAgents or the running
connector; stop only processes you started, by their exact PID (never pkill/killall). Never print or store keys, tokens or
pairing codes.
SCRATCH: /Users/James/ai-sandbox/stevecam-mb/scratch/ only - never /tmp. Tests use pytest tmp_path.
RESULTS: append a "## MENUBAR2" section to menubar/MENUBAR_RESULTS.md EARLY and keep it current (command, exit code, output, `date`).
FRESH session, TIME BUDGET 45 min, HARD STOP 70 min (`date` at start). Worktree /Users/James/ai-sandbox/stevecam-mb, branch menubar
at the commit carrying this brief (9c031a0 = the MENUBAR work, + this brief).
Small tests ONLY via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>::<test>"
Swift build ONLY into scratch/: slot_m4.sh /usr/bin/swiftc -O -swift-version 5 -parse-as-library menubar/SteveCAM.swift -o scratch/SteveCAM

## Facts (supervisor)
- connector.py run_forever installs signal.signal(SIGTERM, self.stop); the loop ends after the current long-poll (poll_wait s,
  from <home>/config.toml, default 30); main() then releases the pidfile and returns 0. status.json says "off" at the end.
- While a run is active the connector's status.json "state" is "busy" (emit_state("busy", action, progress)); idle is "idle".
- test_connector.py already builds connectors against stubbed STEVE responses; look there for a fake server/client to reuse.
## Items
1. NEW test connector/test_pidstatus.py::test_sigterm_exits_zero: start a REAL child `python3 connector/connector.py --home <tmp>`
   that reaches its message loop against a local fake STEVE (a tiny http.server in a test thread on 127.0.0.1:<free port>, via
   STEVE_BASE_URL; tmp home with config.toml poll_wait = 1 and a state.json that is already enrolled - reuse whatever
   test_connector.py does). Wait until status.json says "idle" (<= 20 s), send SIGTERM to the child's exact PID, and assert:
   exit code 0 within 15 s, connector.pid removed, status.json state "off". Kill the child by exact PID in a finally.
   MUTATION M4 (scratch copy): remove the SIGTERM handler line -> the test must go red with the measured exit code (expect -15).
2. SteveCAM.swift: when status "state" is "busy", the menu's Stop and Restart first show an NSAlert "A run is in progress. Stop
   anyway?" (buttons Stop / Cancel; Cancel does nothing). The URL actions stevecam://stop and stevecam://restart REFUSE while busy
   (no signal sent; record one line "refused stop: run in progress" in ~/.stevecam/menubar.log with a timestamp) unless the URL
   carries force=1 (stevecam://stop?force=1), which stops without asking. stevecam://start is unchanged. The "Turn off after"
   timer already only acts when idle - keep it so.
   Put the decision in a small pure function (e.g. func stopDecision(state: String?, force: Bool, fromURL: Bool) -> enum
   {proceed, confirm, refuse}) and add NEW checks to menubar/test_menubar_files.py ONLY by appending a new test function that
   greps SteveCAM.swift for: the exact alert text, "force", and that every kill( call site is reached only after the decision
   (state the check you used). Also keep `swiftc -typecheck` green.
3. README: one short paragraph on the busy guard and force=1.
AT-RISK (must stay green; paste exit codes): connector/test_pidstatus.py (all), menubar/test_menubar_files.py (all),
connector/test_show3d.py, connector/test_units_publish.py.
## Results: red test (1) before/after with numbers, M4 measured, swiftc build size, changed line counts. Then stop.
