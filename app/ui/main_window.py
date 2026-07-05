"""
MainWindow — top-level QMainWindow.
Owns all workers (StreamWorker, CaptureEngine thread, ReconstructionWorker)
and wires them together with Qt signals.
"""
from __future__ import annotations

from pathlib import Path

from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStatusBar,
    QTabWidget,
    QWidget,
)
import cv2
from loguru import logger

from app.config import AppConfig
from app.core.capture_engine import CaptureEngine
from app.core.reconstruction.reconstruction_worker import ReconstructionWorker
from app.core.stream_worker import StreamWorker
from app.state import AppState, FrameRecord
from app.ui.capture_panel import CapturePanel
from app.ui.reconstruction_panel import ReconstructionPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.stream_panel import StreamPanel


class MainWindow(QMainWindow):
    # Cross-thread signals into the CaptureEngine (which lives on its own thread
    # and owns QTimers).  Emitting these gives Qt a *queued* call that runs on the
    # engine's thread — calling the engine's methods directly from the main thread
    # would touch those timers cross-thread ("Timers cannot be stopped from
    # another thread") and crash on shutdown.
    _engine_update_config = pyqtSignal(object)
    _engine_stop_capture = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Photogrammetry Studio")
        self.resize(1280, 800)
        self.setStyleSheet(_DARK_STYLE)

        # ── App state and config ─────────────────────────────────────────
        self._config = AppConfig.load(AppConfig.default_config_path())
        self._state = AppState()
        self._state.new_session(Path(self._config.output_dir))

        # ── Workers ──────────────────────────────────────────────────────
        self._stream_worker = StreamWorker(self._config)

        self._capture_engine = CaptureEngine(self._config, self._state)
        self._capture_thread = QThread(self)
        self._capture_engine.moveToThread(self._capture_thread)
        # Destroy the engine (and its QTimers) on its own thread when it stops.
        self._capture_thread.finished.connect(self._capture_engine.deleteLater)
        self._capture_thread.start()

        self._recon_worker: ReconstructionWorker | None = None

        # ── UI ────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._stream_panel = StreamPanel()
        self._capture_panel = CapturePanel()
        self._recon_panel = ReconstructionPanel(self._config)
        self._recon_panel.set_detail(self._config.reconstruction_detail)

        self._tabs.addTab(self._stream_panel, "Stream")
        self._tabs.addTab(self._capture_panel, "Capture")
        self._tabs.addTab(self._recon_panel, "Reconstruct")

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._conn_indicator = QLabel("●")
        self._conn_indicator.setStyleSheet("color: #ff6b6b;")
        self._status_bar.addPermanentWidget(self._conn_indicator)

        self._build_menu()
        self._wire_signals()

        # ── Start stream immediately ──────────────────────────────────────
        self._stream_worker.start()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")

        new_session_act = QAction("New Session", self)
        new_session_act.setShortcut("Ctrl+N")
        new_session_act.triggered.connect(self._new_session)
        file_menu.addAction(new_session_act)

        import_act = QAction("Import Images…", self)
        import_act.setShortcut("Ctrl+I")
        import_act.triggered.connect(self._import_images)
        file_menu.addAction(import_act)

        export_act = QAction("Export Model…", self)
        export_act.setShortcut("Ctrl+E")
        export_act.triggered.connect(self._export_model)
        file_menu.addAction(export_act)

        file_menu.addSeparator()

        settings_act = QAction("Settings…", self)
        settings_act.setShortcut("Ctrl+,")
        settings_act.triggered.connect(self._open_settings)
        file_menu.addAction(settings_act)

        file_menu.addSeparator()

        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(quit_act)

        capture_menu = menubar.addMenu("Capture")
        start_act = QAction("Start Capture", self)
        start_act.setShortcut("Space")
        start_act.triggered.connect(self._capture_panel.start_capture_requested)
        capture_menu.addAction(start_act)

        snap_act = QAction("Capture Now", self)
        snap_act.setShortcut("Ctrl+Return")
        snap_act.triggered.connect(self._capture_panel.manual_capture_requested)
        capture_menu.addAction(snap_act)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        # Stream → display (both the Stream tab and the Capture tab's preview)
        self._stream_worker.display_frame_ready.connect(
            self._stream_panel.on_display_frame
        )
        self._stream_worker.display_frame_ready.connect(
            self._capture_panel.on_display_frame
        )
        self._stream_worker.connection_status.connect(
            self._stream_panel.on_connection_status
        )
        self._stream_worker.connection_status.connect(self._on_connection_status)
        self._stream_worker.fps_updated.connect(self._stream_panel.on_fps_updated)
        self._stream_worker.stream_health.connect(self._stream_panel.on_stream_health)
        self._stream_worker.error.connect(self._on_stream_error)

        # Stream → capture engine (full-res frames)
        self._stream_worker.frame_ready.connect(self._capture_engine.on_new_frame)

        # Capture panel → engine
        self._capture_panel.start_capture_requested.connect(
            self._capture_engine.start_capture
        )
        self._capture_panel.stop_capture_requested.connect(
            self._capture_engine.stop_capture
        )
        self._capture_panel.manual_capture_requested.connect(
            self._capture_engine.manual_capture
        )
        self._capture_panel.capture_mode_changed.connect(self._on_mode_changed)
        self._capture_panel.interval_changed.connect(self._on_interval_changed)
        self._capture_panel.export_pngs_requested.connect(self._export_pngs)
        self._capture_panel.import_images_requested.connect(self._import_images)
        self._capture_panel.reconstruct_requested.connect(self._start_reconstruction)

        # Thread-safe (queued) calls into the capture engine on its own thread.
        self._engine_update_config.connect(self._capture_engine.update_config)
        self._engine_stop_capture.connect(self._capture_engine.stop_capture)

        # Engine → UI
        self._capture_engine.quality_updated.connect(
            self._capture_panel.on_quality_updated
        )
        self._capture_engine.frame_captured.connect(
            self._capture_panel.on_frame_captured
        )
        self._capture_engine.frame_captured.connect(self._on_frame_captured)
        self._capture_engine.status_message.connect(self._status_bar.showMessage)

        # Reconstruction panel → config
        self._recon_panel.detail_changed.connect(self._on_detail_changed)

    # ------------------------------------------------------------------
    # Slots / handlers
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def _on_connection_status(self, status: str) -> None:
        colours = {
            "connected": "#51cf66",
            "reconnecting": "#ffd43b",
            "disconnected": "#ff6b6b",
        }
        c = colours.get(status, "#aaa")
        self._conn_indicator.setStyleSheet(f"color: {c};")
        self._state.stream_connected = status == "connected"

    @pyqtSlot(str)
    def _on_stream_error(self, msg: str) -> None:
        self._status_bar.showMessage(f"Stream error: {msg}", 10000)
        logger.error(msg)

    @pyqtSlot(object, object)
    def _on_frame_captured(self, record, _rgb) -> None:
        self._status_bar.showMessage(
            f"Frame {record.index} saved  |  Total: {self._state.frame_count}"
        )

    @pyqtSlot(str)
    def _on_mode_changed(self, mode: str) -> None:
        self._config.capture_mode = mode
        self._engine_update_config.emit(self._config)

    @pyqtSlot(float)
    def _on_interval_changed(self, secs: float) -> None:
        self._config.interval_seconds = secs
        self._engine_update_config.emit(self._config)

    @pyqtSlot(str)
    def _on_detail_changed(self, detail: str) -> None:
        self._config.reconstruction_detail = detail
        self._config.save(AppConfig.default_config_path())

    @pyqtSlot()
    def _start_reconstruction(self) -> None:
        if self._state.frame_count < self._config.min_frames:
            QMessageBox.warning(
                self,
                "Not enough frames",
                f"At least {self._config.min_frames} frames are required "
                f"(currently {self._state.frame_count}).",
            )
            return

        if self._recon_worker and self._recon_worker.isRunning():
            QMessageBox.information(self, "Busy", "Reconstruction is already running.")
            return

        self._tabs.setCurrentWidget(self._recon_panel)
        self._recon_panel.reset()

        self._recon_worker = ReconstructionWorker(
            config=self._config,
            app_state=self._state,
        )
        self._recon_worker.stage_started.connect(self._recon_panel.on_stage_started)
        self._recon_worker.stage_progress.connect(self._recon_panel.on_stage_progress)
        self._recon_worker.stage_done.connect(self._recon_panel.on_stage_done)
        self._recon_worker.reconstruction_done.connect(
            self._recon_panel.on_reconstruction_done
        )
        self._recon_worker.reconstruction_failed.connect(
            self._recon_panel.on_reconstruction_failed
        )
        self._recon_worker.log_message.connect(self._recon_panel.on_log_message)
        self._recon_worker.start()
        self._status_bar.showMessage("Reconstruction started…")

    def _new_session(self) -> None:
        if self._state.capture_running:
            self._engine_stop_capture.emit()
        self._state.new_session(Path(self._config.output_dir))
        self._capture_panel.clear_session()
        self._capture_panel.on_capture_stopped()
        self._recon_panel.reset()
        self._status_bar.showMessage(f"New session: {self._state.session_id}")

    @pyqtSlot()
    def _import_images(self) -> None:
        """Copy existing images into the current session so they can be
        reconstructed without capturing from the stream — handy for testing."""
        if self._state.frames_dir is None:
            QMessageBox.information(self, "No session", "Start a session first.")
            return

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Import images into this session",
            self._config.output_dir,
            "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)",
        )
        if not files:
            return

        frames_dir = self._state.frames_dir
        frames_dir.mkdir(parents=True, exist_ok=True)
        start = self._state.frame_count

        progress = QProgressDialog("Importing images…", "Cancel", 0, len(files), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        import shutil
        imported = 0
        for i, src in enumerate(files):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            QApplication.processEvents()

            idx = start + imported + 1
            ext = Path(src).suffix.lower() or ".jpg"
            dest = frames_dir / f"frame_{idx:04d}{ext}"
            try:
                shutil.copy2(src, dest)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Import failed for {src}: {exc}")
                continue

            bgr = cv2.imread(str(dest))
            sharp = 0.0
            if bgr is not None:
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            record = FrameRecord(
                index=idx,
                filename=str(dest),
                timestamp=datetime.now().isoformat(),
                motion_score=0.0,
                sharpness_score=sharp,
                novelty_score=1.0,
                capture_mode="imported",
            )
            self._state.add_frame(record)
            if bgr is not None:
                self._capture_panel.on_frame_captured(
                    record, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                )
            imported += 1

        progress.setValue(len(files))
        self._status_bar.showMessage(
            f"Imported {imported} image(s). Total frames: {self._state.frame_count}"
        )
        QMessageBox.information(
            self,
            "Import complete",
            f"Imported {imported} image(s).\n"
            f"Total frames now: {self._state.frame_count}.\n\n"
            "Go to the Reconstruct tab and press Start.",
        )

    def _export_pngs(self) -> None:
        if self._state.frame_count == 0:
            QMessageBox.information(self, "No frames", "No captured frames to export.")
            return

        dest = QFileDialog.getExistingDirectory(
            self, "Export captured frames as PNGs to…", self._config.output_dir
        )
        if not dest:
            return
        dest_path = Path(dest)

        progress = QProgressDialog(
            "Exporting PNGs…", "Cancel", 0, self._state.frame_count, self
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        exported = 0
        failed: list[str] = []
        # PNG compression 1 = near-fastest, still fully lossless (max quality)
        encode_params = [cv2.IMWRITE_PNG_COMPRESSION, 1]

        for i, record in enumerate(self._state.frames):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            progress.setLabelText(f"Exporting {Path(record.filename).name}…")
            QApplication.processEvents()

            bgr = cv2.imread(record.filename)
            if bgr is None:
                failed.append(Path(record.filename).name)
                continue
            out_name = f"frame_{record.index:04d}.png"
            if cv2.imwrite(str(dest_path / out_name), bgr, encode_params):
                exported += 1
            else:
                failed.append(out_name)

        progress.setValue(self._state.frame_count)

        msg = f"Exported {exported} PNG file(s) to:\n{dest_path}"
        if failed:
            msg += f"\n\nFailed: {len(failed)} file(s)\n" + "\n".join(failed[:10])
            if len(failed) > 10:
                msg += f"\n…and {len(failed) - 10} more"
        QMessageBox.information(self, "Export complete", msg)
        self._status_bar.showMessage(f"Exported {exported} PNGs to {dest_path}", 5000)

    def _export_model(self) -> None:
        model_path = self._state.reconstruction.output_model_path
        if not model_path:
            QMessageBox.information(self, "No model", "No reconstruction output yet.")
            return
        dest = QFileDialog.getExistingDirectory(self, "Export model to…")
        if dest:
            src = Path(model_path).parent
            import shutil as _shutil
            _shutil.copytree(src, Path(dest) / src.name, dirs_exist_ok=True)
            self._status_bar.showMessage(f"Exported to {dest}")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            new_config = dlg.get_config()
            self._config = new_config
            self._config.save(AppConfig.default_config_path())
            # Hot-update workers
            self._stream_worker.update_config(new_config)
            self._engine_update_config.emit(new_config)
            self._status_bar.showMessage("Settings saved.", 3000)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._stream_worker.stop()
        self._stream_worker.wait(3000)

        # Stop the engine *on its own thread* (queued), then shut the thread's
        # event loop down.  The queued stop is processed before quit(), so the
        # QTimers are stopped by the thread that owns them — no cross-thread
        # timer teardown crash.
        self._engine_stop_capture.emit()
        self._capture_thread.quit()
        self._capture_thread.wait(3000)

        if self._recon_worker and self._recon_worker.isRunning():
            self._recon_worker.terminate()
            self._recon_worker.wait(5000)

        self._config.save(AppConfig.default_config_path())
        event.accept()


# ---------------------------------------------------------------------------
# Dark theme stylesheet
# ---------------------------------------------------------------------------

_DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #333;
}
QTabBar::tab {
    background: #252540;
    color: #aaa;
    padding: 6px 18px;
    border: 1px solid #333;
    border-bottom: none;
}
QTabBar::tab:selected {
    background: #1a1a2e;
    color: #fff;
}
QGroupBox {
    border: 1px solid #333;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: #aaa;
}
QPushButton {
    background: #252540;
    color: #ddd;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 4px 12px;
}
QPushButton:hover {
    background: #333360;
}
QPushButton:pressed {
    background: #1a1a2e;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #111128;
    color: #ddd;
    border: 1px solid #444;
    border-radius: 3px;
    padding: 2px 4px;
}
QProgressBar {
    background: #111128;
    border: 1px solid #444;
    border-radius: 3px;
    text-align: center;
    color: white;
}
QProgressBar::chunk {
    background: #1971c2;
    border-radius: 2px;
}
QScrollBar:vertical {
    background: #111128;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #444;
    border-radius: 5px;
}
QStatusBar {
    background: #111128;
    color: #aaa;
}
QMenuBar {
    background: #111128;
    color: #ddd;
}
QMenuBar::item:selected {
    background: #333360;
}
QMenu {
    background: #1a1a2e;
    border: 1px solid #444;
}
QMenu::item:selected {
    background: #333360;
}
"""
