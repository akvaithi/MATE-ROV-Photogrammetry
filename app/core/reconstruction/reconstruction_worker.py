"""
ReconstructionWorker — runs the ColmapPipeline on a dedicated QThread,
emitting granular progress signals back to the UI.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.config import AppConfig
from app.core.reconstruction.colmap_pipeline import ColmapPipeline
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

    def __init__(
        self,
        config: AppConfig,
        app_state: AppState,
        dense: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._state = app_state
        self._dense = dense

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        if self._state.frames_dir is None or self._state.output_dir is None:
            self.reconstruction_failed.emit("No active session.")
            return

        # Intercept loguru output and relay to UI
        from loguru import logger
        sink_id = logger.add(
            lambda msg: self.log_message.emit(msg.strip()), level="DEBUG"
        )

        backend = self._resolve_backend()
        logger.info(f"Reconstruction backend: {backend}")

        try:
            if backend == "realitykit":
                output_path = self._run_realitykit()
            else:
                output_path = self._run_colmap()
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
    # Backend dispatch
    # ------------------------------------------------------------------

    def _resolve_backend(self) -> str:
        pref = getattr(self._config, "reconstruction_backend", "auto")
        if pref == "realitykit":
            return "realitykit"
        if pref == "colmap":
            return "colmap"
        # auto — prefer Apple's pipeline on macOS with Swift available
        return "realitykit" if RealityKitPipeline.is_available() else "colmap"

    def _run_realitykit(self) -> Path:
        assert self._state.frames_dir is not None
        assert self._state.output_dir is not None
        pipeline = RealityKitPipeline(detail=self._config.realitykit_detail)
        return pipeline.run(
            image_dir=self._state.frames_dir,
            output_path=self._state.output_dir / "model.usdz",
            progress_cb=self._progress_cb,
        )

    def _run_colmap(self) -> Path:
        assert self._state.frames_dir is not None
        assert self._state.colmap_dir is not None
        pipeline = ColmapPipeline(
            colmap_binary=self._config.colmap_binary,
            camera_model=self._config.colmap_camera_model,
            max_features=self._config.colmap_max_features,
        )
        return pipeline.run(
            image_dir=self._state.frames_dir,
            workspace=self._state.colmap_dir,
            progress_cb=self._progress_cb,
            dense=self._dense,
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
