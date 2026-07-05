"""
Reconstruction backend contract + shared progress helpers.

Every reconstruction engine (RealityKit on macOS, RealityScan / Meshroom on
Windows/Linux) implements the same small surface so `ReconstructionWorker` and
the UI never need to know which one is running:

    backend.is_available()  -> bool
    backend.run(image_dir, output_path, progress_cb) -> Path

Engines report a single 0..1 fraction of overall progress; `emit_stage_progress`
splays that fraction across the five UI stage bars (a hold-over from the classic
COLMAP-style pipeline) so the user always gets familiar feedback regardless of
backend.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable

from loguru import logger

# The five pipeline stages shown in the UI, each mapped to a slice of the
# overall 0..1 progress fraction.  (name, fraction_lo, fraction_hi)
STAGE_BANDS: list[tuple[str, float, float]] = [
    ("Feature Extraction",             0.00, 0.10),
    ("Feature Matching",               0.10, 0.30),
    ("Sparse Reconstruction (SfM)",    0.30, 0.55),
    ("Dense Reconstruction (MVS)",     0.55, 0.90),
    ("Meshing",                        0.90, 1.00),
]

ProgressCallback = Callable[[str, int], None]


def emit_stage_progress(fraction: float, cb: ProgressCallback) -> None:
    """Translate an overall 0..1 fraction into per-stage (name, percent) calls."""
    fraction = max(0.0, min(1.0, fraction))
    for stage, lo, hi in STAGE_BANDS:
        if fraction >= hi:
            cb(stage, 100)
        elif fraction >= lo:
            pct = int(round((fraction - lo) / (hi - lo) * 100))
            cb(stage, pct)
        # else: stage not yet started — leave its bar at its prior value


def complete_all_stages(cb: Optional[ProgressCallback]) -> None:
    """Mark every stage bar 100% for a tidy UI finish."""
    if cb:
        for stage, _, _ in STAGE_BANDS:
            cb(stage, 100)


def obj_to_glb(obj_path: Path, glb_path: Path) -> Path:
    """Convert a textured OBJ (+MTL+textures) to a single self-contained GLB.

    GLB is binary glTF: trimesh embeds the geometry *and* texture image into one
    file, so the result is portable (no sidecar PNGs) and renders in any glTF
    viewer.  Falls back to returning the original OBJ if trimesh is unavailable
    or the conversion fails.
    """
    if glb_path.suffix.lower() != ".glb":
        glb_path = glb_path.with_suffix(".glb")
    try:
        import trimesh  # heavy import; only needed at conversion time

        scene = trimesh.load(str(obj_path))
        scene.export(str(glb_path))
        logger.info(f"Converted {obj_path.name} → {glb_path}")
        return glb_path
    except Exception as exc:  # noqa: BLE001 — degrade gracefully to the OBJ
        logger.warning(f"GLB conversion failed ({exc}); keeping OBJ output instead.")
        return obj_path


def finalize_model(obj_path: Path, glb_path: Path) -> Path:
    """Turn a raw OBJ export into the app's deliverables and return the primary.

    Writes, next to `glb_path`:
      * ``model.glb`` — self-contained, textured (the primary, returned path)
      * ``model.stl`` — geometry-only, opens in any viewer (Windows 3D Viewer,
        Paint 3D, printers, etc.)

    The original OBJ (+MTL+textures) is left in place too, so the output folder
    ends up with a textured GLB, a universal STL, and the editable OBJ set.
    Falls back to the OBJ if trimesh is missing.
    """
    glb = obj_to_glb(obj_path, glb_path)
    # Best-effort STL alongside the GLB for maximum viewer compatibility.
    try:
        import trimesh

        stl_path = glb_path.with_suffix(".stl")
        scene = trimesh.load(str(obj_path))
        mesh = scene.dump(concatenate=True) if hasattr(scene, "dump") else scene
        mesh.export(str(stl_path))
        logger.info(f"Wrote STL copy → {stl_path}")
    except Exception as exc:  # noqa: BLE001 — STL is a bonus, never fatal
        logger.warning(f"STL export skipped ({exc}).")
    return glb


@runtime_checkable
class ReconstructionBackend(Protocol):
    """Structural contract shared by every reconstruction engine."""

    #: Human-readable engine name, shown in the UI (e.g. "RealityScan").
    name: str
    #: Suffix of the file this backend writes (e.g. ".usdz", ".glb").
    output_suffix: str

    @classmethod
    def is_available(cls) -> bool:
        """True if this engine can run on the current machine right now."""
        ...

    def run(
        self,
        image_dir: Path,
        output_path: Path,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> Path:
        """Reconstruct a model from images in `image_dir`, writing `output_path`.

        Returns the path actually written (which may differ in suffix).
        Raises RuntimeError on failure with a user-facing message.
        """
        ...
