#!/usr/bin/env bash
# ==============================================================================
# Nova Autopilot - Install Instagram / Multi-Platform Publish Queue Service
# Loads scripts/com.nova.autopilot.publish_queue.plist into macOS LaunchAgents
# Runs every 10 minutes (600s) to dispatch scheduled posts
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_NAME="com.nova.autopilot.publish_queue.plist"
SOURCE_PLIST="$SCRIPT_DIR/$PLIST_NAME"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$PLIST_NAME"

echo "=========================================================="
echo "Installing Nova Autopilot Publish Queue LaunchAgent"
echo "=========================================================="

mkdir -p "$TARGET_DIR"
mkdir -p "$PROJECT_ROOT/data"

# Copy plist to ~/Library/LaunchAgents
cp "$SOURCE_PLIST" "$TARGET_PLIST"

# Unload previous instance if loaded
launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" 2>/dev/null || true

# Load and bootstrap service
launchctl bootstrap "gui/$(id -u)" "$TARGET_PLIST"

echo "✅ Successfully installed and loaded: $TARGET_PLIST"
echo "The queue runner will execute every 10 minutes (600 seconds)."
echo "Logs: $PROJECT_ROOT/data/publish_queue_stdout.log"
echo "To uninstall anytime, run: bash scripts/uninstall_publish_queue.sh"
