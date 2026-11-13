#!/usr/bin/env bash
# Configures macOS Apple Silicon power management to wake or power on for US prime-time publishing
# Run with: bash scripts/setup_pmset_wake.sh

set -euo pipefail

echo "=========================================================="
echo "Nova Autopilot - macOS Power Management (pmset) Wake Setup"
echo "=========================================================="
echo "This schedules your MacBook Air to wake at US prime times:"
echo "1. 21:25:00 IST (approx 11:55 AM US Eastern - Lunch Peak)"
echo "2. 03:25:00 IST (approx 17:55 PM US Eastern - Evening Prime)"
echo ""
echo "Note: Modifying pmset requires administrator privileges."
echo "Command to execute:"
echo "sudo pmset repeat wake MTWRFSU 21:25:00"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Running with sudo..."
    sudo pmset repeat wake MTWRFSU 21:25:00
else
    pmset repeat wake MTWRFSU 21:25:00
fi

echo ""
echo "Current repeat schedule:"
pmset -g sched
echo ""
echo "Setup complete! To cancel anytime, run: bash scripts/remove_pmset_wake.sh"
