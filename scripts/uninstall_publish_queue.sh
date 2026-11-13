#!/usr/bin/env bash
# ==============================================================================
# Nova Autopilot - Uninstall Instagram / Multi-Platform Publish Queue Service
# Unloads scripts/com.nova.autopilot.publish_queue.plist from macOS LaunchAgents
# ==============================================================================

set -euo pipefail

PLIST_NAME="com.nova.autopilot.publish_queue.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$PLIST_NAME"

echo "=========================================================="
echo "Uninstalling Nova Autopilot Publish Queue LaunchAgent"
echo "=========================================================="

if [ -f "$TARGET_PLIST" ]; then
    launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" 2>/dev/null || true
    rm -f "$TARGET_PLIST"
    echo "✅ Successfully unloaded and removed: $TARGET_PLIST"
else
    echo "ℹ️ Service is not currently installed at $TARGET_PLIST"
fi
