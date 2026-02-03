#!/bin/bash
# Start the full development environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

BACKEND_PID=""
BACKEND_PORT=""

echo "Starting Stingray Explorer development environment..."

# Cleanup function - kills backend on any exit
cleanup() {
    echo ""
    echo "Cleaning up..."
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "Stopping backend (PID: $BACKEND_PID)..."
        # Try graceful shutdown first
        kill "$BACKEND_PID" 2>/dev/null
        # Wait up to 2 seconds for graceful shutdown
        for i in {1..4}; do
            sleep 0.5
            if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
                break
            fi
        done
        # Force kill if still running (e.g., stuck in I/O operation)
        if kill -0 "$BACKEND_PID" 2>/dev/null; then
            echo "Backend didn't stop gracefully, force killing..."
            kill -9 "$BACKEND_PID" 2>/dev/null
        fi
    fi
    # Also kill any orphaned python processes on our port range
    pkill -9 -f "python main.py" 2>/dev/null || true
    echo "Cleanup complete."
    exit 0
}

# Set up traps for various signals
trap cleanup EXIT
trap cleanup SIGINT
trap cleanup SIGTERM
trap cleanup SIGHUP

# Start the Python backend (auto-finds free port)
echo "Starting Python backend..."
cd "$PROJECT_ROOT/python-backend"

# Start backend and capture output to get the port
python main.py 2>&1 &
BACKEND_PID=$!

# Wait for backend to print the port (max 10 seconds)
echo "Waiting for backend to start..."
for i in {1..20}; do
    sleep 0.5
    # Check if process is still running
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "Error: Backend process died"
        exit 1
    fi
    # Try to get health check
    if curl -s "http://127.0.0.1:8765/health" >/dev/null 2>&1; then
        BACKEND_PORT=8765
        break
    fi
    # Try alternate ports
    for port in 8766 8767 8768 8769; do
        if curl -s "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
            BACKEND_PORT=$port
            break 2
        fi
    done
done

if [ -z "$BACKEND_PORT" ]; then
    echo "Error: Could not detect backend port"
    exit 1
fi

echo "Backend started on port $BACKEND_PORT (PID: $BACKEND_PID)"

# Export port for frontend
export VITE_BACKEND_PORT=$BACKEND_PORT

# Start the Electron app
echo "Starting Electron app..."
cd "$PROJECT_ROOT"

# Use dev:linux on Linux to disable sandbox (avoids permission issues)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    npm run dev:linux
else
    npm run dev
fi

# Cleanup will be called automatically via trap
