#!/bin/bash
# Package the Stingray Explorer application for distribution

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/python-backend"
DIST_DIR="$PROJECT_ROOT/dist"

echo "Packaging Stingray Explorer..."

cd "$PROJECT_ROOT"

# Build the application first
"$SCRIPT_DIR/build.sh"

# Create a distribution package with Python backend
echo "Creating distribution package..."

# Create resources directory for Python backend
RESOURCES_DIR="$DIST_DIR/resources/python-backend"
mkdir -p "$RESOURCES_DIR"

# Copy Python backend files
cp -r "$BACKEND_DIR"/* "$RESOURCES_DIR/"

echo "Package created in $DIST_DIR"
echo ""
echo "Note: For production distribution, you'll need to:"
echo "1. Bundle Python with the application or require it as a dependency"
echo "2. Use electron-builder to create platform-specific installers"
echo "3. Sign the application for macOS and Windows"
