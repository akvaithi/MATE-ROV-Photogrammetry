# Photogrammetry Studio

A PyQt6 desktop app (macOS, Apple Silicon) that turns an **RTSP video stream**
into a 3D model: it watches the stream, captures frames that pass quality gates
(sharp, novel, well-framed), and reconstructs a mesh with **Apple Object Capture
(RealityKit)** — the only backend. COLMAP support was removed in favour of
RealityKit's quality; reconstruction is therefore **macOS-only** (the capture
half is cross-platform).

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
   └─ RealityKitPipeline ─▶ swiftc helper ─▶ PhotogrammetrySession ─▶ model.usdz
```

| Path | Role |
|---|---|
| `app/core/stream_worker.py` | RTSP capture loop, reconnect logic |
| `app/core/capture_engine.py` | Quality-gated capture (own thread) |
| `app/core/quality_assessor.py` | Sharpness / novelty / framing scoring |
| `app/core/reconstruction/realitykit_pipeline.py` | Drives the Swift helper, parses JSON progress |
| `app/core/reconstruction/realitykit_helper.swift` | CLI around `PhotogrammetrySession` |
| `app/ui/main_window.py` | Owns all workers + signal routing |
| `app/config.py`, `app/state.py` | Settings + shared app state |

Sessions write to `~/photogrammetry_sessions/session_<timestamp>/`; output is
`model.usdz` (RealityKit).

## Conventions & gotchas

- **Python 3.12** is the target. Reconstruction (RealityKit) needs no Python deps —
  just macOS + Xcode CLT (`xcode-select --install`); the Swift helper compiles on
  first run. There is no non-Mac reconstruction path (COLMAP was removed).
- PyInstaller build uses a runtime hook (`pyinstaller_hooks/pyi_rth_cv2.py`) for a
  cv2-on-macOS import recursion. The Reconstruct panel's 3D preview renders the
  USDZ via macOS **Quick Look** (`qlmanage -t` for the thumbnail, `qlmanage -p`
  for the interactive viewer) — no Python 3D library, so pyvista/VTK are gone.
- The app is not codesigned — first launch needs right-click → Open.

## Platform & direction

**macOS-only by design** — RealityKit / Object Capture has no Windows/Linux port.
The capture half (RTSP + quality gating) is cross-platform; to drive the app from
Windows, reconstruct on a shared Mac.

A full **Swift/SwiftUI rewrite was considered and deferred**: the app already
works and the team lives in Python. The key constraint if it's ever revisited is
that **RTSP ingest is the blocker** — OpenCV does it in one line, but AVFoundation
can't play RTSP, so a native build needs VLCKit or a bundled FFmpeg. De-risk RTSP
first before committing. The highest-value native step *short* of a rewrite is an
**embedded interactive USDZ viewer** via a small Swift helper (same pattern as the
Object Capture helper), replacing the current Quick Look hand-off.

## GNC 3-week plan status

Goal 3 (*refine the RTSP-to-3D pipeline: error logging for stream drops / high
latency + performance metrics*) is **done** — see `app/core/stream_health.py`,
`stream_worker.py`, and [docs/RTSP-Pipeline.md](docs/RTSP-Pipeline.md). This was
the last open item in `3_Week Plan.md` (Project 3); Goals 1 & 2 (SITL sim + servo
control) live in the parent GNC folder.
