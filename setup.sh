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

# Install pip packages (excludes OpenMVS which is a Homebrew binary)
pip install \
    PyQt6 opencv-python "numpy<2" Pillow loguru scipy trimesh \
    pycolmap open3d pyvista pyvistaqt vtk \
    --quiet

echo "pip packages installed."

# Check for COLMAP binary (needed for SfM sparse stage)
if command -v colmap &>/dev/null; then
    echo "COLMAP: found ($(colmap --version 2>&1 | head -1))"
else
    echo "COLMAP: NOT found — install with: brew install colmap"
    echo "  (Required for SfM. Dense stage uses Open3D which is pip-installed.)"
fi

# Check for OpenMVS (optional — best dense quality on Apple Silicon)
if command -v DensifyPointCloud &>/dev/null || command -v OpenMVS_DensifyPointCloud &>/dev/null; then
    echo "OpenMVS: found (best dense backend)"
else
    echo "OpenMVS: not found (Open3D CPU fallback will be used for dense)"
    echo "  Optional install: brew install openmvs"
fi

echo ""
echo "Setup complete.  Run the app with:"
echo "  source .venv/bin/activate && python main.py"
