# Task MENUBAR3: open Settings with SwiftUI's SettingsLink (the legacy selector is broken on this macOS). Do not commit.
LOCKS: NEVER create, remove or edit /private/tmp/claude-502/*.lock, /private/tmp/claude-502/m4slot.prio or /private/tmp/claude-502/m4model.busy - not even a lock you think is stale (the slot scripts clear a dead owner's lock themselves); if a slot seems stuck, write that into your results file and wait or stop.
**LANE RULE: no Core Front or engine runs at all in this task. NOTHING longer than 10 minutes goes on the small lane (slot_m4.sh);
do NOT run connector/test_connector.py. If a run would exceed 10 min, don't start it; write it into the results file.**
TESTS: do NOT delete, rename or rewrite any existing test or its assertions. Add NEW tests only (append to menubar/test_menubar_files.py).
SCOPE (hard): edit ONLY menubar/SteveCAM.swift (+ the appended test, + a results section). Nothing else.
HARD RULES: no git stash/reset/clean/restore/checkout/rebase/cherry-pick; install NOTHING; do NOT run make_app.sh, install_agent.sh,
uninstall_agent.sh, launchctl, or the built app; do NOT touch ~/.stevecam or ~/Library/LaunchAgents; stop only your own processes by
exact PID. SCRATCH: /Users/James/ai-sandbox/stevecam-mb/scratch/ only.
RESULTS: append "## MENUBAR3" to menubar/MENUBAR_RESULTS.md EARLY (commands, exit codes, output, `date`).
FRESH session, TIME BUDGET 25 min, HARD STOP 40 min. Worktree /Users/James/ai-sandbox/stevecam-mb, branch menubar at the commit
carrying this brief (8b375e3 + brief).
Small tests via /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 -m pytest -q -p no:cacheprovider "<path>"
Swift build ONLY into scratch/: slot_m4.sh /usr/bin/swiftc -O -swift-version 5 -parse-as-library menubar/SteveCAM.swift -o scratch/SteveCAM

## Facts (supervisor)
- This Mac runs macOS 27 (Darwin 27). Another app on it measured that NSApp.sendAction(Selector(("showSettingsWindow:"))) /
  "showPreferencesWindow:" no longer opens a SwiftUI Settings scene on macOS 27. The supported ways are SwiftUI's SettingsLink
  (macOS 14+) inside the MenuBarExtra content, or the openSettings environment action (macOS 14+).
- SteveCAM.swift: openSettingsWindow() (~L84) uses those selectors; the menu's "Settings..." Button calls it; the scene has a
  Settings { } window. LSMinimumSystemVersion is 13.0 (make_app.sh).
## Item
1. In the menu, use `if #available(macOS 14, *) { SettingsLink { Text("Settings...") } } else { Button("Settings...") { openSettingsWindow() } }`
   (activate the app first so the window comes to the front: NSApp.activate before or via .simultaneousGesture / onAppear in the
   Settings content - choose one, state which). Keep openSettingsWindow() only as the macOS 13 fallback.
2. Append test menubar/test_menubar_files.py::test_settings_uses_settingslink: SteveCAM.swift contains "SettingsLink" inside an
   `#available(macOS 14` branch, and swiftc -typecheck is green.
AT-RISK: menubar/test_menubar_files.py (all), connector/test_pidstatus.py (all) - paste exit codes. Report swiftc build size. Then stop.
