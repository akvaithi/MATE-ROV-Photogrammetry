#!/usr/bin/env bash
# Build Photogrammetry Studio.app for macOS.
#
# Usage:
#   ./build_app.sh           # clean build + zip
#   ./build_app.sh --no-zip  # build only, skip the release archive
#
# Requires the project venv at .venv with pyinstaller installed:
#   .venv/bin/pip install pyinstaller
set -euo pipefail

cd "$(dirname "$0")"

PY=.venv/bin/python
PYINST=.venv/bin/pyinstaller

[[ -x "$PY"    ]] || { echo "venv not found at .venv"; exit 1; }
[[ -x "$PYINST" ]] || { echo "pyinstaller not installed in venv"; exit 1; }

echo "==> Cleaning previous build"
rm -rf build dist

echo "==> Running PyInstaller"
"$PYINST" PhotogrammetryStudio.spec --noconfirm --clean

APP="dist/Photogrammetry Studio.app"
if [[ ! -d "$APP" ]]; then
    echo "Build failed: $APP not found"; exit 1
fi

echo "==> Bundle built: $APP"
echo "==> Size: $(du -sh "$APP" | cut -f1)"

if [[ "${1:-}" != "--no-zip" ]]; then
    ZIP="dist/PhotogrammetryStudio-macOS.zip"
    echo "==> Zipping bundle to $ZIP"
    rm -f "$ZIP"
    # ditto preserves symlinks, extended attributes, and resource forks.
    ditto -c -k --keepParent "$APP" "$ZIP"
    echo "==> Archive: $ZIP ($(du -sh "$ZIP" | cut -f1))"
fi

echo "==> Done."
