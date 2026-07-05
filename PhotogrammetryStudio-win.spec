# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Photogrammetry Studio on Windows.

Build (from the project root, inside the venv):
    pyinstaller PhotogrammetryStudio-win.spec --noconfirm

Output:
    dist/PhotogrammetryStudio/PhotogrammetryStudio.exe   (portable onedir)

Notes
-----
* Reconstruction engines (RealityScan / Meshroom) are NOT bundled — they are
  large external tools the user installs once.  The app locates them at runtime.
* The in-app "View in 3D" viewer uses trimesh + pyglet, so scipy/pyglet/trimesh
  data must be collected (below).  The exe re-launches itself as `--view <model>`
  to open a model, so no OS file association is involved.
"""

from PyInstaller.utils.hooks import collect_data_files

BLOCK_CIPHER = None

# trimesh ships resource files (templates) it loads at runtime.  scipy and pyglet
# are handled by PyInstaller's own hooks, so we don't collect their submodules
# manually (that would drag in their entire test suites and bloat the build).
datas = []
datas += collect_data_files("trimesh")

hiddenimports = [
    "loguru",
    # trimesh imports these lazily; name them so the frozen build includes them.
    "scipy.sparse",
    "scipy.spatial",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Heavy optional deps we never use — keep the bundle lean.
        "pyvista",
        "pyvistaqt",
        "vtk",
        "vtkmodules",
        "matplotlib",
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
    name="PhotogrammetryStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed GUI app (no console window)
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
    name="PhotogrammetryStudio",
)
