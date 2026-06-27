"""
ReconstructionWorker — runs the RealityKit (Apple Object Capture) pipeline on a
dedicated QThread, emitting granular progress signals back to the UI.

RealityKit is the only backend: it produces the highest-quality meshes with no
extra tooling. It is macOS-only (Apple's PhotogrammetrySession), so on an
unsupported platform the worker fails fast with a clear message.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.config import AppConfig
from app.core.reconstruction.realitykit_pipeline import RealityKitPipeline
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

        if not RealityKitPipeline.is_available():
            self.reconstruction_failed.emit(
                "RealityKit (Apple Object Capture) is unavailable. It requires "
                "macOS 12+ with the Swift toolchain (run `xcode-select --install`)."
            )
            return

        # Intercept loguru output and relay to UI
        from loguru import logger
        sink_id = logger.add(
            lambda msg: self.log_message.emit(msg.strip()), level="DEBUG"
        )
        logger.info("Reconstruction backend: RealityKit (Apple Object Capture)")

        try:
            output_path = self._run_realitykit()
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

    def _run_realitykit(self) -> Path:
        assert self._state.frames_dir is not None
        assert self._state.output_dir is not None
        pipeline = RealityKitPipeline(detail=self._config.realitykit_detail)
        return pipeline.run(
            image_dir=self._state.frames_dir,
            output_path=self._state.output_dir / "model.usdz",
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
