"""
SettingsDialog — configure RTSP URL, capture thresholds, output directory,
and COLMAP binary path.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._config = config
        self._build_ui()
        self._populate(config)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Stream tab ──────────────────────────────────────────────────
        stream_tab = QWidget()
        stream_form = QFormLayout(stream_tab)
        self._rtsp_url = QLineEdit()
        self._rtsp_url.setPlaceholderText("rtsp://192.168.1.100:8554/stream")
        stream_form.addRow("RTSP URL:", self._rtsp_url)
        self._reconnect_delay = QDoubleSpinBox()
        self._reconnect_delay.setRange(0.5, 30.0)
        self._reconnect_delay.setSuffix(" s")
        stream_form.addRow("Reconnect delay:", self._reconnect_delay)
        tabs.addTab(stream_tab, "Stream")

        # ── Capture tab ─────────────────────────────────────────────────
        capture_tab = QWidget()
        capture_form = QFormLayout(capture_tab)

        self._motion_thresh = QDoubleSpinBox()
        self._motion_thresh.setRange(0.1, 50.0)
        self._motion_thresh.setSingleStep(0.5)
        self._motion_thresh.setToolTip(
            "Mean pixel difference between frames. Lower = stricter motion rejection."
        )
        capture_form.addRow("Motion threshold:", self._motion_thresh)

        self._sharpness_thresh = QDoubleSpinBox()
        self._sharpness_thresh.setRange(1.0, 1000.0)
        self._sharpness_thresh.setSingleStep(5.0)
        self._sharpness_thresh.setToolTip(
            "Laplacian variance. Higher = require sharper images."
        )
        capture_form.addRow("Sharpness threshold:", self._sharpness_thresh)

        self._novelty_thresh = QDoubleSpinBox()
        self._novelty_thresh.setRange(0.01, 1.0)
        self._novelty_thresh.setSingleStep(0.01)
        self._novelty_thresh.setToolTip(
            "Bhattacharyya distance. Higher = require more visual difference from saved frames."
        )
        capture_form.addRow("Novelty threshold:", self._novelty_thresh)

        self._framing_thresh = QDoubleSpinBox()
        self._framing_thresh.setRange(0.0, 1.0)
        self._framing_thresh.setSingleStep(0.05)
        self._framing_thresh.setToolTip(
            "Saliency-based framing quality. Higher = require the subject to be "
            "well-centred and well-sized in the frame. 0 disables the gate."
        )
        capture_form.addRow("Framing threshold:", self._framing_thresh)

        self._interval_secs = QDoubleSpinBox()
        self._interval_secs.setRange(0.5, 300.0)
        self._interval_secs.setSuffix(" s")
        capture_form.addRow("Interval (seconds):", self._interval_secs)

        self._auto_min_interval = QDoubleSpinBox()
        self._auto_min_interval.setRange(0.0, 60.0)
        self._auto_min_interval.setSingleStep(0.25)
        self._auto_min_interval.setSuffix(" s")
        self._auto_min_interval.setToolTip(
            "Minimum time between auto-captures. Raise to slow the capture rate."
        )
        capture_form.addRow("Auto cooldown:", self._auto_min_interval)

        self._min_frames = QSpinBox()
        self._min_frames.setRange(5, 1000)
        capture_form.addRow("Min frames for reconstruction:", self._min_frames)

        self._max_frames = QSpinBox()
        self._max_frames.setRange(10, 5000)
        capture_form.addRow("Max frames:", self._max_frames)

        self._jpeg_quality = QSpinBox()
        self._jpeg_quality.setRange(50, 100)
        self._jpeg_quality.setSuffix(" %")
        capture_form.addRow("JPEG quality:", self._jpeg_quality)

        tabs.addTab(capture_tab, "Capture")

        # ── Output tab ──────────────────────────────────────────────────
        output_tab = QWidget()
        output_form = QFormLayout(output_tab)

        dir_row = QHBoxLayout()
        self._output_dir = QLineEdit()
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output_dir)
        dir_row.addWidget(self._output_dir)
        dir_row.addWidget(browse_btn)
        output_form.addRow("Output directory:", dir_row)

        self._colmap_binary = QLineEdit()
        self._colmap_binary.setPlaceholderText("colmap")
        output_form.addRow("COLMAP binary path:", self._colmap_binary)

        tabs.addTab(output_tab, "Output / COLMAP")

        layout.addWidget(tabs)

        # ── Buttons ─────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, cfg: AppConfig) -> None:
        self._rtsp_url.setText(cfg.rtsp_url)
        self._reconnect_delay.setValue(cfg.stream_reconnect_delay)
        self._motion_thresh.setValue(cfg.motion_threshold)
        self._sharpness_thresh.setValue(cfg.sharpness_threshold)
        self._novelty_thresh.setValue(cfg.novelty_threshold)
        self._framing_thresh.setValue(cfg.framing_threshold)
        self._interval_secs.setValue(cfg.interval_seconds)
        self._auto_min_interval.setValue(cfg.auto_min_interval_seconds)
        self._min_frames.setValue(cfg.min_frames)
        self._max_frames.setValue(cfg.max_frames)
        self._jpeg_quality.setValue(cfg.jpeg_quality)
        self._output_dir.setText(cfg.output_dir)
        self._colmap_binary.setText(cfg.colmap_binary)

    def get_config(self) -> AppConfig:
        """Return an updated AppConfig from current widget values.

        Starts from the original config so fields not exposed by the dialog
        (e.g. reconstruction_backend, realitykit_detail) are preserved.
        """
        from dataclasses import replace
        return replace(
            self._config,
            rtsp_url=self._rtsp_url.text().strip(),
            stream_reconnect_delay=self._reconnect_delay.value(),
            motion_threshold=self._motion_thresh.value(),
            sharpness_threshold=self._sharpness_thresh.value(),
            novelty_threshold=self._novelty_thresh.value(),
            framing_threshold=self._framing_thresh.value(),
            interval_seconds=self._interval_secs.value(),
            auto_min_interval_seconds=self._auto_min_interval.value(),
            min_frames=self._min_frames.value(),
            max_frames=self._max_frames.value(),
            jpeg_quality=self._jpeg_quality.value(),
            output_dir=self._output_dir.text().strip(),
            colmap_binary=self._colmap_binary.text().strip() or "colmap",
        )

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select output directory", self._output_dir.text()
        )
        if path:
            self._output_dir.setText(path)
