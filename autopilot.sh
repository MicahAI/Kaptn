#!/usr/bin/env bash
# Kaptn AutoPilot — quick launcher
# Usage: ./autopilot.sh [start|status|log]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'"
    exit 1
fi

source "$VENV_DIR/bin/activate"

kaptn "${@:-start}"
