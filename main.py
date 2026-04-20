#!/usr/bin/env python3
"""
Photogrammetry Studio — entry point.

Usage
-----
    python main.py

Requirements: see requirements.txt
Recommended Python: 3.12 (open3d wheels available)
"""
import sys
import os

# Ensure the project root is on sys.path when launched from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from loguru import logger

from app.ui.main_window import MainWindow


def main() -> None:
    # High-DPI support (Qt 6 enables this by default, but be explicit)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Photogrammetry Studio")
    app.setOrganizationName("PhotogrammetryStudio")

    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}",
        level="INFO",
    )

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
