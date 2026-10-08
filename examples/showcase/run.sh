#!/usr/bin/env bash
# ==============================================================================
# rsgi-wsrpc Showcase Launcher for Linux and macOS (Terminal)
# ==============================================================================
set -e

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo " 🚀 [rsgi-wsrpc] Starting Showcase Demo Server"
echo "============================================================"

# Locate Python 3.11+
PYTHON_BIN=""
for cmd in python3 python python3.12 python3.11; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON_BIN="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Error: Python 3.11+ not found. Please install Python from python.org."
    exit 1
fi

echo "✔ Found Python: $($PYTHON_BIN --version) ($PYTHON_BIN)"

# Check or create virtual environment
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙ Creating virtual environment in $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install dependencies from PyPI
echo "📦 Checking and installing dependencies from PyPI..."
python -m pip install --quiet --upgrade pip
python -m pip install --upgrade -r "$SCRIPT_DIR/requirements.txt"

echo "============================================================"
echo " 🌐 Server is starting..."
echo " Open in browser: http://127.0.0.1:8080"
echo "============================================================"

# Run server
exec python "$SCRIPT_DIR/server.py" "$@"
