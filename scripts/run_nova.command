#!/usr/bin/env bash
# ==============================================================================
# Nova Autopilot - Double-Clickable Desktop Launcher
# Prevents Mac sleep via caffeinate, executes studio run, opens Review UI
# ==============================================================================

# Change working directory to project root
cd "$(dirname "$0")/.." || exit 1

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "⚡ Launching Nova Autopilot Studio..."

# Verify Ollama service
if ! pgrep -x "ollama" > /dev/null; then
    echo "🤖 Starting Ollama local server..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
fi

# Run pipeline protected by caffeinate (prevents Mac sleep during video rendering)
echo "🎬 Running Studio Pipeline..."
caffeinate -i .venv/bin/python -m nova run

echo "🌐 Opening Review Queue in browser..."
open "http://127.0.0.1:8765/review"

echo "🖥️ Starting Review Web Studio server (Press Ctrl+C to stop)..."
.venv/bin/python -m nova ui
