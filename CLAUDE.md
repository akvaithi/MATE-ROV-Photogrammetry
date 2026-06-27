# Photogrammetry Studio

A PyQt6 desktop app (macOS, Apple Silicon) that turns an **RTSP video stream**
into a 3D model: it watches the stream, captures frames that pass quality gates
(sharp, novel, well-framed), and reconstructs a mesh with **Apple Object Capture
(RealityKit)** or **COLMAP**.

Built for the MATE ROV competition (Team Oceanus / GNC). This repo is also a git
**submodule** inside `ThinkTank-TAMU/TAMU-Oceanus` at
`01_Subteams/GNC/Photogrammetry-App` — commit here and push to this repo's own
remote (`akvaithi/MATE-ROV-Photogrammetry`), then bump the pointer in the team repo.

## Run / build

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # 3.12 (open3d wheels)
pip install -r requirements.txt
python main.py

./build_app.sh            # PyInstaller bundle + zip → dist/
./build_app.sh --no-zip   # build only
```

## Architecture (where things live)

Everything is thread-isolated through Qt signals — **never touch the UI from a
worker thread; emit a signal instead.**

```
StreamWorker (QThread)  ── RTSP via OpenCV/FFmpeg, auto-reconnect
   ├─ display_frame_ready ─▶ Stream + Capture preview
   └─ frame_ready         ─▶ CaptureEngine (own thread)
                                ├─ QualityAssessor  sharpness + novelty + framing score
                                └─ FrameStore       JPEG writer, dedup by Bhattacharyya distance
ReconstructionWorker (QThread)  on demand when frame_count ≥ min_frames
   ├─ RealityKitPipeline ─▶ swiftc helper ─▶ PhotogrammetrySession (.usdz)
   └─ ColmapPipeline     ─▶ pycolmap / COLMAP CLI ─▶ OpenMVS / Open3D (.ply)
```

| Path | Role |
|---|---|
| `app/core/stream_worker.py` | RTSP capture loop, reconnect logic |
| `app/core/capture_engine.py` | Quality-gated capture (own thread) |
| `app/core/quality_assessor.py` | Sharpness / novelty / framing scoring |
| `app/core/reconstruction/realitykit_pipeline.py` | Drives the Swift helper, parses JSON progress |
| `app/core/reconstruction/realitykit_helper.swift` | CLI around `PhotogrammetrySession` |
| `app/core/reconstruction/colmap_pipeline.py` | SfM + MVS via pycolmap/COLMAP |
| `app/ui/main_window.py` | Owns all workers + signal routing |
| `app/config.py`, `app/state.py` | Settings + shared app state |

Sessions write to `~/photogrammetry_sessions/session_<timestamp>/`; output is
`model.usdz` (RealityKit) or `model.ply` (COLMAP).

## Conventions & gotchas

- **Python 3.12** is the target (open3d wheels). Backends are optional: RealityKit
  needs Xcode CLT (`xcode-select --install`); COLMAP needs `brew install colmap`.
- `Auto` backend → RealityKit on macOS, COLMAP otherwise.
- PyInstaller build uses a runtime hook (`pyinstaller_hooks/pyi_rth_cv2.py`) for a
  cv2-on-macOS import recursion; **pyvista/VTK are excluded** to keep the bundle
  small, so the 3D preview pane is a placeholder in the packaged build (USDZ still
  opens in Preview / Reality Composer).
- The app is not codesigned — first launch needs right-click → Open.

## Goal 3 (GNC 3-week plan) — current work item

> *Refine the RTSP-to-3D pipeline: add **error logging for stream drops / high
> latency** and document performance metrics.*

Start in `app/core/stream_worker.py` (the RTSP loop + reconnect) — that's where
drop/latency detection belongs. Surface events through a logger (and ideally a UI
indicator via a signal), and document the metrics. See `3_Week Plan.md` Project 3
in the parent GNC folder.
