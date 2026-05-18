# Photogrammetry Studio

A PyQt6 desktop app for turning an RTSP video stream into a 3D model. It watches the stream, captures frames that pass quality gates (sharp, novel, well-framed), and hands the resulting image set to either Apple's Object Capture (same engine as PhotoCatch) or COLMAP for reconstruction.

Built for the MATE ROV competition — designed so an operator can scan an object underwater (or on deck) via an IP camera and get a usable mesh in a few minutes.

## Download

Prebuilt macOS bundle (Apple Silicon, macOS 12+):

**[Latest release →](https://github.com/akvaithi/MATE-ROV-Photogrammetry/releases/latest)**

The app is not codesigned, so the first launch needs right-click → **Open** to bypass Gatekeeper. After that, double-click works.

## What you need

| | Required for | |
|---|---|---|
| macOS 12+ (Apple Silicon) | running the app | |
| RTSP stream | source frames | e.g. `rtsp://192.168.1.100:8554/stream` |
| Xcode Command Line Tools | RealityKit backend (first reconstruction compiles a Swift helper) | `xcode-select --install` |
| COLMAP *(optional)* | fallback / non-mac reconstruction | `brew install colmap` |
| OpenMVS or Open3D *(optional)* | dense reconstruction inside the COLMAP backend | `brew install openmvs`, or `pip install open3d` |

## Usage

1. **Stream tab** — connects to the RTSP URL from Settings; check the indicator turns green.
2. **Capture tab** — pick a mode:
   - **Auto**: captures whenever a frame is sharp + novel + well-framed, with a configurable cooldown.
   - **Interval**: fires every N seconds regardless.
   - **Manual**: only when you press Capture Now.
   The live preview shows a rule-of-thirds grid and a colour-coded framing box (green = good, yellow = marginal, red = reject).
3. **Reconstruct tab** — pick a backend (Auto / RealityKit / COLMAP), a detail level (Preview → Raw), and hit Start. Progress bars show feature extraction → matching → SfM → MVS → meshing.

Frames live in `~/photogrammetry_sessions/session_<timestamp>/`; the output model is written alongside as `model.usdz` (RealityKit) or `model.ply` (COLMAP).

## Reconstruction backends

| Backend | When to use | Output |
|---|---|---|
| **RealityKit (Apple Object Capture)** | macOS default. Same engine as PhotoCatch and Reality Composer. Best quality, no extra tools. | `.usdz` with textures |
| **COLMAP** | Cross-platform, full control. Needs `brew install colmap`. Pairs with OpenMVS or Open3D for dense reconstruction. | `.ply` |
| **Auto** | Picks RealityKit on macOS if available, COLMAP otherwise. | depends |

Detail levels for RealityKit map directly to Apple's `PhotogrammetrySession.Request.Detail` enum: **Preview** (seconds) through **Raw** (minutes, original-resolution texture).

## Running from source

```bash
git clone https://github.com/akvaithi/MATE-ROV-Photogrammetry.git
cd MATE-ROV-Photogrammetry
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Python 3.12 is recommended (open3d wheels are available there).

## Building the .app

```bash
./build_app.sh           # clean rebuild + zip the bundle
./build_app.sh --no-zip  # build only
```

Output: `dist/Photogrammetry Studio.app` and `dist/PhotogrammetryStudio-macOS.zip`.

The build uses PyInstaller with a small runtime hook ([pyinstaller_hooks/pyi_rth_cv2.py](pyinstaller_hooks/pyi_rth_cv2.py)) that works around a known cv2-on-macOS-bundle import recursion. pyvista/VTK are excluded to keep the bundle ~150 MB zipped instead of ~400 MB — the 3D preview pane stays a placeholder in the packaged build, but loading USDZ in Reality Composer / Preview works fine.

## Architecture

```
StreamWorker (QThread)         RTSP frames via OpenCV/FFmpeg
       │
       ├──▶ display_frame_ready  ──▶ Stream + Capture preview
       └──▶ frame_ready           ──▶ CaptureEngine (worker thread)
                                          │
                                          ├─ QualityAssessor: focus + edge + center-prior framing score
                                          ├─ FrameStore: JPEG writer, deduplicated by Bhattacharyya distance
                                          └─ emits frame_captured

ReconstructionWorker (QThread)   on demand, when frame_count ≥ min_frames
       │
       ├─ RealityKitPipeline  ──▶ swiftc-compiled helper ──▶ PhotogrammetrySession
       └─ ColmapPipeline      ──▶ pycolmap / colmap CLI ──▶ OpenMVS / Open3D
```

| Path | Role |
|---|---|
| [app/core/stream_worker.py](app/core/stream_worker.py) | RTSP capture loop with auto-reconnect |
| [app/core/capture_engine.py](app/core/capture_engine.py) | Quality-gated frame capture, runs on its own thread |
| [app/core/quality_assessor.py](app/core/quality_assessor.py) | Sharpness, novelty, and ML-based framing score |
| [app/core/reconstruction/realitykit_pipeline.py](app/core/reconstruction/realitykit_pipeline.py) | Drives the Swift helper, splays progress into stage bars |
| [app/core/reconstruction/realitykit_helper.swift](app/core/reconstruction/realitykit_helper.swift) | CLI wrapper around `PhotogrammetrySession`, emits JSON events |
| [app/core/reconstruction/colmap_pipeline.py](app/core/reconstruction/colmap_pipeline.py) | SfM + MVS via pycolmap + COLMAP CLI |
| [app/ui/main_window.py](app/ui/main_window.py) | Owns all workers and signal routing |

## License

MIT — see source headers.
