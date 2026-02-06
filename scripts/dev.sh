#!/bin/bash
# Start the full development environment
#
# Note: The Python backend is spawned and managed by Electron, not this script.
# This ensures Electron can capture all backend stdout/stderr for the log panel.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Starting Stingray Explorer development environment..."

# Cleanup function - kills any orphaned backend processes on exit
cleanup() {
    echo ""
    echo "Cleaning up..."
    # Kill any orphaned python backend processes (safety measure)
    pkill -9 -f "${PROJECT_ROOT}/python-backend/main.py" 2>/dev/null || true
    echo "Cleanup complete."
    exit 0
}

# Set up traps for various signals
trap cleanup EXIT
trap cleanup SIGINT
trap cleanup SIGTERM
trap cleanup SIGHUP

# Start the Electron app (it will spawn and manage the Python backend)
echo "Starting Electron app..."
echo "Note: Python backend will be started by Electron for proper log capture."
cd "$PROJECT_ROOT"

# Use dev:linux on Linux to disable sandbox (avoids permission issues)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    npm run dev:linux
else
    npm run dev
fi

# Cleanup will be called automatically via trap
