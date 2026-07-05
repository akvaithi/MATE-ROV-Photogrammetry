"""
ModelViewer — cross-platform 3D-model preview + open/reveal controls.

Reconstruction backends emit different formats (RealityKit → .usdz on macOS;
RealityScan / Meshroom → .glb on Windows/Linux).  This widget shows a static
preview where it can render one cheaply and natively, and delegates interactive
(rotatable) viewing to the OS's own 3D viewer — which works offline, adds no heavy
3D dependency, and behaves identically to the app's previous Quick Look hand-off:

  * macOS   → Quick Look (`qlmanage`)   — thumbnail + interactive panel
  * Windows → default app (3D Viewer)   — interactive; thumbnail if renderable
  * Linux   → `xdg-open`                — interactive; thumbnail if renderable

"Reveal" opens the containing folder with the file selected.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QProcess, QTimer, pyqtSlot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _project_root() -> Path:
    # app/ui/widgets/model_viewer.py → project root is three parents up.
    return Path(__file__).resolve().parents[3]


class ModelViewer(QWidget):
    """Static preview + OS-native open/reveal for a reconstructed model."""

    _PLACEHOLDER = "3D preview appears here after reconstruction."

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model_path: str | None = None
        self._thumb_pixmap: QPixmap | None = None
        self._thumb_proc: QProcess | None = None
        self._thumb_expected: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(self._PLACEHOLDER)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #111; color: #555; min-height: 160px;")
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._label, stretch=1)

        btns = QHBoxLayout()
        self._open_btn = QPushButton(self._open_button_label())
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_default)
        self._reveal_btn = QPushButton(self._reveal_button_label())
        self._reveal_btn.setEnabled(False)
        self._reveal_btn.clicked.connect(self._reveal)
        btns.addWidget(self._open_btn)
        btns.addWidget(self._reveal_btn)
        btns.addStretch()
        root.addLayout(btns)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._model_path = None
        self._thumb_pixmap = None
        self._label.setPixmap(QPixmap())
        self._label.setText(self._PLACEHOLDER)
        self._open_btn.setEnabled(False)
        self._reveal_btn.setEnabled(False)

    def load_model(self, path: str) -> None:
        self._model_path = path
        self._open_btn.setEnabled(True)
        self._reveal_btn.setEnabled(True)
        self._render_thumbnail(path)

    # ------------------------------------------------------------------
    # Platform-specific button labels
    # ------------------------------------------------------------------

    @staticmethod
    def _open_button_label() -> str:
        if sys.platform == "darwin":
            return "Open in Quick Look"
        return "View in 3D"

    @staticmethod
    def _reveal_button_label() -> str:
        if sys.platform == "darwin":
            return "Reveal in Finder"
        if os.name == "nt":
            return "Reveal in Explorer"
        return "Show in folder"

    # ------------------------------------------------------------------
    # Thumbnail rendering
    # ------------------------------------------------------------------

    def _render_thumbnail(self, path: str) -> None:
        suffix = Path(path).suffix.lower()
        if sys.platform == "darwin" and suffix == ".usdz":
            self._render_quicklook_thumbnail(path)
        else:
            # No cheap, reliable offline mesh renderer for GLB/OBJ without a heavy
            # GL/3D dependency — show file info and lean on the OS viewer button.
            self._show_info_placeholder(path)

    def _render_quicklook_thumbnail(self, path: str) -> None:
        """macOS: render a static preview via `qlmanage -t` (async, timed out)."""
        self._thumb_pixmap = None
        self._label.setPixmap(QPixmap())
        self._label.setText("Rendering preview…")
        out_dir = tempfile.mkdtemp(prefix="usdz_thumb_")
        self._thumb_expected = str(Path(out_dir) / (Path(path).name + ".png"))

        proc = QProcess(self)
        self._thumb_proc = proc
        proc.finished.connect(lambda *_: self._on_thumb_done())
        QTimer.singleShot(20000, self._on_thumb_timeout)
        proc.start("qlmanage", ["-t", "-s", "1024", "-o", out_dir, path])

    def _show_info_placeholder(self, path: str) -> None:
        p = Path(path)
        size_mb = p.stat().st_size / (1024 * 1024) if p.exists() else 0.0
        stl = p.with_suffix(".stl")
        extra = "  •  model.stl also written (opens anywhere)" if stl.exists() else ""
        self._label.setPixmap(QPixmap())
        self._label.setText(
            f"✓ Model ready: {p.name}  ({size_mb:.1f} MB){extra}\n\n"
            f"Click “{self._open_button_label()}” to rotate it in an interactive window."
        )
        self._label.setStyleSheet("background: #111; color: #51cf66; min-height: 160px;")

    def _on_thumb_done(self) -> None:
        thumb = self._thumb_expected
        if thumb and Path(thumb).exists():
            self._thumb_pixmap = QPixmap(thumb)
            self._apply_thumbnail()
        else:
            self._label.setText(
                f"Preview thumbnail unavailable — use “{self._open_button_label()}”."
            )

    def _on_thumb_timeout(self) -> None:
        proc = self._thumb_proc
        if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
            proc.kill()
            self._label.setText(
                f"Preview is taking a while — use “{self._open_button_label()}”."
            )

    def _apply_thumbnail(self) -> None:
        if not self._thumb_pixmap or self._thumb_pixmap.isNull():
            return
        self._label.setPixmap(
            self._thumb_pixmap.scaled(
                self._label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_thumbnail()

    # ------------------------------------------------------------------
    # Open / Reveal (OS-aware)
    # ------------------------------------------------------------------

    def _open_default(self) -> None:
        if not self._model_path:
            return
        path = self._model_path
        suffix = Path(path).suffix.lower()

        # macOS USDZ → Quick Look (native, rotatable).
        if sys.platform == "darwin" and suffix == ".usdz":
            subprocess.Popen(
                ["qlmanage", "-p", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return

        # Mesh formats → our own trimesh viewer, run in this app's interpreter.
        # This deliberately bypasses the OS file association (on Windows a fresh
        # RealityScan install steals the .glb association and then rejects it).
        if suffix in (".glb", ".gltf", ".obj", ".stl", ".ply"):
            try:
                if getattr(sys, "frozen", False):
                    # Packaged: re-launch the bundled exe in --view mode.
                    subprocess.Popen([sys.executable, "--view", path])
                else:
                    # From source: run the viewer module from the project root.
                    subprocess.Popen(
                        [sys.executable, "-m", "app.tools.view_model", path],
                        cwd=str(_project_root()),
                    )
                return
            except Exception:
                pass  # fall through to the OS opener

        # Fallback: hand off to the OS default handler.
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            self._reveal()

    def _reveal(self) -> None:
        if not self._model_path:
            return
        path = self._model_path
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])
