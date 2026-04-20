from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class FrameRecord:
    """Metadata for a single captured frame."""
    index: int
    filename: str                  # e.g. "frame_0001.jpg"
    timestamp: str                 # ISO format
    motion_score: float
    sharpness_score: float
    novelty_score: float
    capture_mode: str              # "auto", "interval", "manual"

    @property
    def path(self) -> str:
        return self.filename


@dataclass
class ReconstructionStatus:
    """Tracks the state of the reconstruction pipeline."""
    is_running: bool = False
    current_stage: str = ""
    stage_progress: int = 0        # 0-100
    stages_completed: list[str] = field(default_factory=list)
    output_model_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AppState:
    """Single source of truth for the running application session."""
    session_id: str = ""
    session_dir: Optional[Path] = None
    frames_dir: Optional[Path] = None
    colmap_dir: Optional[Path] = None
    output_dir: Optional[Path] = None

    frames: list[FrameRecord] = field(default_factory=list)
    reconstruction: ReconstructionStatus = field(default_factory=ReconstructionStatus)

    stream_connected: bool = False
    stream_fps: float = 0.0

    capture_running: bool = False
    capture_mode: str = "manual"

    colmap_available: bool = False

    def new_session(self, base_output_dir: Path) -> None:
        self.session_id = datetime.now().strftime("session_%Y%m%d_%H%M%S")
        self.session_dir = base_output_dir / self.session_id
        self.frames_dir = self.session_dir / "frames"
        self.colmap_dir = self.session_dir / "colmap"
        self.output_dir = self.session_dir / "output"
        for d in (self.frames_dir, self.colmap_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.frames = []
        self.reconstruction = ReconstructionStatus()

    def add_frame(self, record: FrameRecord) -> None:
        self.frames.append(record)

    @property
    def frame_count(self) -> int:
        return len(self.frames)
