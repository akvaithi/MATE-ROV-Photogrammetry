"""
MeshroomPipeline — cross-platform (Windows/Linux) reconstruction via
AliceVision's Meshroom, driven headless through its `meshroom_batch` CLI.

Meshroom is fully open-source and needs no account, but its depth-map stage runs
only on CUDA, so an **NVIDIA GPU is mandatory** — we detect its absence and fail
fast rather than stalling.  Meshroom emits a textured OBJ; we convert it to GLB
(via trimesh) so the same in-app viewer renders every backend's output.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from shutil import which
from typing import Optional

from loguru import logger

from app.core.reconstruction.base import (
    ProgressCallback,
    complete_all_stages,
    emit_stage_progress,
    finalize_model,
)

_KNOWN_BIN_NAMES = ("meshroom_batch.exe", "meshroom_batch")

# Detail level → Meshroom node param overrides.  Lower downscale = denser depth
# maps (slower, higher quality); larger textureSide = higher-res texture.
# Keys use meshroom_batch's NODETYPE:param form (applies to all nodes of a type).
_DETAIL_MAP: dict[str, dict[str, str]] = {
    "preview": {"DepthMap:downscale": "4", "Texturing:textureSide": "1024"},
    "reduced": {"DepthMap:downscale": "4", "Texturing:textureSide": "2048"},
    "medium":  {"DepthMap:downscale": "2", "Texturing:textureSide": "4096"},
    "full":    {"DepthMap:downscale": "2", "Texturing:textureSide": "8192"},
    "raw":     {"DepthMap:downscale": "1", "Texturing:textureSide": "8192"},
}

# Meshroom prints the node it is executing; map node-name keywords to the
# overall fraction reached when that node starts.
_NODE_CUES: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"FeatureExtraction|CameraInit", re.I),        0.00),
    (re.compile(r"ImageMatching|FeatureMatching", re.I),       0.10),
    (re.compile(r"StructureFromMotion", re.I),                 0.30),
    (re.compile(r"PrepareDenseScene|DepthMap", re.I),          0.55),
    (re.compile(r"Meshing|MeshFiltering|Texturing|Publish", re.I), 0.90),
]


class MeshroomPipeline:
    """AliceVision/Meshroom reconstruction via meshroom_batch (needs NVIDIA CUDA)."""

    name = "Meshroom (AliceVision)"
    output_suffix = ".glb"

    def __init__(self, detail: str = "medium", bin_path: str = "") -> None:
        self.detail = detail if detail in _DETAIL_MAP else "medium"
        self._bin_override = bin_path

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def find_executable(cls, override: str = "") -> Optional[Path]:
        if override:
            p = Path(override)
            return p if p.exists() else None
        for name in _KNOWN_BIN_NAMES:
            found = which(name)
            if found:
                return Path(found)
        return None

    @staticmethod
    def has_cuda_gpu() -> bool:
        """Heuristic NVIDIA/CUDA check: nvidia-smi on PATH or in System32."""
        if which("nvidia-smi"):
            return True
        if os.name == "nt":
            sysroot = os.environ.get("SystemRoot", r"C:\Windows")
            if (Path(sysroot) / "System32" / "nvidia-smi.exe").exists():
                return True
        return False

    @classmethod
    def is_available(cls, bin_path: str = "") -> bool:
        return cls.find_executable(bin_path) is not None and cls.has_cuda_gpu()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        image_dir: Path,
        output_path: Path,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> Path:
        binary = self.find_executable(self._bin_override)
        if binary is None:
            raise RuntimeError(
                "meshroom_batch not found. Install Meshroom from alicevision.org "
                "and add it to PATH, or set its path in Settings."
            )
        if not self.has_cuda_gpu():
            raise RuntimeError(
                "Meshroom requires an NVIDIA CUDA GPU (no CPU fallback for depth "
                "maps). Use RealityScan on this machine, or reconstruct on a Mac."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="meshroom_", dir=output_path.parent))

        args = [
            str(binary),
            "--input", str(image_dir),
            "--pipeline", "photogrammetry",
            "--output", str(work_dir),
        ]
        # All overrides must follow a single --paramOverrides flag (nargs='*').
        overrides = [f"{k}={v}" for k, v in _DETAIL_MAP[self.detail].items()]
        if overrides:
            args += ["--paramOverrides", *overrides]
        logger.debug("Launching Meshroom: " + " ".join(args))

        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None

        fraction = 0.0
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            logger.debug(f"Meshroom: {line}")
            fraction = self._update_progress(line, fraction, progress_cb)

        if proc.wait() != 0:
            raise RuntimeError(
                "Meshroom failed (see log). Common causes: too few overlapping "
                "images, or the CUDA depth-map stage could not run."
            )

        obj = self._find_output_mesh(work_dir)
        if obj is None:
            raise RuntimeError(
                f"Meshroom finished but no textured mesh was found in {work_dir}."
            )

        result = finalize_model(obj, output_path)
        complete_all_stages(progress_cb)
        return result

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _find_output_mesh(work_dir: Path) -> Optional[Path]:
        # Publish node copies the textured mesh to the output root; fall back to
        # a recursive search for any OBJ if the layout differs by version.
        preferred = list(work_dir.glob("*.obj"))
        if preferred:
            return preferred[0]
        found = list(work_dir.rglob("texturedMesh.obj")) or list(work_dir.rglob("*.obj"))
        return found[0] if found else None

    @staticmethod
    def _update_progress(
        line: str,
        current_fraction: float,
        cb: Optional[ProgressCallback],
    ) -> float:
        fraction = current_fraction
        for pattern, phase_start in _NODE_CUES:
            if pattern.search(line):
                fraction = max(fraction, phase_start)
                break
        if cb:
            emit_stage_progress(fraction, cb)
        return fraction
