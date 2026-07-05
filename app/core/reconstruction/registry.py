"""
Backend registry — picks the reconstruction engine for the current machine.

Selection order (when `config.reconstruction_backend == "auto"`):
  * macOS            → RealityKit (Apple Object Capture)
  * Windows / Linux  → RealityScan if installed, else Meshroom (needs NVIDIA CUDA)

An explicit `reconstruction_backend` value ("realitykit" | "realityscan" |
"meshroom") forces that engine and surfaces a clear error if it is unavailable.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from app.core.reconstruction.meshroom_pipeline import MeshroomPipeline
from app.core.reconstruction.realitykit_pipeline import RealityKitPipeline
from app.core.reconstruction.realityscan_pipeline import RealityScanPipeline

if TYPE_CHECKING:
    from app.config import AppConfig
    from app.core.reconstruction.base import ReconstructionBackend


def _availability(config: "AppConfig") -> dict[str, bool]:
    """Availability of each backend, honouring configured executable paths."""
    return {
        "realitykit": RealityKitPipeline.is_available(),
        "realityscan": RealityScanPipeline.is_available(config.realityscan_exe),
        "meshroom": MeshroomPipeline.is_available(config.meshroom_bin),
    }


def available_backend_names(config: "AppConfig") -> list[str]:
    """Human-readable names of every backend usable on this machine right now."""
    names = {
        "realitykit": RealityKitPipeline.name,
        "realityscan": RealityScanPipeline.name,
        "meshroom": MeshroomPipeline.name,
    }
    return [names[k] for k, ok in _availability(config).items() if ok]


def _instantiate(key: str, config: "AppConfig") -> "ReconstructionBackend":
    detail = config.reconstruction_detail
    if key == "realitykit":
        return RealityKitPipeline(detail=detail)
    if key == "realityscan":
        return RealityScanPipeline(detail=detail, exe_path=config.realityscan_exe)
    if key == "meshroom":
        return MeshroomPipeline(detail=detail, bin_path=config.meshroom_bin)
    raise ValueError(f"Unknown reconstruction backend: {key!r}")


def select_backend(config: "AppConfig") -> "ReconstructionBackend":
    """Return an instantiated backend for `config`, or raise if none is usable."""
    avail = _availability(config)
    choice = (config.reconstruction_backend or "auto").lower()

    if choice != "auto":
        if choice not in avail:
            raise RuntimeError(
                f"Unknown reconstruction backend '{choice}'. Valid options: "
                "auto, realitykit, realityscan, meshroom."
            )
        if not avail[choice]:
            raise RuntimeError(_unavailable_message(choice))
        return _instantiate(choice, config)

    # Auto: platform-preferred order.
    order = (
        ["realitykit", "realityscan", "meshroom"]
        if sys.platform == "darwin"
        else ["realityscan", "meshroom", "realitykit"]
    )
    for key in order:
        if avail[key]:
            return _instantiate(key, config)

    raise RuntimeError(
        "No reconstruction engine is available on this machine.\n"
        "  • macOS: install Xcode Command Line Tools (RealityKit).\n"
        "  • Windows: install RealityScan (free, realityscan.com) — recommended, "
        "or Meshroom (needs an NVIDIA GPU).\n"
        "  • Linux: install Meshroom (needs an NVIDIA GPU)."
    )


def _unavailable_message(key: str) -> str:
    if key == "realitykit":
        return (
            "RealityKit (Apple Object Capture) is unavailable — it requires macOS "
            "12+ with the Swift toolchain (`xcode-select --install`)."
        )
    if key == "realityscan":
        return (
            "RealityScan is unavailable — install it from realityscan.com (free "
            "for students / sub-$1M teams), or set its path in Settings. "
            "RealityScan is Windows-only."
        )
    if key == "meshroom":
        return (
            "Meshroom is unavailable — install it from alicevision.org and ensure "
            "an NVIDIA CUDA GPU is present (there is no CPU fallback)."
        )
    return f"Backend '{key}' is unavailable."
