"""
ReconstructionPanel — progress bars per pipeline stage, log viewer,
and an embedded cross-platform 3D model preview.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.core.reconstruction.registry import available_backend_names
from app.ui.widgets.model_viewer import ModelViewer


PIPELINE_STAGES = [
    "Feature Extraction",
    "Feature Matching",
    "Sparse Reconstruction (SfM)",
    "Dense Reconstruction (MVS)",
    "Meshing",
]


class ReconstructionPanel(QWidget):
    detail_changed = pyqtSignal(str)        # "preview" | "reduced" | "medium" | "full" | "raw"

    def __init__(self, config: Optional[AppConfig] = None, parent=None) -> None:
        super().__init__(parent)
        self._config = config or AppConfig()
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

        # Engine (auto-detected) + detail picker
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel(self._engine_label_text()))
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

        # ── Cross-platform model preview ────────────────────────────────
        self._viewer = ModelViewer()
        self._viewer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._viewer, stretch=1)

    def _engine_label_text(self) -> str:
        names = available_backend_names(self._config)
        if not names:
            return "Engine: none available — see setup (RealityScan / Meshroom / RealityKit)"
        return "Engine: auto — " + ", ".join(names)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def reset(self) -> None:
        for bar in self._bars.values():
            bar.setValue(0)
        self._log.clear()
        self._status_label.setText("Idle")
        self._output_label.clear()
        self._viewer.reset()

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
        self._viewer.load_model(output_path)

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
