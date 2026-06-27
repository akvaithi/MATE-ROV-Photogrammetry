"""
ReconstructionPanel — progress bars per pipeline stage, log viewer,
and an embedded 3D mesh preview.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.reconstruction.realitykit_pipeline import RealityKitPipeline


PIPELINE_STAGES = [
    "Feature Extraction",
    "Feature Matching",
    "Sparse Reconstruction (SfM)",
    "Dense Reconstruction (MVS)",
    "Meshing",
]


class ReconstructionPanel(QWidget):
    detail_changed = pyqtSignal(str)        # "preview" | "reduced" | "medium" | "full" | "raw"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._bars: dict[str, QProgressBar] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Top half: progress + controls ───────────────────────────────
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # Engine (RealityKit only) + detail picker
        engine_row = QHBoxLayout()
        rk_available = RealityKitPipeline.is_available()
        engine_lbl = QLabel(
            "Engine: RealityKit (Apple Object Capture)"
            + ("" if rk_available else "  — unavailable on this platform")
        )
        engine_lbl.setStyleSheet("color: #aaa;" if rk_available else "color: #ff6b6b;")
        engine_row.addWidget(engine_lbl)

        engine_row.addSpacing(12)
        engine_row.addWidget(QLabel("Detail:"))
        self._detail_combo = QComboBox()
        for label, key in [
            ("Preview",  "preview"),
            ("Reduced",  "reduced"),
            ("Medium",   "medium"),
            ("Full",     "full"),
            ("Raw",      "raw"),
        ]:
            self._detail_combo.addItem(label, key)
        self._detail_combo.setCurrentIndex(2)   # medium
        self._detail_combo.currentIndexChanged.connect(
            lambda _i: self.detail_changed.emit(self._detail_combo.currentData())
        )
        engine_row.addWidget(self._detail_combo)
        engine_row.addStretch()
        top_layout.addLayout(engine_row)

        # Progress bars
        stages_box = QGroupBox("Pipeline Progress")
        stages_layout = QVBoxLayout(stages_box)
        stages_layout.setSpacing(4)

        for stage in PIPELINE_STAGES:
            row = QHBoxLayout()
            lbl = QLabel(stage)
            lbl.setFixedWidth(240)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            row.addWidget(lbl)
            row.addWidget(bar)
            stages_layout.addLayout(row)
            self._bars[stage] = bar

        top_layout.addWidget(stages_box)

        # Status label
        self._status_label = QLabel("Idle")
        self._status_label.setStyleSheet("font-weight: bold; color: #aaa;")
        top_layout.addWidget(self._status_label)

        # Output path
        self._output_label = QLabel()
        self._output_label.setWordWrap(True)
        self._output_label.setStyleSheet("color: #51cf66;")
        top_layout.addWidget(self._output_label)

        splitter.addWidget(top_widget)

        # ── Bottom half: log pane ───────────────────────────────────────
        log_box = QGroupBox("Reconstruction Log")
        log_layout = QVBoxLayout(log_box)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "background: #0d0d0d; color: #ccc; font-family: monospace; font-size: 11px;"
        )
        log_layout.addWidget(self._log)
        splitter.addWidget(log_box)

        splitter.setSizes([300, 200])
        root.addWidget(splitter)

        # ── 3D viewer placeholder ───────────────────────────────────────
        self._viewer_label = QLabel("3D preview will appear here after reconstruction.")
        self._viewer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._viewer_label.setStyleSheet("background: #111; color: #555; min-height: 160px;")
        self._viewer_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._viewer_label, stretch=1)

        # Try to embed a pyvista viewer if available
        self._pyvista_plotter = None
        self._try_embed_pyvista(root)

    def _try_embed_pyvista(self, root: QVBoxLayout) -> None:
        try:
            import pyvista as pv
            from pyvistaqt import BackgroundPlotter
            self._pyvista_plotter = BackgroundPlotter(parent=self, show=False)
            self._pyvista_plotter.set_background("#111111")
            root.removeWidget(self._viewer_label)
            self._viewer_label.hide()
            root.addWidget(self._pyvista_plotter.interactor, stretch=1)
        except Exception:
            pass   # pyvista not installed — keep the placeholder label

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def reset(self) -> None:
        for bar in self._bars.values():
            bar.setValue(0)
        self._log.clear()
        self._status_label.setText("Idle")
        self._output_label.clear()

    def set_detail(self, detail: str) -> None:
        for i in range(self._detail_combo.count()):
            if self._detail_combo.itemData(i) == detail:
                self._detail_combo.setCurrentIndex(i)
                return

    # ------------------------------------------------------------------
    # Slots wired from ReconstructionWorker
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def on_stage_started(self, stage: str) -> None:
        self._status_label.setText(f"Running: {stage}…")
        self._status_label.setStyleSheet("font-weight: bold; color: #ffd43b;")

    @pyqtSlot(str, int)
    def on_stage_progress(self, stage: str, percent: int) -> None:
        # Match stage name prefix to handle minor variations
        for key, bar in self._bars.items():
            if stage.startswith(key) or key.startswith(stage.split("(")[0].strip()):
                bar.setValue(percent)
                break

    @pyqtSlot(str)
    def on_stage_done(self, stage: str) -> None:
        for key, bar in self._bars.items():
            if stage.startswith(key) or key.startswith(stage.split("(")[0].strip()):
                bar.setValue(100)
                break

    @pyqtSlot(str)
    def on_reconstruction_done(self, output_path: str) -> None:
        self._status_label.setText("Reconstruction complete!")
        self._status_label.setStyleSheet("font-weight: bold; color: #51cf66;")
        self._output_label.setText(f"Output: {output_path}")
        self._load_model(output_path)

    @pyqtSlot(str)
    def on_reconstruction_failed(self, error: str) -> None:
        self._status_label.setText(f"Failed: {error[:120]}")
        self._status_label.setStyleSheet("font-weight: bold; color: #ff6b6b;")
        self._log.append(f"[ERROR] {error}")

    @pyqtSlot(str)
    def on_log_message(self, msg: str) -> None:
        self._log.append(msg)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load_model(self, path: str) -> None:
        if self._pyvista_plotter is None:
            return
        try:
            import pyvista as pv
            mesh = pv.read(path)
            self._pyvista_plotter.clear()
            self._pyvista_plotter.add_mesh(mesh, color="tan", smooth_shading=True)
            self._pyvista_plotter.reset_camera()
        except Exception as exc:
            self._log.append(f"[3D viewer] Could not load model: {exc}")
