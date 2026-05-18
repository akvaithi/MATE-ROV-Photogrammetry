# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Photogrammetry Studio.app

Build:
    pyinstaller PhotogrammetryStudio.spec --noconfirm

Output:
    dist/Photogrammetry Studio.app

Note: pyvista is optional at runtime; if not bundled, the panel falls back
to a placeholder label.  Including it bloats the binary by ~200 MB.
"""

from pathlib import Path

BLOCK_CIPHER = None
PROJECT_ROOT = Path(SPECPATH)

# Bundle the Swift helper source so the app can compile it on first run
# (requires Xcode Command Line Tools on the user's machine).
datas = [
    (
        str(PROJECT_ROOT / "app/core/reconstruction/realitykit_helper.swift"),
        "app/core/reconstruction",
    ),
]

hiddenimports = [
    "pycolmap",
    "loguru",
]

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=["pyinstaller_hooks/pyi_rth_cv2.py"],
    excludes=[
        # Heavy optional deps — keep the bundle lean.
        # The reconstruction panel handles their absence gracefully.
        "pyvista",
        "pyvistaqt",
        "vtk",
        "vtkmodules",
        "matplotlib",
        "scipy",
        "tkinter",
        "PyQt5",
        "PySide6",
        "PySide2",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=BLOCK_CIPHER)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Photogrammetry Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Photogrammetry Studio",
)

app = BUNDLE(
    coll,
    name="Photogrammetry Studio.app",
    icon=None,
    bundle_identifier="com.akvaithi.photogrammetrystudio",
    info_plist={
        "CFBundleName": "Photogrammetry Studio",
        "CFBundleDisplayName": "Photogrammetry Studio",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSCameraUsageDescription": "Used for live RTSP capture preview.",
        "NSLocalNetworkUsageDescription": "Used to connect to RTSP streams on the local network.",
    },
)
