# SteveCAM menu-bar app (menubar/)

Menu-bar (status-bar) app for the STEVE connector plus a LaunchAgent that
keeps `connector/connector.py` running. Reads the connector's
`~/.stevecam/status.json` and `~/.stevecam/connector.pid`; the connector
refuses to start twice while another live `connector.py` holds the pidfile.

## Build the app

    menubar/make_app.sh

Compiles `SteveCAM.swift` with `/usr/bin/swiftc` into
`~/Applications/SteveCAM.app` (LSUIElement, URL scheme `stevecam`, repo path
in the `SCRepo` Info.plist key). Build log: `~/.stevecam/app-build.log`.
The script exits non-zero on a failed build. Launch it from Launchpad or
`open ~/Applications/SteveCAM.app`.

## Install / uninstall the LaunchAgent

    menubar/install_agent.sh      # render plist, plutil -lint, bootstrap
    menubar/uninstall_agent.sh    # bootout + remove the plist

`install_agent.sh` renders `com.stevecam.connector.plist.in` (`@REPO@`,
`@HOME@`) into `~/Library/LaunchAgents/com.stevecam.connector.plist` and
bootstraps it into `gui/<uid>` only when the label is not already loaded.
It refuses (with a message) while `~/.stevecam/connector.pid` names a live
`connector.py` that launchd did not start — stop it first. The agent runs
`/opt/homebrew/bin/python3 <repo>/connector/connector.py` from the repo
root, logging to `~/.stevecam/connector.log`, `RunAtLoad`, `KeepAlive
SuccessfulExit=false` (a clean exit 0 — e.g. a refusal or a SIGTERM stop —
is not respawned), `ThrottleInterval 10`. `ExitTimeOut 45` gives the
connector 45 s to shut down cleanly before launchd SIGKILLs it.

## Menu items

- **status line** — `Running, pid N`, `Working: <action> NN%` or `Stopped`
  (status.json + pidfile liveness, refreshed every 3 s)
- **main <commit>** — short git commit the connector reported
- **<connector name> · <fingerprint>** — the connector's own name + short
  fingerprint (never keys or pairing codes)
- **Last run** — action + UTC time of the newest run, when any
- **Start** — `launchctl kickstart gui/<uid>/com.stevecam.connector`
  (only when not already running)
- **Stop** — SIGTERM to the exact pidfile PID, after re-checking that its
  command line contains `connector.py`; waits up to 45 s. Never by name.
- **Restart** — Stop, then Start
- **Open log** — opens `~/.stevecam/connector.log`
- **Settings...** — *Start at login* rewrites `RunAtLoad` in the LaunchAgent
  plist (takes effect at next login); *Turn off after* (Never / 30 min /
  2 h / 8 h, saved in `~/.stevecam/menubar.json`) Stops the connector once
  status.json has said idle for that long
- **Quit SteveCAM** — quits the app only; the connector keeps running

URL scheme: `stevecam://start`, `stevecam://stop`, `stevecam://restart` do
the same as the menu items.

**Busy guard.** While the connector's status.json says a run is in progress
(`state` = `busy`), menu **Stop** / **Restart** first ask *"A run is in
progress. Stop anyway?"* (Stop / Cancel; Cancel does nothing), and the URL
actions `stevecam://stop` / `stevecam://restart` REFUSE instead — no signal
is sent and one timestamped line `refused stop: run in progress` (or
`refused restart: ...`) is appended to `~/.stevecam/menubar.log`. A URL with
`force=1` (`stevecam://stop?force=1`) stops without asking;
`stevecam://start` is unchanged and the *Turn off after* timer still only
acts while idle.

## Tests

    /Users/James/ai-sandbox/stevecam-ops/slot_m4.sh /opt/homebrew/bin/python3 \
        -m pytest -q -p no:cacheprovider menubar/test_menubar_files.py \
        connector/test_pidstatus.py
