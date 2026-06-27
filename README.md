# Photogrammetry Studio

A PyQt6 desktop app for turning an RTSP video stream into a 3D model. It watches the stream, captures frames that pass quality gates (sharp, novel, well-framed), and reconstructs a textured mesh with **Apple's Object Capture (RealityKit)** — the same engine behind PhotoCatch and Reality Composer.

Built for the MATE ROV competition — designed so an operator can scan an object underwater (or on deck) via an IP camera and get a usable mesh in a few minutes.

> **macOS only.** Object Capture is an Apple framework (RealityKit + Metal) with no Windows/Linux equivalent. The capture half (RTSP + quality gating) is cross-platform, but reconstruction requires a Mac. See [Reconstruction backend](#reconstruction-backend).

## Download

Prebuilt macOS bundle (Apple Silicon, macOS 12+):

**[Latest release →](https://github.com/akvaithi/MATE-ROV-Photogrammetry/releases/latest)**

The app is not codesigned, so the first launch needs right-click → **Open** to bypass Gatekeeper. After that, double-click works.

## What you need

| | Required for | |
|---|---|---|
| macOS 12+ (Apple Silicon) | running the app + reconstruction | |
| RTSP stream | source frames | e.g. `rtsp://192.168.1.100:8554/stream` |
| Xcode Command Line Tools | RealityKit reconstruction (first run compiles a Swift helper) | `xcode-select --install` |

## Usage

1. **Stream tab** — connects to the RTSP URL from Settings; check the indicator turns green.
2. **Capture tab** — pick a mode:
   - **Auto**: captures whenever a frame is sharp + novel + well-framed, with a configurable cooldown.
   - **Interval**: fires every N seconds regardless.
   - **Manual**: only when you press Capture Now.
   The live preview shows a rule-of-thirds grid and a colour-coded framing box (green = good, yellow = marginal, red = reject).
3. **Reconstruct tab** — pick a detail level (Preview → Raw) and hit Start. Progress bars show feature extraction → matching → SfM → MVS → meshing. When it finishes, a preview of the `.usdz` appears in the panel; **Open in Quick Look** opens the full interactive (rotatable) viewer, and **Reveal in Finder** locates the file.

Frames live in `~/photogrammetry_sessions/session_<timestamp>/`; the output model is written alongside as `model.usdz`.

## Reconstruction backend

Reconstruction uses **RealityKit (Apple Object Capture)** — the same engine as PhotoCatch and Reality Composer. Best-in-class quality, no extra tooling beyond Xcode Command Line Tools, output is a textured `.usdz`. On first run the app compiles a small Swift helper around `PhotogrammetrySession`.

Detail levels map directly to Apple's `PhotogrammetrySession.Request.Detail` enum: **Preview** (seconds) through **Raw** (minutes, original-resolution texture).

> **Why Apple-only?** Object Capture is built on RealityKit + Metal and has no Windows/Linux port. COLMAP support was removed in favour of RealityKit's superior quality. To use the app from a Windows machine, run reconstruction on a shared Mac (a Mac mini works well as a build node) — the capture side is cross-platform.

## Running from source

```bash
git clone https://github.com/akvaithi/MATE-ROV-Photogrammetry.git
cd MATE-ROV-Photogrammetry
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Python 3.12 is recommended.

## Building the .app

```bash
./build_app.sh           # clean rebuild + zip the bundle
./build_app.sh --no-zip  # build only
```

Output: `dist/Photogrammetry Studio.app` and `dist/PhotogrammetryStudio-macOS.zip`.

The build uses PyInstaller with a small runtime hook ([pyinstaller_hooks/pyi_rth_cv2.py](pyinstaller_hooks/pyi_rth_cv2.py)) that works around a known cv2-on-macOS-bundle import recursion. The in-app 3D preview renders the USDZ via macOS Quick Look (`qlmanage`) and the **Open in Quick Look** button opens the full interactive viewer — so no heavy 3D library (pyvista/VTK) is bundled, keeping the app lean.

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
       └─ RealityKitPipeline  ──▶ swiftc-compiled helper ──▶ PhotogrammetrySession ──▶ model.usdz
```

| Path | Role |
|---|---|
| [app/core/stream_worker.py](app/core/stream_worker.py) | RTSP capture loop with auto-reconnect |
| [app/core/stream_health.py](app/core/stream_health.py) | Drop / latency detection, logging, and stream metrics |
| [app/core/capture_engine.py](app/core/capture_engine.py) | Quality-gated frame capture, runs on its own thread |
| [app/core/quality_assessor.py](app/core/quality_assessor.py) | Sharpness, novelty, and ML-based framing score |
| [app/core/reconstruction/realitykit_pipeline.py](app/core/reconstruction/realitykit_pipeline.py) | Drives the Swift helper, splays progress into stage bars |
| [app/core/reconstruction/realitykit_helper.swift](app/core/reconstruction/realitykit_helper.swift) | CLI wrapper around `PhotogrammetrySession`, emits JSON events |
| [app/ui/main_window.py](app/ui/main_window.py) | Owns all workers and signal routing |

## Stream health & logging

The RTSP ingest is instrumented for **dropped frames and high latency**: drops,
reconnects, and inter-frame stalls are detected, shown live on the Stream tab,
and logged to `~/.photogrammetry/logs/` (a rotating app log plus a per-run
`stream_health_*.jsonl` for analysis). Thresholds live in `app/config.py`
(`stream_latency_warn_ms`, `stream_health_log`). Full write-up:
[docs/RTSP-Pipeline.md](docs/RTSP-Pipeline.md).

## Platform & roadmap

**macOS only** — reconstruction uses Apple's Object Capture, which has no
Windows/Linux equivalent. The capture side (RTSP + quality gating) is
cross-platform, so a Windows operator can drive the app and reconstruct on a
shared Mac (a Mac mini works well as a build node).

A native **Swift/SwiftUI rewrite was considered and deferred** for now: the app
works, the team works in Python, and RTSP ingest — one line with OpenCV — is
non-trivial in Swift (AVFoundation can't play RTSP). The likely next native step
is an **embedded interactive USDZ viewer** to replace the Quick Look hand-off.

## License

MIT — see source headers.
