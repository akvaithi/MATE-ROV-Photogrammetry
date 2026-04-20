"""
RealityKitPipeline — wraps Apple's PhotogrammetrySession (Object Capture)
via a compiled Swift helper binary.  Same engine that powers PhotoCatch and
Reality Composer's mobile scanning, so output quality matches those tools.

Availability: macOS 12+, Apple Silicon or Intel with AVX2.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Callable, Optional

from loguru import logger

HELPER_SRC = Path(__file__).parent / "realitykit_helper.swift"
HELPER_CACHE_DIR = Path.home() / ".photogrammetry" / "bin"
HELPER_BIN = HELPER_CACHE_DIR / "realitykit_helper"

# Apple's session gives a single fractional progress (0..1).  We splay it
# across the existing UI stage bars so the user gets familiar feedback.
STAGE_BANDS: list[tuple[str, float, float]] = [
    ("Feature Extraction",             0.00, 0.10),
    ("Feature Matching",               0.10, 0.30),
    ("Sparse Reconstruction (SfM)",    0.30, 0.55),
    ("Dense Reconstruction (MVS)",     0.55, 0.90),
    ("Meshing",                        0.90, 1.00),
]


class RealityKitPipeline:
    """Object Capture reconstruction via a compiled Swift helper."""

    def __init__(self, detail: str = "medium") -> None:
        self.detail = detail

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @staticmethod
    def is_platform_supported() -> bool:
        return sys.platform == "darwin" and which("swiftc") is not None

    @staticmethod
    def _needs_rebuild() -> bool:
        if not HELPER_BIN.exists():
            return True
        return HELPER_SRC.stat().st_mtime > HELPER_BIN.stat().st_mtime

    @classmethod
    def is_available(cls) -> bool:
        return cls.is_platform_supported()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_helper(self) -> None:
        if not self.is_platform_supported():
            raise RuntimeError(
                "RealityKit backend requires macOS with the Swift toolchain "
                "(install Xcode Command Line Tools: `xcode-select --install`)."
            )
        HELPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Compiling RealityKit helper binary…")
        cmd = ["swiftc", "-O", "-o", str(HELPER_BIN), str(HELPER_SRC)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"swiftc failed (exit {result.returncode}):\n{result.stderr}"
            )
        logger.info(f"Built RealityKit helper at {HELPER_BIN}")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        image_dir: Path,
        output_path: Path,
        progress_cb: Optional[Callable[[str, int], None]] = None,
    ) -> Path:
        if self._needs_rebuild():
            self.build_helper()

        # PhotogrammetrySession writes .usdz; rename suffix if needed.
        if output_path.suffix.lower() != ".usdz":
            output_path = output_path.with_suffix(".usdz")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        args = [str(HELPER_BIN), str(image_dir), str(output_path), self.detail]
        logger.debug(f"Launching helper: {' '.join(args)}")

        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.debug(f"helper: {line}")
                continue
            self._handle_event(msg, progress_cb)

        returncode = proc.wait()
        if returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(
                f"RealityKit helper exited with code {returncode}: {stderr}"
            )

        if not output_path.exists():
            raise RuntimeError(
                f"RealityKit completed but output {output_path} is missing."
            )
        # Mark every stage bar complete for a tidy UI finish.
        if progress_cb:
            for stage, _, _ in STAGE_BANDS:
                progress_cb(stage, 100)
        return output_path

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _handle_event(
        self,
        msg: dict,
        progress_cb: Optional[Callable[[str, int], None]],
    ) -> None:
        mtype = msg.get("type")
        if mtype == "progress":
            fraction = float(msg.get("fraction", 0.0))
            if progress_cb:
                self._emit_stage_progress(fraction, progress_cb)
        elif mtype == "warn":
            logger.warning(f"RealityKit: {msg.get('message')}")
        elif mtype == "info":
            logger.info(f"RealityKit: {msg.get('message')}")
        elif mtype == "error":
            raise RuntimeError(f"RealityKit error: {msg.get('message')}")
        elif mtype in ("complete", "request_complete", "cancelled"):
            logger.info(f"RealityKit: {mtype}")

    @staticmethod
    def _emit_stage_progress(
        fraction: float,
        cb: Callable[[str, int], None],
    ) -> None:
        fraction = max(0.0, min(1.0, fraction))
        for stage, lo, hi in STAGE_BANDS:
            if fraction >= hi:
                cb(stage, 100)
            elif fraction >= lo:
                pct = int(round((fraction - lo) / (hi - lo) * 100))
                cb(stage, pct)
            # else: stage not yet started — leave its bar at its prior value
