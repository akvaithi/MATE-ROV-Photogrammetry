"""
StreamHealthMonitor — RTSP drop & latency tracking (GNC 3-week plan, Goal 3).

The StreamWorker feeds this lifecycle events (connect attempt / connected /
frame / drop / reconnect / fatal). In return it:

  • logs every notable event through loguru (which main.py also persists to a
    rotating file sink), so a dropped or laggy stream leaves a trail,
  • appends structured JSON-lines records to a per-run log for later analysis,
  • maintains rolling performance metrics — FPS, drop / reconnect / stall counts,
    up- and down-time, and inter-frame latency — exposed as a StreamStats snapshot
    the UI can display.

"High latency" here means the wall-clock gap between two successive decoded
frames exceeding ``latency_warn_ms``. In a blocking pull loop with the capture
buffer pinned to 1 frame, that gap tracks how long ``cap.read()`` waited for the
next frame, so an oversized gap means the stream stalled or the network backed up.

The monitor runs on the StreamWorker thread (not the Qt main thread) and holds no
Qt objects, so it stays cheap and testable in isolation.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from loguru import logger


@dataclass
class StreamStats:
    """Immutable snapshot of stream health, emitted to the UI."""
    connected: bool = False
    frames_total: int = 0
    drops: int = 0            # mid-stream read failures (each forces a reconnect)
    reconnects: int = 0       # connections re-established after a drop
    stalls: int = 0           # inter-frame gaps over the latency threshold
    avg_fps: float = 0.0      # frames / connected-time
    uptime_s: float = 0.0     # cumulative connected time
    downtime_s: float = 0.0   # cumulative time spent disconnected (after first connect)
    last_gap_ms: float = 0.0  # most recent inter-frame gap
    max_gap_ms: float = 0.0   # worst inter-frame gap this session
    avg_gap_ms: float = 0.0   # mean inter-frame gap


class StreamHealthMonitor:
    DEFAULT_LOG_DIR = Path.home() / ".photogrammetry" / "logs"

    def __init__(
        self,
        latency_warn_ms: float = 1500.0,
        write_log: bool = True,
        log_dir: Path | str | None = None,
    ) -> None:
        self._latency_warn = latency_warn_ms / 1000.0  # seconds
        self._write_log = write_log
        self._log_dir = Path(log_dir) if log_dir else self.DEFAULT_LOG_DIR
        self._log_path: Path | None = None
        if write_log:
            try:
                self._log_dir.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                self._log_path = self._log_dir / f"stream_health_{stamp}.jsonl"
            except OSError as exc:
                logger.error(f"Could not create stream-health log dir: {exc}")
                self._write_log = False

        # --- metrics ---
        self._frames = 0
        self._drops = 0
        self._reconnects = 0
        self._stalls = 0
        self._uptime = 0.0
        self._downtime = 0.0
        self._gap_sum = 0.0
        self._gap_n = 0
        self._max_gap = 0.0
        self._last_gap = 0.0

        # --- transition bookkeeping ---
        self._connected = False
        self._ever_connected = False
        self._fatal_logged = False
        self._last_frame_t: float | None = None
        self._connected_since: float | None = None
        self._down_since: float | None = None

    # ------------------------------------------------------------------
    # Lifecycle events (called from the StreamWorker thread)
    # ------------------------------------------------------------------

    def on_connect_attempt(self, attempt: int) -> None:
        if self._ever_connected:
            self._event("reconnecting", attempt=attempt)
            logger.info(f"RTSP reconnecting (attempt {attempt})")
        else:
            self._event("connecting", attempt=attempt)
            logger.info(f"RTSP connecting to stream (attempt {attempt})")

    def on_connected(self) -> None:
        is_reconnect = self._ever_connected
        self._set_connected(True)
        if is_reconnect:
            self._reconnects += 1
        self._ever_connected = True
        self._fatal_logged = False
        self._event("connected", reconnect=is_reconnect)
        logger.success(
            "RTSP stream re-established" if is_reconnect else "RTSP stream connected"
        )

    def on_open_failed(self, attempt: int) -> None:
        # Start counting downtime once we've been connected at least once.
        if self._ever_connected and not self._connected and self._down_since is None:
            self._down_since = time.monotonic()
        self._event("open_failed", attempt=attempt)
        logger.warning(f"RTSP open failed (attempt {attempt})")

    def on_frame(self) -> None:
        now = time.monotonic()
        if self._last_frame_t is not None:
            gap = now - self._last_frame_t
            self._last_gap = gap * 1000.0
            self._gap_sum += gap
            self._gap_n += 1
            if gap > self._max_gap:
                self._max_gap = gap
            if gap >= self._latency_warn:
                self._stalls += 1
                self._event("high_latency", gap_ms=round(gap * 1000.0, 1))
                logger.warning(
                    f"RTSP high-latency stall: {gap * 1000.0:.0f} ms between frames "
                    f"(threshold {self._latency_warn * 1000.0:.0f} ms)"
                )
        self._last_frame_t = now
        self._frames += 1

    def on_drop(self, reason: str = "read_failed") -> None:
        up = 0.0
        if self._connected_since is not None:
            up = time.monotonic() - self._connected_since
        self._drops += 1
        self._set_connected(False)
        self._event("drop", reason=reason, uptime_s=round(up, 1))
        logger.warning(f"RTSP stream dropped ({reason}) after {up:.1f}s connected")

    def on_fatal(self, message: str) -> None:
        if not self._fatal_logged:
            self._event("fatal", message=message)
            logger.error(message)
            self._fatal_logged = True

    def on_close(self) -> None:
        self._set_connected(False)
        stats = self.snapshot()
        self._event("summary", **asdict(stats))
        logger.info(
            f"RTSP session summary: {stats.frames_total} frames, {stats.drops} drops, "
            f"{stats.reconnects} reconnects, {stats.stalls} stalls, "
            f"uptime {stats.uptime_s:.0f}s, downtime {stats.downtime_s:.0f}s, "
            f"max gap {stats.max_gap_ms:.0f} ms"
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> StreamStats:
        now = time.monotonic()
        uptime = self._uptime + (now - self._connected_since if self._connected_since else 0.0)
        downtime = self._downtime + (now - self._down_since if self._down_since else 0.0)
        avg_fps = self._frames / uptime if uptime > 0 else 0.0
        avg_gap = (self._gap_sum / self._gap_n * 1000.0) if self._gap_n else 0.0
        return StreamStats(
            connected=self._connected,
            frames_total=self._frames,
            drops=self._drops,
            reconnects=self._reconnects,
            stalls=self._stalls,
            avg_fps=round(avg_fps, 1),
            uptime_s=round(uptime, 1),
            downtime_s=round(downtime, 1),
            last_gap_ms=round(self._last_gap, 1),
            max_gap_ms=round(self._max_gap * 1000.0, 1),
            avg_gap_ms=round(avg_gap, 1),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _set_connected(self, value: bool) -> None:
        """Accumulate up/down-time across a connected<->disconnected transition."""
        now = time.monotonic()
        if value and not self._connected:
            if self._down_since is not None:
                self._downtime += now - self._down_since
                self._down_since = None
            self._connected_since = now
            self._connected = True
            self._last_frame_t = None  # don't count the reconnect gap as a stall
        elif not value and self._connected:
            if self._connected_since is not None:
                self._uptime += now - self._connected_since
                self._connected_since = None
            self._down_since = now
            self._connected = False
            self._last_frame_t = None

    def _event(self, kind: str, **fields) -> None:
        if not self._write_log or self._log_path is None:
            return
        record = {"ts": round(time.time(), 3), "event": kind, **fields}
        try:
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.error(f"stream-health log write failed: {exc}")
            self._write_log = False
