"""
Saves captured frames to disk and maintains the in-memory histogram cache
used for novelty checks.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.core.quality_assessor import compute_hsv_hist
from app.state import FrameRecord


class FrameStore:
    """
    Manages persisting frames to `frames_dir` and keeping metadata in memory.

    Thread-safety note: All public methods are called from the CaptureEngine
    worker thread.  The MainWindow reads `self.hists` via a signal; no locking
    is needed because the list is only ever *appended* (never mutated in place).
    """

    def __init__(self, frames_dir: Path, jpeg_quality: int = 95) -> None:
        self.frames_dir = frames_dir
        self.jpeg_quality = jpeg_quality
        self.hists: list[np.ndarray] = []          # HSV histograms of saved frames
        self._records: list[FrameRecord] = []
        self._metadata_path = frames_dir.parent / "metadata.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_frame(
        self,
        bgr: np.ndarray,
        scores: dict,
        capture_mode: str,
    ) -> FrameRecord:
        """
        Persist a frame as JPEG, update the histogram cache, and return its record.
        """
        index = len(self._records) + 1
        filename = f"frame_{index:04d}.jpg"
        filepath = self.frames_dir / filename

        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        cv2.imwrite(str(filepath), bgr, encode_params)

        # Update histogram cache
        hist = compute_hsv_hist(bgr)
        self.hists.append(hist)

        record = FrameRecord(
            index=index,
            filename=str(filepath),
            timestamp=datetime.now().isoformat(),
            motion_score=scores.get("motion", 0.0),
            sharpness_score=scores.get("sharpness", 0.0),
            novelty_score=scores.get("novelty", 1.0),
            capture_mode=capture_mode,
        )
        self._records.append(record)
        self._flush_metadata()
        return record

    def load_existing_session(self) -> list[FrameRecord]:
        """
        Re-populate from a previously saved metadata.json (for session resume).
        Also rebuilds the histogram cache from disk images.
        """
        if not self._metadata_path.exists():
            return []

        data = json.loads(self._metadata_path.read_text())
        records = []
        for item in data:
            rec = FrameRecord(**item)
            records.append(rec)
            path = Path(rec.filename)
            if path.exists():
                bgr = cv2.imread(str(path))
                if bgr is not None:
                    self.hists.append(compute_hsv_hist(bgr))

        self._records = records
        return records

    @property
    def frame_count(self) -> int:
        return len(self._records)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _flush_metadata(self) -> None:
        payload = [
            {
                "index": r.index,
                "filename": r.filename,
                "timestamp": r.timestamp,
                "motion_score": r.motion_score,
                "sharpness_score": r.sharpness_score,
                "novelty_score": r.novelty_score,
                "capture_mode": r.capture_mode,
            }
            for r in self._records
        ]
        self._metadata_path.write_text(json.dumps(payload, indent=2))
