#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PROJECT_DIR=""

if [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -d "$SCRIPT_DIR/src/blab" ]; then
    PROJECT_DIR="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/boundary-lab/pyproject.toml" ] && [ -d "$SCRIPT_DIR/boundary-lab/src/blab" ]; then
    PROJECT_DIR="$SCRIPT_DIR/boundary-lab"
else
    echo "ERROR: Could not find the Boundary Lab project folder."
    echo "Place this launcher inside the repository or directly above it."
    exit 1
fi

cd "$PROJECT_DIR"

BLAB_BIN="$PROJECT_DIR/.venv/bin/blab"

if [ ! -f "$BLAB_BIN" ]; then
    echo "ERROR: Boundary Lab is not installed in this checkout."
    echo "Run 01_install_update_boundary-lab.command (or 01_install_update_boundary-lab.sh) first."
    exit 1
fi

echo "============================================================"
echo "Boundary Lab launcher (macOS)"
echo "============================================================"
echo "Using project folder: $PROJECT_DIR"
echo "Starting Boundary Lab..."
echo ""

exec "$BLAB_BIN" gui "$@"
