#!/usr/bin/env bash
# Cancels macOS Apple Silicon power management repeat wake schedule
# Run with: bash scripts/remove_pmset_wake.sh

set -euo pipefail

echo "=========================================================="
echo "Nova Autopilot - Cancel macOS Power Management Wake"
echo "=========================================================="

if [ "$EUID" -ne 0 ]; then
    echo "Running with sudo..."
    sudo pmset repeat cancel
else
    pmset repeat cancel
fi

echo ""
echo "Current repeat schedule after cancel:"
pmset -g sched || true
echo ""
echo "Repeat wake schedule successfully removed."
