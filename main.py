#!/usr/bin/env python3
"""
Photogrammetry Studio — entry point.

Usage
-----
    python main.py

Requirements: see requirements.txt
Recommended Python: 3.12
"""
import sys
import os
from pathlib import Path

# Ensure the project root is on sys.path when launched from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from loguru import logger

from app.ui.main_window import MainWindow


def main() -> None:
    # Lightweight viewer mode: `<app> --view <model>` opens the model in the
    # interactive 3D viewer and exits.  The packaged app re-launches itself this
    # way so "View in 3D" never depends on the OS file association.
    if len(sys.argv) >= 3 and sys.argv[1] == "--view":
        from app.tools.view_model import main as view_main
        sys.exit(view_main(["view_model", sys.argv[2]]))

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

    # Persist logs (incl. RTSP drop / high-latency warnings) to a rotating file
    # so stream issues are diagnosable after the fact, even in the packaged app.
    log_dir = Path.home() / ".photogrammetry" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
            level="DEBUG",
            rotation="5 MB",
            retention="14 days",
            # NOTE: do NOT set enqueue=True here. loguru's enqueue spawns a
            # multiprocessing queue/resource-tracker, which in a PyInstaller
            # bundle (macOS "spawn") re-executes the .app and fork-bombs new
            # windows. loguru is already thread-safe for our QThread workers.
        )
        logger.info(f"Logging to {log_dir}")
    except OSError as exc:
        logger.warning(f"File logging disabled ({exc}); using stderr only")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    # Must be the first thing in a frozen app: lets any spawned multiprocessing
    # helper bail out instead of re-running main() and opening another window.
    import multiprocessing
    multiprocessing.freeze_support()
    main()
