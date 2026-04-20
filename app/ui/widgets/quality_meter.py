"""
QualityMeter — a custom widget that displays a labelled value bar with
colour-coded fill (red → yellow → green based on thresholds).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget, QSizePolicy


class QualityMeter(QWidget):
    """
    A horizontal bar gauge that shows a normalised value (0.0 – 1.0).

    Usage
    -----
    meter = QualityMeter("Sharpness", low=0.0, high=1.0)
    meter.set_value(0.73)
    """

    def __init__(
        self,
        label: str,
        low: float = 0.0,
        high: float = 1.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._low = low
        self._high = high
        self._value: float = 0.0
        self._normalised: float = 0.0
        self.setMinimumHeight(22)
        self.setMaximumHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float) -> None:
        self._value = value
        span = self._high - self._low
        self._normalised = max(0.0, min(1.0, (value - self._low) / span if span else 0.0))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        bar_x = 90
        bar_w = rect.width() - bar_x - 4
        bar_h = rect.height() - 6
        bar_y = 3

        # Background
        p.fillRect(bar_x, bar_y, bar_w, bar_h, QColor("#2b2b2b"))

        # Fill colour: red → yellow → green
        n = self._normalised
        if n < 0.5:
            r, g = 220, int(220 * (n / 0.5))
        else:
            r, g = int(220 * (1 - (n - 0.5) / 0.5)), 220
        fill_color = QColor(r, g, 60)
        fill_w = int(bar_w * n)
        if fill_w > 0:
            p.fillRect(bar_x, bar_y, fill_w, bar_h, fill_color)

        # Border
        p.setPen(QPen(QColor("#555555"), 1))
        p.drawRect(bar_x, bar_y, bar_w - 1, bar_h - 1)

        # Label
        p.setPen(Qt.GlobalColor.white)
        p.drawText(0, 0, bar_x - 4, rect.height(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._label)

        # Value text
        p.setPen(Qt.GlobalColor.white)
        p.drawText(
            bar_x + fill_w + 4, bar_y, bar_w - fill_w - 8, bar_h,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{self._value:.1f}",
        )
