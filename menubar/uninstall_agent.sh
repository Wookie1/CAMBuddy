#!/bin/bash
# Task MENUBAR: uninstall the connector LaunchAgent: bootout gui/<uid> and
# remove ~/Library/LaunchAgents/com.stevecam.connector.plist. Does not stop
# a connector that is already running.
set -u

LABEL=com.stevecam.connector
OUT="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

if launchctl print "gui/$UID_NUM/$LABEL" > /dev/null 2>&1; then
    launchctl bootout "gui/$UID_NUM/$LABEL" \
        || { echo "launchctl bootout failed for $LABEL" >&2; exit 1; }
    echo "booted out $LABEL from gui/$UID_NUM"
else
    echo "not loaded: $LABEL"
fi

if [ -f "$OUT" ]; then
    rm -f "$OUT" || { echo "could not remove $OUT" >&2; exit 1; }
    echo "removed $OUT"
else
    echo "no plist at $OUT"
fi
