"""
StreamWorker — runs on its own QThread, decodes RTSP frames, emits signals.
The main thread must never call cv2.VideoCapture directly.
"""
from __future__ import annotations

import time

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from app.config import AppConfig
from app.core.stream_health import StreamHealthMonitor


class StreamWorker(QThread):
    """
    Continuously reads frames from an RTSP stream (or any URL OpenCV accepts).

    Signals
    -------
    frame_ready(np.ndarray)
        Full-resolution BGR frame, emitted at native stream rate.
        The CaptureEngine connects here for quality analysis.
    display_frame_ready(np.ndarray)
        RGB frame downsampled to at most 854×480, for the preview QLabel.
        Keeps the UI responsive even for high-res streams.
    connection_status(str)
        Human-readable status string: "connected", "reconnecting", "disconnected".
    fps_updated(float)
        Current decode FPS, updated every second.
    error(str)
        Fatal error message (e.g. bad URL that never connects).
    stream_health(object)
        StreamStats snapshot (drops, reconnects, stalls, latency) for the UI.
        Backed by StreamHealthMonitor, which also logs and persists events.
    """

    frame_ready = pyqtSignal(object)           # np.ndarray full-res BGR
    display_frame_ready = pyqtSignal(object)   # np.ndarray display-res RGB
    connection_status = pyqtSignal(str)
    fps_updated = pyqtSignal(float)
    error = pyqtSignal(str)
    stream_health = pyqtSignal(object)         # StreamStats

    # Maximum width for the display preview (height is computed to keep AR)
    DISPLAY_MAX_WIDTH = 854

    # Give up (emit a fatal error) after this many consecutive failed opens
    MAX_OPEN_ATTEMPTS = 5

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._stop_flag = False
        self._cap: cv2.VideoCapture | None = None
        self._monitor = StreamHealthMonitor(
            latency_warn_ms=config.stream_latency_warn_ms,
            write_log=config.stream_health_log,
        )

    def _emit_health(self) -> None:
        self.stream_health.emit(self._monitor.snapshot())

    # ------------------------------------------------------------------
    # Public control API (called from main thread)
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._stop_flag = True

    def update_config(self, config: AppConfig) -> None:
        """Hot-swap config; will take effect on the next reconnect."""
        self._config = config

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._stop_flag = False
        open_attempts = 0
        frame_count = 0
        fps_timer_start = time.monotonic()

        while not self._stop_flag:
            # --- Open / reopen the capture ---
            if self._cap is None or not self._cap.isOpened():
                open_attempts += 1
                self.connection_status.emit("reconnecting")
                self._monitor.on_connect_attempt(open_attempts)
                self._cap = self._open_capture(self._config.rtsp_url)
                if self._cap is None:
                    self._monitor.on_open_failed(open_attempts)
                    if open_attempts >= self.MAX_OPEN_ATTEMPTS:
                        self._monitor.on_fatal(
                            f"Cannot connect to {self._config.rtsp_url} after "
                            f"{open_attempts} attempts."
                        )
                        self.error.emit(
                            f"Cannot connect to {self._config.rtsp_url} after "
                            f"{open_attempts} attempts."
                        )
                    self._emit_health()
                    self.msleep(int(self._config.stream_reconnect_delay * 1000))
                    continue
                open_attempts = 0
                self._monitor.on_connected()
                self.connection_status.emit("connected")
                self._emit_health()
                frame_count = 0
                fps_timer_start = time.monotonic()

            # --- Read one frame ---
            ret, bgr = self._cap.read()
            if not ret or bgr is None:
                self._cap.release()
                self._cap = None
                self._monitor.on_drop("read_failed")
                self.connection_status.emit("reconnecting")
                self._emit_health()
                self.msleep(int(self._config.stream_reconnect_delay * 1000))
                continue

            # --- Track latency / health, then emit full-res for capture engine ---
            self._monitor.on_frame()
            self.frame_ready.emit(bgr)

            # --- Build display frame ---
            display = self._make_display_frame(bgr)
            self.display_frame_ready.emit(display)

            # --- FPS accounting (once per second, also refresh health) ---
            frame_count += 1
            elapsed = time.monotonic() - fps_timer_start
            if elapsed >= 1.0:
                self.fps_updated.emit(frame_count / elapsed)
                frame_count = 0
                fps_timer_start = time.monotonic()
                self._emit_health()

        # Cleanup
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._monitor.on_close()
        self._emit_health()
        self.connection_status.emit("disconnected")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open_capture(self, url: str) -> cv2.VideoCapture | None:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return None
        # Minimise latency: keep only the most recent frame in the internal buffer
        cap.set(cv2.CAP_PROP_BUFFERSIZE, self._config.stream_buffer_size)
        return cap

    def _make_display_frame(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        if w > self.DISPLAY_MAX_WIDTH:
            scale = self.DISPLAY_MAX_WIDTH / w
            new_w = self.DISPLAY_MAX_WIDTH
            new_h = int(h * scale)
            bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        # Convert to RGB for Qt
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
