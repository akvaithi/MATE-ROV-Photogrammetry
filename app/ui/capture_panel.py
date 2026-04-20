"""
CapturePanel — frame count, live quality gauges, capture controls,
and the thumbnail grid.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QSpinBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
)

from app.state import FrameRecord
from app.ui.widgets.quality_meter import QualityMeter
from app.ui.widgets.thumbnail_grid import ThumbnailGrid


class CapturePanel(QWidget):
    # Emitted when the user changes mode / settings
    capture_mode_changed = pyqtSignal(str)      # "auto" | "interval" | "manual"
    interval_changed = pyqtSignal(float)        # seconds
    start_capture_requested = pyqtSignal()
    stop_capture_requested = pyqtSignal()
    manual_capture_requested = pyqtSignal()
    export_pngs_requested = pyqtSignal()
    reconstruct_requested = pyqtSignal(bool)    # bool = dense

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._capture_running = False
        # Normalised subject bbox (x, y, w, h) from the framing detector, in [0, 1]
        self._framing_bbox: tuple[float, float, float, float] | None = None
        self._framing_value: float = 0.0
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Live preview ────────────────────────────────────────────────
        self._preview = QLabel("Waiting for stream…")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("background: #000; color: #888;")
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview.setMinimumSize(480, 270)
        root.addWidget(self._preview, stretch=1)

        # ── Mode selector ───────────────────────────────────────────────
        mode_box = QGroupBox("Capture Mode")
        mode_layout = QHBoxLayout(mode_box)

        self._mode_group = QButtonGroup(self)
        for label, key in [("Auto (stillness)", "auto"), ("Interval", "interval"), ("Manual", "manual")]:
            rb = QRadioButton(label)
            rb.setProperty("mode_key", key)
            self._mode_group.addButton(rb)
            mode_layout.addWidget(rb)
            if key == "auto":
                rb.setChecked(True)
        self._mode_group.buttonClicked.connect(self._on_mode_changed)

        # Interval spinbox (shown only in interval mode)
        self._interval_spin = QDoubleSpinBox()
        self._interval_spin.setRange(0.5, 300.0)
        self._interval_spin.setValue(5.0)
        self._interval_spin.setSuffix(" s")
        self._interval_spin.setEnabled(False)
        self._interval_spin.valueChanged.connect(
            lambda v: self.interval_changed.emit(v)
        )
        mode_layout.addWidget(QLabel("Every:"))
        mode_layout.addWidget(self._interval_spin)

        root.addWidget(mode_box)

        # ── Quality meters ───────────────────────────────────────────────
        quality_box = QGroupBox("Frame Quality (live)")
        quality_form = QVBoxLayout(quality_box)
        quality_form.setSpacing(2)

        self._motion_meter = QualityMeter("Motion", low=0.0, high=10.0)
        self._sharpness_meter = QualityMeter("Sharpness", low=0.0, high=300.0)
        self._novelty_meter = QualityMeter("Novelty", low=0.0, high=1.0)
        self._framing_meter = QualityMeter("Framing", low=0.0, high=1.0)
        self._reject_label = QLabel("Reject reason: —")
        self._reject_label.setStyleSheet("color: #ff6b6b; font-size: 11px;")

        quality_form.addWidget(self._motion_meter)
        quality_form.addWidget(self._sharpness_meter)
        quality_form.addWidget(self._novelty_meter)
        quality_form.addWidget(self._framing_meter)
        quality_form.addWidget(self._reject_label)
        root.addWidget(quality_box)

        # ── Frame counter ────────────────────────────────────────────────
        counter_row = QHBoxLayout()
        self._count_label = QLabel("Frames captured: 0")
        self._count_label.setStyleSheet("font-weight: bold;")
        counter_row.addWidget(self._count_label)
        counter_row.addStretch()
        root.addLayout(counter_row)

        # ── Control buttons ──────────────────────────────────────────────
        btn_row = QHBoxLayout()

        self._start_btn = QPushButton("Start Capture")
        self._start_btn.setStyleSheet("background: #2f9e44; color: white; font-weight: bold;")
        self._start_btn.clicked.connect(self._on_start_clicked)

        self._end_btn = QPushButton("End Capture")
        self._end_btn.setStyleSheet("background: #c92a2a; color: white; font-weight: bold;")
        self._end_btn.setEnabled(False)
        self._end_btn.clicked.connect(self._on_end_clicked)

        self._manual_btn = QPushButton("Capture Now")
        self._manual_btn.clicked.connect(self.manual_capture_requested)

        self._export_btn = QPushButton("Export PNGs…")
        self._export_btn.clicked.connect(self.export_pngs_requested)

        self._recon_btn = QPushButton("Reconstruct 3D")
        self._recon_btn.setStyleSheet("background: #1971c2; color: white; font-weight: bold;")
        self._recon_btn.clicked.connect(lambda: self.reconstruct_requested.emit(True))

        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._end_btn)
        btn_row.addWidget(self._manual_btn)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._recon_btn)
        root.addLayout(btn_row)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #444;")
        root.addWidget(line)

        # ── Thumbnail grid ───────────────────────────────────────────────
        self._thumbnails = ThumbnailGrid()
        root.addWidget(self._thumbnails, stretch=1)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def on_quality_updated(self, scores: dict) -> None:
        # Motion: lower is better — invert for the bar (full bar = no motion)
        motion = scores.get("motion", 0.0)
        self._motion_meter.set_value(motion)

        self._sharpness_meter.set_value(scores.get("sharpness", 0.0))
        self._novelty_meter.set_value(scores.get("novelty", 0.0))

        self._framing_value = float(scores.get("framing", 0.0))
        self._framing_meter.set_value(self._framing_value)
        self._framing_bbox = scores.get("framing_bbox")

        reason = scores.get("reject_reason")
        if reason:
            msgs = {
                "motion": "Rejected: too much motion",
                "blur": "Rejected: frame too blurry",
                "duplicate": "Rejected: too similar to saved frames",
                "framing": "Waiting for better framing (centre the object)",
            }
            self._reject_label.setText(msgs.get(reason, f"Rejected: {reason}"))
            self._reject_label.setStyleSheet("color: #ff6b6b; font-size: 11px;")
        else:
            self._reject_label.setText("Ready to capture")
            self._reject_label.setStyleSheet("color: #51cf66; font-size: 11px;")

    @pyqtSlot(object, object)
    def on_frame_captured(self, record: FrameRecord, rgb: np.ndarray) -> None:
        self._thumbnails.add_frame(record.index, rgb)
        self._count_label.setText(f"Frames captured: {record.index}")

    @pyqtSlot(object)
    def on_display_frame(self, rgb: np.ndarray) -> None:
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._draw_overlays(pixmap)
        self._preview.setPixmap(pixmap)

    def _draw_overlays(self, pixmap: QPixmap) -> None:
        """Paint rule-of-thirds grid and detected subject bbox on the preview."""
        pw, ph = pixmap.width(), pixmap.height()
        if pw <= 0 or ph <= 0:
            return
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rule-of-thirds grid: faint white lines at 1/3 and 2/3
        grid_pen = QPen(QColor(255, 255, 255, 110))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for i in (1, 2):
            x = int(pw * i / 3)
            y = int(ph * i / 3)
            painter.drawLine(x, 0, x, ph)
            painter.drawLine(0, y, pw, y)

        # Subject bbox from the framing detector
        if self._framing_bbox is not None:
            bx, by, bw, bh = self._framing_bbox
            rx, ry = int(bx * pw), int(by * ph)
            rw, rh = int(bw * pw), int(bh * ph)
            # Green when framing is good, red when poor
            if self._framing_value >= 0.55:
                color = QColor(81, 207, 102, 220)   # green
            elif self._framing_value >= 0.35:
                color = QColor(255, 212, 59, 220)   # yellow
            else:
                color = QColor(255, 107, 107, 220)  # red
            box_pen = QPen(color)
            box_pen.setWidth(2)
            painter.setPen(box_pen)
            painter.drawRect(rx, ry, rw, rh)

        painter.end()

    def on_capture_started(self) -> None:
        self._capture_running = True
        self._start_btn.setEnabled(False)
        self._end_btn.setEnabled(True)

    def on_capture_stopped(self) -> None:
        self._capture_running = False
        self._start_btn.setEnabled(True)
        self._end_btn.setEnabled(False)

    def clear_session(self) -> None:
        self._thumbnails.clear()
        self._count_label.setText("Frames captured: 0")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _on_start_clicked(self) -> None:
        self.on_capture_started()
        self.start_capture_requested.emit()

    def _on_end_clicked(self) -> None:
        self.on_capture_stopped()
        self.stop_capture_requested.emit()

    def _on_mode_changed(self, button) -> None:
        key = button.property("mode_key")
        self._interval_spin.setEnabled(key == "interval")
        self.capture_mode_changed.emit(key)
