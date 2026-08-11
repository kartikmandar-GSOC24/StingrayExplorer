#!/bin/bash
# Build the Stingray Explorer application

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Building Stingray Explorer..."

cd "$PROJECT_ROOT"

# Install npm dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install
fi

# Build the application
echo "Building Electron app..."
npm run build

echo "Build complete!"
echo "Output is in the dist/ directory."
