"""
CaptureEngine — lives on a worker QThread (via moveToThread), driven by two
QTimers:
  - analysis_timer  : fires every ~33 ms (30 Hz) to evaluate quality gates
  - interval_timer  : fires every N seconds for interval-mode captures
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from app.config import AppConfig
from app.core.frame_store import FrameStore
from app.core.quality_assessor import is_capturable
from app.state import AppState, FrameRecord


class CaptureEngine(QObject):
    """
    Signals
    -------
    frame_captured(FrameRecord, np.ndarray)
        A frame was accepted and saved.  np.ndarray is RGB for thumbnail display.
    quality_updated(dict)
        Live quality scores for each analysis tick — drives the UI gauges.
    status_message(str)
        Human-readable status for the status bar.
    """

    frame_captured = pyqtSignal(object, object)   # FrameRecord, RGB ndarray
    quality_updated = pyqtSignal(dict)
    status_message = pyqtSignal(str)

    def __init__(self, config: AppConfig, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._state = app_state

        self._store: FrameStore | None = None

        # Latest full-resolution BGR frame from StreamWorker
        self._latest_bgr: np.ndarray | None = None
        self._prev_gray: np.ndarray | None = None

        # Rolling buffer for interval mode: (bgr, scores)
        self._rolling: deque[tuple[np.ndarray, dict]] = deque(
            maxlen=config.rolling_buffer_max
        )

        # Capture flags
        self._auto_enabled = False
        self._interval_enabled = False
        self._capture_pending = False   # set True by manual_capture()
        self._last_capture_ts = 0.0     # wall-clock time of last auto-capture (cooldown)

        # Timers (created here; started/stopped via slots)
        self._analysis_timer = QTimer(self)
        self._analysis_timer.setInterval(1000 // max(1, config.analysis_fps))
        self._analysis_timer.timeout.connect(self._on_analysis_tick)

        self._interval_timer = QTimer(self)
        self._interval_timer.setInterval(int(config.interval_seconds * 1000))
        self._interval_timer.timeout.connect(self._on_interval_tick)

    # ------------------------------------------------------------------
    # Public slots — called from the main thread via Qt connections
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def on_new_frame(self, bgr: np.ndarray) -> None:
        """Receive the latest full-res BGR frame from StreamWorker."""
        self._latest_bgr = bgr

    @pyqtSlot()
    def start_capture(self) -> None:
        if self._state.frames_dir is None:
            self.status_message.emit("No active session — cannot start capture.")
            return
        self._store = FrameStore(self._state.frames_dir, self._config.jpeg_quality)
        self._auto_enabled = (self._config.capture_mode == "auto")
        self._interval_enabled = (self._config.capture_mode == "interval")
        self._last_capture_ts = 0.0
        self._analysis_timer.start()
        if self._interval_enabled:
            self._interval_timer.setInterval(int(self._config.interval_seconds * 1000))
            self._interval_timer.start()
        self.status_message.emit("Capture started.")

    @pyqtSlot()
    def stop_capture(self) -> None:
        self._analysis_timer.stop()
        self._interval_timer.stop()
        self._auto_enabled = False
        self._interval_enabled = False
        self.status_message.emit("Capture stopped.")

    @pyqtSlot()
    def manual_capture(self) -> None:
        """Trigger a single capture on the next analysis tick."""
        self._capture_pending = True

    @pyqtSlot(object)
    def update_config(self, config: AppConfig) -> None:
        self._config = config
        self._analysis_timer.setInterval(1000 // max(1, config.analysis_fps))
        self._interval_timer.setInterval(int(config.interval_seconds * 1000))
        if self._store:
            self._store.jpeg_quality = config.jpeg_quality

    # ------------------------------------------------------------------
    # Timer callbacks (run on worker thread event loop)
    # ------------------------------------------------------------------

    def _on_analysis_tick(self) -> None:
        bgr = self._latest_bgr
        if bgr is None:
            return

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        if self._prev_gray is None:
            # First frame — can't compute motion yet; just store and wait
            self._prev_gray = gray
            return

        # Run quality gates
        hists = self._store.hists if self._store else []
        accept, scores = is_capturable(
            prev_gray=self._prev_gray,
            curr_gray=gray,
            curr_bgr=bgr,
            saved_hists=hists,
            motion_threshold=self._config.motion_threshold,
            sharpness_threshold=self._config.sharpness_threshold,
            novelty_threshold=self._config.novelty_threshold,
            framing_threshold=self._config.framing_threshold,
        )

        self.quality_updated.emit(scores)

        # Always push to rolling buffer so interval mode can pick the best frame
        if self._interval_enabled:
            self._rolling.append((bgr.copy(), scores))

        # Auto-capture (with cooldown to cap the capture rate)
        if accept and self._auto_enabled and self._store:
            now = time.monotonic()
            cooldown = max(0.0, self._config.auto_min_interval_seconds)
            if (
                self._state.frame_count < self._config.max_frames
                and now - self._last_capture_ts >= cooldown
            ):
                self._do_capture(bgr, scores, "auto")
                self._last_capture_ts = now

        # Manual capture (ignores quality gates — user decides)
        if self._capture_pending and self._store:
            self._capture_pending = False
            self._do_capture(bgr, scores, "manual")

        self._prev_gray = gray

    def _on_interval_tick(self) -> None:
        if not self._store or not self._rolling:
            return
        if self._state.frame_count >= self._config.max_frames:
            return
        # Pick the sharpest frame from the rolling buffer
        best_bgr, best_scores = max(
            self._rolling, key=lambda item: item[1].get("sharpness", 0.0)
        )
        self._rolling.clear()
        self._do_capture(best_bgr, best_scores, "interval")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _do_capture(self, bgr: np.ndarray, scores: dict, mode: str) -> None:
        assert self._store is not None
        record = self._store.save_frame(bgr, scores, mode)
        self._state.add_frame(record)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.frame_captured.emit(record, rgb)
        self.status_message.emit(
            f"Captured frame {record.index} "
            f"(sharpness={scores.get('sharpness', 0):.0f}, mode={mode})"
        )
