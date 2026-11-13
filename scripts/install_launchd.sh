#!/usr/bin/env bash
# ==============================================================================
# Nova Autopilot - macOS launchd Daily Automation Manager
# Installs or uninstalls user LaunchAgent for daily scheduled production runs
# ==============================================================================

set -e

cd "$(dirname "$0")/.." || exit 1
PROJECT_DIR="$(pwd)"
PLIST_LABEL="com.nova.autopilot.daily"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$LAUNCH_AGENTS_DIR/$PLIST_LABEL.plist"

HOUR="${2:-10}"
MINUTE="${3:-00}"

usage() {
    echo "Usage: $0 [install|uninstall|status] [hour_24] [minute]"
    echo "Example: $0 install 10 30    # Schedule run at 10:30 AM daily"
    echo "Example: $0 uninstall        # Remove daily schedule"
    exit 1
}

case "$1" in
    install)
        mkdir -p "$LAUNCH_AGENTS_DIR"
        mkdir -p "$PROJECT_DIR/data/logs"

        echo "🗓️ Generating launchd plist scheduled for $(printf "%02d:%02d" "$HOUR" "$MINUTE")..."
        cat <<EOF > "$TARGET_PLIST"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-i</string>
        <string>$PROJECT_DIR/.venv/bin/python</string>
        <string>-m</string>
        <string>nova</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/data/logs/launchd_nova.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/data/logs/launchd_nova.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

        echo "⚙️ Loading LaunchAgent into macOS system..."
        launchctl unload "$TARGET_PLIST" 2>/dev/null || true
        launchctl load "$TARGET_PLIST"
        echo "✅ Installed successfully! Daily run scheduled at $(printf "%02d:%02d" "$HOUR" "$MINUTE")."
        echo "📝 Note: The Mac must be awake or set to wake via Energy Saver settings."
        ;;

    uninstall)
        echo "🛑 Unloading and removing LaunchAgent..."
        launchctl unload "$TARGET_PLIST" 2>/dev/null || true
        rm -f "$TARGET_PLIST"
        echo "✅ Daily schedule removed."
        ;;

    status)
        if launchctl list | grep "$PLIST_LABEL" > /dev/null; then
            echo "🟢 LaunchAgent is LOADED and ACTIVE."
            launchctl list "$PLIST_LABEL"
        else
            echo "⚪ LaunchAgent is NOT currently loaded."
        fi
        ;;

    *)
        usage
        ;;
esac
