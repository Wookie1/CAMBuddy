#!/bin/bash
# Task MENUBAR: install the connector LaunchAgent. Renders
# menubar/com.cambuddy.connector.plist.in into
# ~/Library/LaunchAgents/com.cambuddy.connector.plist, lints it with plutil
# and bootstraps it into gui/<uid> - only if the label is not already
# loaded. Refuses if connector.pid names a live connector.py that launchd
# did not start (stop it first, e.g. from the menu-bar app).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
TPL="$HERE/com.cambuddy.connector.plist.in"
LABEL=com.cambuddy.connector
OUT="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

[ -f "$TPL" ] || { echo "template missing: $TPL" >&2; exit 1; }

# Refuse while a manually started (non-launchd) connector is running.
PIDFILE="$HOME/.cambuddy/connector.pid"
if [ -f "$PIDFILE" ]; then
    PID="$(tr -dc '0-9' < "$PIDFILE")"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null \
       && ps -o command= -p "$PID" 2>/dev/null | grep -q "connector\.py"; then
        PARENT="$(ps -o ppid= -p "$PID" 2>/dev/null | tr -d '[:space:]')"
        if [ "$PARENT" != "1" ]; then
            echo "connector pid $PID is running but was not started by" \
                 "launchd (parent $PARENT);" >&2
            echo "stop it first (CAMBuddy menu: Stop) and run this script" \
                 "again." >&2
            exit 1
        fi
    fi
fi

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|@REPO@|$REPO|g" -e "s|@HOME@|$HOME|g" "$TPL" > "$OUT" \
    || { echo "could not render $OUT" >&2; exit 1; }
plutil -lint "$OUT" > /dev/null \
    || { echo "rendered plist failed plutil -lint: $OUT" >&2; exit 1; }

if launchctl print "gui/$UID_NUM/$LABEL" > /dev/null 2>&1; then
    echo "already loaded: $LABEL (plist updated; reload at next login)"
else
    launchctl bootstrap "gui/$UID_NUM" "$OUT" \
        || { echo "launchctl bootstrap failed for $OUT" >&2; exit 1; }
    echo "loaded $LABEL into gui/$UID_NUM"
fi
echo "installed $OUT"
