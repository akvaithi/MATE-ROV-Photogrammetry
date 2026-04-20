"""
ThumbnailGrid — a scrollable grid of captured frame thumbnails.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QGridLayout,
)


THUMB_W = 120
THUMB_H = 90


class ThumbnailItem(QLabel):
    clicked = pyqtSignal(int)   # frame index

    def __init__(self, index: int, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self._index = index
        self.setPixmap(pixmap.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio))
        self.setFixedSize(THUMB_W, THUMB_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Frame {index}")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "border: 1px solid #444; background: #1e1e1e;"
        )

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._index)


class ThumbnailGrid(QWidget):
    """
    Scrollable grid of frame thumbnails.  Items are added with add_frame().
    """

    frame_selected = pyqtSignal(int)   # frame index

    COLS = 5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[ThumbnailItem] = []

        self._grid = QGridLayout()
        self._grid.setSpacing(4)
        self._grid.setContentsMargins(4, 4, 4, 4)

        container = QWidget()
        container.setLayout(self._grid)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)

    def add_frame(self, index: int, rgb: np.ndarray) -> None:
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        item = ThumbnailItem(index, pixmap)
        item.clicked.connect(self.frame_selected)
        row, col = divmod(len(self._items), self.COLS)
        self._grid.addWidget(item, row, col)
        self._items.append(item)
        # Auto-scroll to bottom
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        )

    def clear(self) -> None:
        for item in self._items:
            self._grid.removeWidget(item)
            item.deleteLater()
        self._items.clear()
