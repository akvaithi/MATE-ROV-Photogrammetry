#!/usr/bin/env bash
# setup.sh — create a Python 3.12 virtual environment and install dependencies
set -e

PYTHON=${PYTHON:-python3.12}

# Check Python version
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: $PYTHON not found."
    echo "Install via Homebrew: brew install python@3.12"
    exit 1
fi

echo "Using Python: $($PYTHON --version)"

# Create venv
if [ ! -d ".venv" ]; then
    "$PYTHON" -m venv .venv
    echo "Created .venv"
fi

source .venv/bin/activate
pip install --upgrade pip wheel --quiet

# Install pip packages (reconstruction needs no Python deps — see below)
pip install -r requirements.txt --quiet

echo "pip packages installed."

# Reconstruction backend: Apple RealityKit / Object Capture (macOS only),
# compiled from the bundled Swift helper on first run. Needs Xcode CLT.
if [ "$(uname)" = "Darwin" ] && command -v swiftc &>/dev/null; then
    echo "RealityKit: ready (swiftc found)"
else
    echo "RealityKit: NOT available — requires macOS + Xcode Command Line Tools"
    echo "  Install with: xcode-select --install"
fi

echo ""
echo "Setup complete.  Run the app with:"
echo "  source .venv/bin/activate && python main.py"
