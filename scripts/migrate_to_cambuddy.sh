#!/bin/bash
# One-time cut-over from the old SteveCAM install to CAMBuddy on James's Mac.
# Run ONLY after the cambuddy-rename branch is merged and checked out, and
# with nothing running (menu Stop, no active run). It:
#   1. boots out and removes the old LaunchAgent com.stevecam.connector,
#   2. moves ~/.stevecam to ~/.cambuddy (key, config, tools, jobs kept),
#   3. removes ~/Applications/SteveCAM.app and the old stevecam:// handler,
#   4. runs menubar/make_app.sh and menubar/install_agent.sh.
# It never touches the repo folder or the GitHub remote.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
U="$(id -u)"
OLD=com.stevecam.connector
launchctl bootout "gui/$U/$OLD" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$OLD.plist"
if [ -d "$HOME/.stevecam" ] && [ ! -e "$HOME/.cambuddy" ]; then
    mv "$HOME/.stevecam" "$HOME/.cambuddy"
    echo "moved ~/.stevecam -> ~/.cambuddy"
fi
osascript -e 'quit app id "studio.stevecam.menubar"' 2>/dev/null || true
rm -rf "$HOME/Applications/SteveCAM.app"
"$REPO/menubar/make_app.sh"
"$REPO/menubar/install_agent.sh"
open "$HOME/Applications/CAMBuddy.app"
echo "done: CAMBuddy connector and menu-bar app installed"
