#!/usr/bin/env bash
# ==============================================================================
# Nova Autopilot - Automated macOS Setup Script
# Configured for Apple Silicon M2 (MacBook Air / Pro)
# ==============================================================================

set -e

echo "🚀 Setting up Nova Autopilot on macOS..."

# Ensure Homebrew path is loaded
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v brew &> /dev/null; then
    echo "⚠️ Homebrew not detected. Please install Homebrew from https://brew.sh first:"
    echo '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

echo "📦 Installing system dependencies via Homebrew..."
brew install ffmpeg ollama cloudflared python@3.12 2>/dev/null || true

# Check if .env exists
if [ ! -f .env ]; then
    echo "📄 Creating .env from .env.example..."
    cp .env.example .env
fi

# Set up Python virtual environment
if [ ! -d ".venv" ]; then
    echo "🐍 Creating Python 3.12 virtual environment at .venv..."
    /opt/homebrew/bin/python3.12 -m venv .venv || python3 -m venv .venv
fi

echo "📦 Installing Python package requirements..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Start Ollama service if not running
if ! pgrep -x "ollama" > /dev/null; then
    echo "🤖 Starting Ollama service in background..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
fi

# Pull recommended 3B model
echo "🧠 Pulling Qwen 2.5 3B model (optimized for Hinglish on Apple M2)..."
ollama pull qwen2.5:3b

# Run Doctor
echo "🩺 Running Nova Doctor diagnostics..."
.venv/bin/python scripts/doctor.py

echo "✅ Nova Autopilot is ready!"
echo "👉 Run your first dry-run: .venv/bin/python -m nova dry-run"
echo "👉 Start the Web Review Studio: .venv/bin/python -m nova ui"
