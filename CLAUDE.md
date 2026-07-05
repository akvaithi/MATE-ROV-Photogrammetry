# Photogrammetry Studio

A PyQt6 desktop app that turns an **RTSP video stream** into a 3D model: it
watches the stream, captures frames that pass quality gates (sharp, novel,
well-framed), and reconstructs a mesh via a **pluggable, auto-selected
reconstruction backend**. The whole pipeline is **cross-platform** (Windows,
macOS, Linux); the engine is chosen for the machine at runtime by
`app/core/reconstruction/registry.py`:

- **macOS** → RealityKit (Apple Object Capture), Swift helper → `model.usdz`
- **Windows** → RealityScan (Epic, free) preferred → `model.glb`
- **Windows/Linux** → Meshroom (AliceVision) fallback, **needs NVIDIA CUDA** → `model.glb`

All backends implement the same contract in `app/core/reconstruction/base.py`
(`is_available()`, `run(image_dir, output_path, progress_cb)`, `name`,
`output_suffix`) and share the five UI stage bars via `emit_stage_progress`.
COLMAP was removed earlier; the classic SfM/MVS stage names it left behind are
what every backend now maps onto.

Built for the MATE ROV competition (Team Oceanus / GNC). This repo is also a git
**submodule** inside `ThinkTank-TAMU/TAMU-Oceanus` at
`01_Subteams/GNC/Photogrammetry-App` — commit here and push to this repo's own
remote (`akvaithi/MATE-ROV-Photogrammetry`), then bump the pointer in the team repo.

## Run / build

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # 3.12 recommended
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
   └─ select_backend(config) ─▶ RealityKit | RealityScan | Meshroom ─▶ model.usdz / model.glb
```

| Path | Role |
|---|---|
| `app/core/stream_worker.py` | RTSP capture loop, reconnect logic |
| `app/core/capture_engine.py` | Quality-gated capture (own thread) |
| `app/core/quality_assessor.py` | Sharpness / novelty / framing scoring |
| `app/core/reconstruction/base.py` | Backend `Protocol` + shared stage-progress helpers |
| `app/core/reconstruction/registry.py` | `select_backend` / `available_backend_names` (platform auto-select) |
| `app/core/reconstruction/realitykit_pipeline.py` | macOS: Swift `PhotogrammetrySession` helper, JSON progress |
| `app/core/reconstruction/realityscan_pipeline.py` | Windows: RealityScan CLI headless, stdout phase-cue progress |
| `app/core/reconstruction/meshroom_pipeline.py` | Win/Linux: `meshroom_batch`, CUDA check, OBJ→GLB via trimesh |
| `app/ui/widgets/model_viewer.py` | Cross-platform preview + OS-native open/reveal |
| `app/ui/main_window.py` | Owns all workers + signal routing |
| `app/config.py`, `app/state.py` | Settings + shared app state |

Sessions write to `~/photogrammetry_sessions/session_<timestamp>/`; output is
`model.usdz` (RealityKit) or `model.glb` (RealityScan / Meshroom). Config field
`reconstruction_backend` (`auto` default) can force a specific engine;
`reconstruction_detail` (was `realitykit_detail`, still read for back-compat)
sets Preview→Raw; `realityscan_exe` / `meshroom_bin` override engine paths.

## Conventions & gotchas

- **Python 3.12** is the target. Backends shell out to external engines rather than
  linking libraries: RealityKit compiles a Swift helper on first run (macOS + Xcode
  CLT); RealityScan / Meshroom are located on `PATH` / known install dirs / a config
  override (`realityscan_exe`, `meshroom_bin`). Only Meshroom's OBJ→GLB step needs a
  Python dep (`trimesh`).
- **Meshroom is CUDA-only** — `MeshroomPipeline.is_available()` requires an NVIDIA
  GPU (via `nvidia-smi`); it fails fast otherwise. RealityScan runs on any modern
  Windows GPU and is the preferred Windows backend.
- **Progress**: RealityKit streams a 0..1 fraction; RealityScan/Meshroom don't, so
  they infer stage transitions from stdout keyword cues (`_PHASE_CUES` / `_NODE_CUES`)
  and still finish with `complete_all_stages`. CLI command specifics can drift between
  RealityScan versions — that's the most likely place to need tuning.
- PyInstaller build uses a runtime hook (`pyinstaller_hooks/pyi_rth_cv2.py`) for a
  cv2-on-macOS import recursion. The 3D preview (`app/ui/widgets/model_viewer.py`)
  shows a native thumbnail (macOS Quick Look) and delegates interactive rotation to
  the OS 3D viewer (`os.startfile` / `qlmanage -p` / `xdg-open`) — no Python 3D lib,
  works offline.
- The app is not codesigned — first launch on macOS needs right-click → Open.

## Platform & direction

**Cross-platform.** Reconstruction is a pluggable backend chosen per platform, so
the full pipeline runs natively on Windows/macOS/Linux — no shared Mac build node.
To add an engine, implement the `base.ReconstructionBackend` contract and register
it in `registry.py`.

A full **Swift/SwiftUI rewrite was considered and deferred**: the app already
works and the team lives in Python. The key constraint if it's ever revisited is
that **RTSP ingest is the blocker** — OpenCV does it in one line, but AVFoundation
can't play RTSP, so a native build needs VLCKit or a bundled FFmpeg. The remaining
native-ish nicety is a **fully-offline embedded WebGL viewer** (vendored three.js in
`QWebEngineView`) to keep model rotation inside the app instead of handing off to the
OS viewer.

## GNC 3-week plan status

Goal 3 (*refine the RTSP-to-3D pipeline: error logging for stream drops / high
latency + performance metrics*) is **done** — see `app/core/stream_health.py`,
`stream_worker.py`, and [docs/RTSP-Pipeline.md](docs/RTSP-Pipeline.md). This was
the last open item in `3_Week Plan.md` (Project 3); Goals 1 & 2 (SITL sim + servo
control) live in the parent GNC folder.
