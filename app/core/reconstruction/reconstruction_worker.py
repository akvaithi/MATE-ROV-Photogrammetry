"""
ReconstructionWorker — runs the selected reconstruction backend on a dedicated
QThread, emitting granular progress signals back to the UI.

The backend is chosen at runtime by `select_backend` (RealityKit on macOS,
RealityScan or Meshroom on Windows/Linux), so this worker is engine-agnostic:
every backend exposes the same `run(image_dir, output_path, progress_cb)` surface.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.config import AppConfig
from app.core.reconstruction.base import ReconstructionBackend
from app.core.reconstruction.registry import select_backend
from app.state import AppState


class ReconstructionWorker(QThread):
    """
    Signals
    -------
    stage_started(str)        Stage name that is beginning.
    stage_progress(str, int)  (stage_name, 0-100 percent).
    stage_done(str)           Stage name that finished.
    reconstruction_done(str)  Absolute path to the output model file.
    reconstruction_failed(str) Error message.
    log_message(str)          Line of log output for the UI log pane.
    """

    stage_started = pyqtSignal(str)
    stage_progress = pyqtSignal(str, int)
    stage_done = pyqtSignal(str)
    reconstruction_done = pyqtSignal(str)
    reconstruction_failed = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, config: AppConfig, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._state = app_state

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        if self._state.frames_dir is None or self._state.output_dir is None:
            self.reconstruction_failed.emit("No active session.")
            return

        # Select the backend up front so an unavailable engine fails clearly.
        try:
            backend: ReconstructionBackend = select_backend(self._config)
        except Exception as exc:
            self.reconstruction_failed.emit(str(exc))
            return

        # Intercept loguru output and relay to UI
        from loguru import logger
        sink_id = logger.add(
            lambda msg: self.log_message.emit(msg.strip()), level="DEBUG"
        )
        logger.info(f"Reconstruction backend: {backend.name}")

        try:
            output_path = self._run_backend(backend)
        except Exception as exc:
            logger.remove(sink_id)
            self.reconstruction_failed.emit(str(exc))
            return

        logger.remove(sink_id)

        if output_path and output_path.exists():
            self._state.reconstruction.output_model_path = str(output_path)
            self.reconstruction_done.emit(str(output_path))
        else:
            self.reconstruction_failed.emit(
                "Pipeline completed but output file was not found."
            )

    # ------------------------------------------------------------------
    # Backend
    # ------------------------------------------------------------------

    def _run_backend(self, backend: ReconstructionBackend) -> Path:
        assert self._state.frames_dir is not None
        assert self._state.output_dir is not None
        output_path = self._state.output_dir / f"model{backend.output_suffix}"
        return backend.run(
            image_dir=self._state.frames_dir,
            output_path=output_path,
            progress_cb=self._progress_cb,
        )

    # ------------------------------------------------------------------
    # Progress callback (called from pipeline, still on worker thread)
    # ------------------------------------------------------------------

    def _progress_cb(self, stage: str, percent: int) -> None:
        if percent == 0:
            self.stage_started.emit(stage)
        self.stage_progress.emit(stage, percent)
        if percent == 100:
            self.stage_done.emit(stage)
        # Update AppState
        self._state.reconstruction.current_stage = stage
        self._state.reconstruction.stage_progress = percent
        if percent == 100 and stage not in self._state.reconstruction.stages_completed:
            self._state.reconstruction.stages_completed.append(stage)
