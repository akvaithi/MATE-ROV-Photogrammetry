"""
StreamPanel — live RTSP preview with connection status and FPS counter.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class StreamPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Video canvas
        self._canvas = QLabel("No stream connected")
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setStyleSheet("background: #000; color: #888;")
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.setMinimumSize(640, 360)

        # Status row
        self._status_label = QLabel("Status: disconnected")
        self._status_label.setStyleSheet("color: #ff6b6b;")

        self._fps_label = QLabel("FPS: —")
        self._fps_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        status_row = QHBoxLayout()
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_row.addWidget(self._fps_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)
        layout.addLayout(status_row)

    # ------------------------------------------------------------------
    # Slots wired from StreamWorker signals
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def on_display_frame(self, rgb: np.ndarray) -> None:
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        # Scale to fill the canvas while keeping aspect ratio
        self._canvas.setPixmap(
            pixmap.scaled(
                self._canvas.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @pyqtSlot(str)
    def on_connection_status(self, status: str) -> None:
        self._status_label.setText(f"Status: {status}")
        colour = {
            "connected": "#51cf66",
            "reconnecting": "#ffd43b",
            "disconnected": "#ff6b6b",
        }.get(status, "#aaaaaa")
        self._status_label.setStyleSheet(f"color: {colour};")

    @pyqtSlot(float)
    def on_fps_updated(self, fps: float) -> None:
        self._fps_label.setText(f"FPS: {fps:.1f}")
