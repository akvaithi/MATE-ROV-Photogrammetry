from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class AppConfig:
    # RTSP stream
    rtsp_url: str = "rtsp://192.168.1.100:8554/stream"
    stream_reconnect_delay: float = 2.0   # seconds before reconnect attempt
    stream_buffer_size: int = 1           # OpenCV internal buffer size (keep low for low latency)
    stream_latency_warn_ms: float = 1500.0  # inter-frame gap above this logs a high-latency stall
    stream_health_log: bool = True        # write a per-run JSONL stream-health event log

    # Capture modes
    capture_mode: str = "auto"            # "auto", "interval", "manual"
    interval_seconds: float = 5.0        # seconds between interval captures
    auto_min_interval_seconds: float = 2.0  # minimum seconds between auto-captures (cooldown)
    min_frames: int = 30                  # minimum frames before reconstruction is allowed
    max_frames: int = 500                 # cap to avoid unbounded disk use

    # Stillness / quality thresholds
    motion_threshold: float = 3.0        # mean abs diff between frames; lower = stricter
    sharpness_threshold: float = 80.0    # Laplacian variance; higher = require sharper
    novelty_threshold: float = 0.10      # Bhattacharyya distance; lower = require more novelty
    framing_threshold: float = 0.45      # focus+centre composition score 0..1; 0 disables

    # Analysis
    analysis_fps: int = 30               # how many times per second to evaluate a frame
    rolling_buffer_max: int = 90         # max frames in the rolling buffer for interval mode

    # Output
    output_dir: str = str(Path.home() / "photogrammetry_sessions")
    jpeg_quality: int = 95               # JPEG save quality for captured frames

    # Reconstruction — RealityKit (Apple Object Capture) is the only backend.
    realitykit_detail: str = "medium"    # preview | reduced | medium | full | raw

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        # Only keep keys that exist in the dataclass to handle version upgrades gracefully
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def default_config_path(cls) -> Path:
        return Path.home() / ".photogrammetry" / "config.json"
