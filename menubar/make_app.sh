#!/bin/bash
# Task MENUBAR: build ~/Applications/SteveCAM.app from menubar/SteveCAM.swift
# using swiftc. Build log: ~/.stevecam/app-build.log. Exits non-zero when
# the build fails. Does NOT touch the LaunchAgent (see install_agent.sh).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
APP="$HOME/Applications/SteveCAM.app"
BIN="$APP/Contents/MacOS/SteveCAM"
LOG="$HOME/.stevecam/app-build.log"

mkdir -p "$HOME/.stevecam"
{
    echo "== SteveCAM build $(date -u +%Y-%m-%dT%H:%M:%SZ) repo=$REPO"
    rm -rf "$APP"
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" || exit 1

    cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>studio.stevecam.menubar</string>
    <key>CFBundleName</key>
    <string>SteveCAM</string>
    <key>CFBundleExecutable</key>
    <string>SteveCAM</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>SCRepo</key>
    <string>$REPO</string>
    <key>CFBundleURLTypes</key>
    <array>
        <dict>
            <key>CFBundleURLName</key>
            <string>studio.stevecam.menubar</string>
            <key>CFBundleURLSchemes</key>
            <array>
                <string>stevecam</string>
            </array>
        </dict>
    </array>
</dict>
</plist>
PLIST

    /usr/bin/swiftc -O -swift-version 5 -parse-as-library \
        "$HERE/SteveCAM.swift" -o "$BIN"
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "swiftc failed (exit $rc)"
        rm -rf "$APP"
        exit $rc
    fi
    plutil -lint "$APP/Contents/Info.plist" || exit 1
    echo "built $APP"
} >> "$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
    echo "SteveCAM build FAILED (exit $rc); see $LOG" >&2
    exit $rc
fi
echo "built $APP (log: $LOG)"
