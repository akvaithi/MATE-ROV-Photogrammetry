# Photogrammetry Studio

A PyQt6 desktop app for turning an RTSP video stream into a 3D model. It watches the stream, captures frames that pass quality gates (sharp, novel, well-framed), and reconstructs a textured mesh with a **pluggable, auto-selected reconstruction backend** — Apple's Object Capture (RealityKit) on macOS, or Epic's RealityScan / AliceVision Meshroom on Windows & Linux.

Built for the MATE ROV competition — designed so an operator can scan an object underwater (or on deck) via an IP camera and get a usable mesh in a few minutes.

> **Cross-platform.** The whole pipeline now runs on **macOS, Windows, and Linux**. The engine is chosen automatically per platform; you just need one installed (see [Reconstruction backends](#reconstruction-backends)). Capture (RTSP + quality gating) has always been cross-platform.

## Download

Prebuilt macOS bundle (Apple Silicon, macOS 12+):

**[Latest release →](https://github.com/akvaithi/MATE-ROV-Photogrammetry/releases/latest)**

The app is not codesigned, so the first launch needs right-click → **Open** to bypass Gatekeeper. After that, double-click works.

## What you need

| | Required for | |
|---|---|---|
| Python 3.12 + the app | running capture (any OS) | Windows / macOS / Linux |
| RTSP stream | source frames | e.g. `rtsp://192.168.1.100:8554/stream` |
| **One** reconstruction engine | building the 3D model | see below |

Reconstruction engine, by platform:

| Platform | Engine | Install |
|---|---|---|
| Windows | **RealityScan** (recommended) | Free for students / sub-$1M teams — [realityscan.com](https://www.realityscan.com/download) |
| Windows / Linux | Meshroom (fallback) | [alicevision.org](https://alicevision.org) — **requires an NVIDIA CUDA GPU** |
| macOS 12+ | RealityKit / Object Capture | Xcode Command Line Tools: `xcode-select --install` |

## Usage

1. **Stream tab** — connects to the RTSP URL from Settings; check the indicator turns green.
2. **Capture tab** — pick a mode:
   - **Auto**: captures whenever a frame is sharp + novel + well-framed, with a configurable cooldown.
   - **Interval**: fires every N seconds regardless.
   - **Manual**: only when you press Capture Now.
   The live preview shows a rule-of-thirds grid and a colour-coded framing box (green = good, yellow = marginal, red = reject).
3. **Reconstruct tab** — the panel shows which engine(s) were auto-detected. Pick a detail level (Preview → Raw) and hit Start. Progress bars show feature extraction → matching → SfM → MVS → meshing. When it finishes, a preview appears in the panel; **Open** launches the full interactive (rotatable) viewer in your OS's 3D viewer and **Reveal** locates the file.

Frames live in `~/photogrammetry_sessions/session_<timestamp>/`; the output model is written alongside as `model.usdz` (RealityKit) or `model.glb` (RealityScan / Meshroom).

## Reconstruction backends

The engine is a **pluggable backend, auto-selected** for the machine (override via `reconstruction_backend` in the config). All backends share the same five-stage progress UI and detail levels (**Preview** → **Raw**).

| Engine | Platforms | Notes |
|---|---|---|
| **RealityScan** (Epic, ex-RealityCapture) | Windows | Best-in-class quality + speed; **free** for students / sub-$1M teams. Driven headless via its CLI; exports a textured `.glb`. |
| **RealityKit** (Apple Object Capture) | macOS 12+ | Same engine as PhotoCatch. Compiles a small Swift helper around `PhotogrammetrySession` on first run; exports `.usdz`. |
| **Meshroom** (AliceVision) | Windows / Linux | Open-source fallback. **Requires an NVIDIA CUDA GPU** (no CPU fallback). Exports OBJ, converted to `.glb` for the viewer. |

**Selection order** (`auto`): macOS → RealityKit; Windows/Linux → RealityScan if installed, else Meshroom. If none is found, the Reconstruct tab explains how to install one.

> **Note on Meshroom + GPU:** Meshroom's depth-map stage is CUDA-only. On a machine without an NVIDIA GPU, install **RealityScan** instead (it runs on any modern Windows GPU). Confirm your competition machine's GPU before relying on Meshroom.

## Running from source

macOS / Linux:

```bash
git clone https://github.com/akvaithi/MATE-ROV-Photogrammetry.git
cd MATE-ROV-Photogrammetry
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Windows (PowerShell):

```powershell
git clone https://github.com/akvaithi/MATE-ROV-Photogrammetry.git
cd MATE-ROV-Photogrammetry
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Python 3.12 is recommended. Then install a reconstruction engine for your platform (see [Reconstruction backends](#reconstruction-backends)).

## Building the .app

```bash
./build_app.sh           # clean rebuild + zip the bundle
./build_app.sh --no-zip  # build only
```

Output: `dist/Photogrammetry Studio.app` and `dist/PhotogrammetryStudio-macOS.zip`.

> `build_app.sh` targets macOS. On Windows, run from source (above) or package with PyInstaller directly (`pyinstaller PhotogrammetryStudio.spec`).

The build uses PyInstaller with a small runtime hook ([pyinstaller_hooks/pyi_rth_cv2.py](pyinstaller_hooks/pyi_rth_cv2.py)) that works around a known cv2-on-macOS-bundle import recursion. The in-app 3D preview shows a native thumbnail (macOS Quick Look) and the **Open** button hands off to the OS's own 3D viewer for interactive rotation — so no heavy 3D library (pyvista/VTK) is bundled and preview works fully offline, keeping the app lean.

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
       └─ select_backend(config) ──▶ RealityKit | RealityScan | Meshroom ──▶ model.usdz / model.glb
```

| Path | Role |
|---|---|
| [app/core/stream_worker.py](app/core/stream_worker.py) | RTSP capture loop with auto-reconnect |
| [app/core/stream_health.py](app/core/stream_health.py) | Drop / latency detection, logging, and stream metrics |
| [app/core/capture_engine.py](app/core/capture_engine.py) | Quality-gated frame capture, runs on its own thread |
| [app/core/quality_assessor.py](app/core/quality_assessor.py) | Sharpness, novelty, and ML-based framing score |
| [app/core/reconstruction/base.py](app/core/reconstruction/base.py) | Backend contract + shared stage-progress helpers |
| [app/core/reconstruction/registry.py](app/core/reconstruction/registry.py) | Auto-selects the backend for the platform |
| [app/core/reconstruction/realitykit_pipeline.py](app/core/reconstruction/realitykit_pipeline.py) | macOS: drives the Swift Object Capture helper |
| [app/core/reconstruction/realityscan_pipeline.py](app/core/reconstruction/realityscan_pipeline.py) | Windows: drives the RealityScan CLI headless |
| [app/core/reconstruction/meshroom_pipeline.py](app/core/reconstruction/meshroom_pipeline.py) | Win/Linux: drives meshroom_batch (needs CUDA) |
| [app/ui/widgets/model_viewer.py](app/ui/widgets/model_viewer.py) | Cross-platform preview + OS-native open/reveal |
| [app/ui/main_window.py](app/ui/main_window.py) | Owns all workers and signal routing |

## Stream health & logging

The RTSP ingest is instrumented for **dropped frames and high latency**: drops,
reconnects, and inter-frame stalls are detected, shown live on the Stream tab,
and logged to `~/.photogrammetry/logs/` (a rotating app log plus a per-run
`stream_health_*.jsonl` for analysis). Thresholds live in `app/config.py`
(`stream_latency_warn_ms`, `stream_health_log`). Full write-up:
[docs/RTSP-Pipeline.md](docs/RTSP-Pipeline.md).

## Platform & roadmap

**Cross-platform** — the reconstruction engine is a pluggable backend selected per
platform (RealityKit on macOS, RealityScan or Meshroom on Windows/Linux), so the
whole capture-to-mesh pipeline runs natively on the competition machine. No shared
Mac build node is required anymore.

Open follow-ups:

- **Metric scale.** Photogrammetry meshes are scale-ambiguous. If the ROV task
  needs real-world measurements, add a known-size reference marker in-scene and
  scale the output against it.
- **Fully-offline embedded WebGL viewer.** Interactive rotation currently hands off
  to the OS 3D viewer (seamless and offline). An embedded three.js/`QWebEngineView`
  viewer would keep rotation inside the app; it needs a vendored (offline) three.js
  asset to avoid a CDN dependency at the poolside.
- A native **Swift/SwiftUI rewrite** remains deferred: the app works, the team works
  in Python, and RTSP ingest — one line with OpenCV — is non-trivial in Swift
  (AVFoundation can't play RTSP).

## License

MIT — see source headers.
