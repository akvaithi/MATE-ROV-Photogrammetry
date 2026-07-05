"""
Standalone 3D model viewer — opens a mesh in trimesh's interactive OpenGL window.

Run as a subprocess so it never blocks the Qt UI, and so viewing does NOT depend
on the OS file association for .glb/.obj/.stl (on Windows a fresh RealityScan
install grabs the .glb association and then rejects the file).  Because it runs
in the app's own venv (trimesh + pyglet), it works offline on any platform.

    python -m app.tools.view_model <path-to-model>

Supports .glb/.gltf/.obj/.stl/.ply.  Left-drag rotates, scroll zooms.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: python -m app.tools.view_model <model>\n")
        return 2
    path = Path(argv[1])
    if not path.exists():
        sys.stderr.write(f"model not found: {path}\n")
        return 3
    try:
        import trimesh

        scene = trimesh.load(str(path))
        # trimesh.Scene.show() opens an interactive pyglet window and blocks
        # until the user closes it.
        scene.show(caption=path.name)
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Failed to open {path}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
