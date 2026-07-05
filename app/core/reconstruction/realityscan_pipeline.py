"""
RealityScanPipeline — Windows reconstruction via Epic's RealityScan (formerly
RealityCapture) run headless from the command line.

RealityScan is free for students and sub-$1M teams and produces best-in-class
meshes at high speed, making it the closest Windows match to Apple's Object
Capture.  We drive it via its `-headless` CLI: a single process runs an ordered
list of commands (add images → align → compute model → texture → export), then
quits.

Unlike RealityKit, the CLI does not stream a clean 0..1 fraction, so progress is
driven **per phase** from stdout cues (alignment → SfM band, model calculation →
MVS band, texturing/export → Meshing band).  Command specifics can vary slightly
between RealityScan versions; the sequence here targets 2.x.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from shutil import which
from typing import Optional

from loguru import logger

from app.core.reconstruction.base import (
    STAGE_BANDS,
    ProgressCallback,
    complete_all_stages,
    emit_stage_progress,
    finalize_model,
)

# Candidate install locations searched when no explicit path is configured.
_KNOWN_EXE_NAMES = ("RealityScan.exe", "RealityCapture.exe")
# Parent dirs whose (possibly version-suffixed) subfolders hold the executable,
# e.g. "Epic Games\RealityScan_2.2\RealityScan.exe".
_INSTALL_PARENT_DIRS = (
    r"C:\Program Files\Epic Games",
    r"C:\Program Files\Capturing Reality",
)

# Detail level → (model-quality command, simplify target tris or None).
# Higher levels compute a denser model and decimate less aggressively.
_DETAIL_MAP: dict[str, tuple[str, Optional[int]]] = {
    "preview": ("-calculatePreviewModel", 100_000),
    "reduced": ("-calculateNormalModel", 200_000),
    "medium":  ("-calculateNormalModel", 500_000),
    "full":    ("-calculateHighModel",   2_000_000),
    "raw":     ("-calculateHighModel",   None),
}

# Map stdout keywords to the progress fraction reached once that phase begins.
# Lets the stage bars advance monotonically as the single CLI process runs.
_PHASE_CUES: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"align", re.I),                       0.10),
    (re.compile(r"reconstruct|depth|model|mesh", re.I), 0.55),
    (re.compile(r"textur|coloriz", re.I),              0.90),
    (re.compile(r"export", re.I),                      0.97),
]
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")


class RealityScanPipeline:
    """Object Capture-quality reconstruction on Windows via RealityScan CLI."""

    name = "RealityScan (Epic / RealityCapture)"
    output_suffix = ".glb"

    def __init__(self, detail: str = "medium", exe_path: str = "") -> None:
        self.detail = detail if detail in _DETAIL_MAP else "medium"
        self._exe_override = exe_path

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def find_executable(cls, override: str = "") -> Optional[Path]:
        """Locate RealityScan.exe: explicit override → PATH → known install dirs.

        Handles version-suffixed install folders (e.g. "RealityScan_2.2") by
        globbing the Epic Games / Capturing Reality parent directories.
        """
        if override:
            p = Path(override)
            return p if p.exists() else None
        for name in _KNOWN_EXE_NAMES:
            found = which(name) or which(name.replace(".exe", ""))
            if found:
                return Path(found)
        for parent in _INSTALL_PARENT_DIRS:
            base = Path(parent)
            if not base.exists():
                continue
            for name in _KNOWN_EXE_NAMES:
                # Direct child (Epic Games\RealityScan\...) and one level of
                # version-suffixed subfolders (Epic Games\RealityScan_2.2\...).
                cand = base / name.replace(".exe", "") / name
                if cand.exists():
                    return cand
                matches = sorted(base.glob(f"*/{name}"), reverse=True)
                if matches:
                    return matches[0]
        return None

    @classmethod
    def is_available(cls, exe_path: str = "") -> bool:
        return os.name == "nt" and cls.find_executable(exe_path) is not None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        image_dir: Path,
        output_path: Path,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> Path:
        exe = self.find_executable(self._exe_override)
        if exe is None:
            raise RuntimeError(
                "RealityScan executable not found. Install RealityScan from "
                "realityscan.com (free for students / sub-$1M teams), or set its "
                "path in Settings."
            )

        if output_path.suffix.lower() != self.output_suffix:
            output_path = output_path.with_suffix(self.output_suffix)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export as OBJ (RealityScan's most reliable, always-textured format),
        # then convert to a valid self-contained GLB + STL.  Exporting GLB
        # directly can leave the texture as an external file the GLB references
        # badly ("invalid scan" in some viewers), so we go via OBJ.
        obj_path = output_path.parent / "rs_export" / "model.obj"
        obj_path.parent.mkdir(parents=True, exist_ok=True)

        args = self._build_args(exe, image_dir, obj_path)
        logger.debug("Launching RealityScan: " + " ".join(str(a) for a in args))

        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None

        phase_fraction = 0.0
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            logger.debug(f"RealityScan: {line}")
            phase_fraction = self._update_progress(line, phase_fraction, progress_cb)

        returncode = proc.wait()
        if returncode != 0:
            raise RuntimeError(
                f"RealityScan exited with code {returncode}. See the log above; "
                "verify the images aligned and a model could be computed."
            )
        if not obj_path.exists():
            raise RuntimeError(
                "RealityScan finished but no model was exported "
                "(alignment or model calculation may have failed — try more "
                "overlapping images)."
            )
        result = finalize_model(obj_path, output_path)
        complete_all_stages(progress_cb)
        return result

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _build_args(self, exe: Path, image_dir: Path, output_path: Path) -> list[str]:
        model_cmd, simplify = _DETAIL_MAP[self.detail]
        args: list[str] = [
            str(exe),
            "-headless",
            "-addFolder", str(image_dir),
            "-align",
            "-setReconstructionRegionAuto",
            model_cmd,
        ]
        if simplify is not None:
            args += ["-simplify", str(simplify)]
        args += [
            "-calculateTexture",
            "-exportSelectedModel", str(output_path),
            "-quit",
        ]
        return args

    @staticmethod
    def _update_progress(
        line: str,
        current_fraction: float,
        cb: Optional[ProgressCallback],
    ) -> float:
        """Advance the overall fraction from a stdout line; monotonic."""
        fraction = current_fraction
        for pattern, phase_start in _PHASE_CUES:
            if pattern.search(line):
                fraction = max(fraction, phase_start)
                break
        # If the line carries an explicit percentage, nudge within the phase.
        m = _PERCENT_RE.search(line)
        if m:
            pct = min(100, int(m.group(1))) / 100.0
            # Scale the percentage across the current band's remaining span.
            band = _band_for_fraction(fraction)
            if band is not None:
                _, lo, hi = band
                fraction = max(fraction, lo + pct * (hi - lo))
        if cb:
            emit_stage_progress(fraction, cb)
        return fraction


def _band_for_fraction(fraction: float) -> Optional[tuple[str, float, float]]:
    for stage, lo, hi in STAGE_BANDS:
        if lo <= fraction < hi:
            return (stage, lo, hi)
    return STAGE_BANDS[-1] if fraction >= STAGE_BANDS[-1][1] else None
