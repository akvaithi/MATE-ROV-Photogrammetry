# RTSP-to-3D Pipeline & Performance Metrics

GNC 3-week plan, **Goal 3 — Refine the photogrammetry pipeline**: continuous
processing of an RTSP stream into 3D models with minimal error and dropped
frames, plus documentation of the pipeline and its performance metrics.

This document describes the end-to-end path a video stream takes to become a 3D
model, and the **stream-health instrumentation** added so dropped or laggy
streams are detected, logged, and measurable.

---

## Pipeline overview

```
 RTSP camera ─▶ StreamWorker ─▶ CaptureEngine ─▶ FrameStore ─▶ ReconstructionWorker ─▶ model
 (IP / ROV)     (QThread)        (quality gate)   (JPEGs)       (RealityKit / COLMAP)   (.usdz/.ply)
```

| Stage | Module | Role |
|---|---|---|
| **Ingest** | [`app/core/stream_worker.py`](../app/core/stream_worker.py) | Pulls frames from the RTSP URL via OpenCV/FFmpeg in a blocking loop, with auto-reconnect. Capture buffer pinned to 1 frame for low latency. |
| **Health** | [`app/core/stream_health.py`](../app/core/stream_health.py) | Tracks drops, reconnects, high-latency stalls, and inter-frame timing; logs and persists events. |
| **Quality gate** | [`app/core/capture_engine.py`](../app/core/capture_engine.py) + [`quality_assessor.py`](../app/core/quality_assessor.py) | Keeps only frames that are sharp, novel, and well-framed. |
| **Store** | [`app/core/frame_store.py`](../app/core/frame_store.py) | Writes JPEGs, de-duplicated by Bhattacharyya distance. |
| **Reconstruct** | [`reconstruction/`](../app/core/reconstruction/) | RealityKit (Apple Object Capture → `.usdz`) or COLMAP (SfM+MVS → `.ply`). |

Each worker runs on its own thread and communicates with the UI through Qt
signals — the main thread never touches OpenCV or the network directly.

---

## Stream health: drops & latency

The ingest stage is where the stream can fail, so that's where the
instrumentation lives. `StreamWorker` feeds lifecycle events to a
`StreamHealthMonitor`, which both **logs** them and accumulates **metrics**.

### What is detected

| Condition | How it's detected | Logged as |
|---|---|---|
| **Stream drop** | `cap.read()` returns no frame mid-stream → the worker releases and reconnects | `WARNING` + `drop` event (with how long it had been connected) |
| **High latency / stall** | Wall-clock gap between two decoded frames ≥ `stream_latency_warn_ms` (default **1500 ms**) | `WARNING` + `high_latency` event (with the gap in ms) |
| **Failed reconnect** | A reopen attempt fails | `WARNING` + `open_failed` event |
| **Reconnected** | Capture reopens after a drop | `SUCCESS` + `connected` event (`reconnect: true`) |
| **Fatal** | `MAX_OPEN_ATTEMPTS` (5) consecutive failed opens | `ERROR` + `fatal` event |

> Why inter-frame gap = latency: with the capture buffer set to 1 frame, the
> blocking `cap.read()` returns only when the next frame is available, so the gap
> between successful reads tracks how long the pipeline waited on the stream. A
> gap far above the nominal frame period means the stream stalled or the network
> backed up.

### Metrics captured (`StreamStats`)

Emitted to the UI on every state change and once per second, and written as a
`summary` event when the stream stops:

| Field | Meaning |
|---|---|
| `frames_total` | frames successfully decoded |
| `drops` | mid-stream read failures (each forces a reconnect) |
| `reconnects` | connections re-established after a drop |
| `stalls` | inter-frame gaps over the latency threshold |
| `avg_fps` | frames ÷ connected time |
| `uptime_s` / `downtime_s` | cumulative connected vs disconnected time |
| `last_gap_ms` / `max_gap_ms` / `avg_gap_ms` | inter-frame latency, current / worst / mean |

The Stream tab shows a live summary line:
`drops 0 · reconnects 0 · stalls 0 · latency 33/120 ms (now/max)` — it turns
amber once the stream has had any trouble in the session.

---

## Where the logs go

| Sink | Path | Contents |
|---|---|---|
| **App log** (rotating) | `~/.photogrammetry/logs/app_YYYY-MM-DD.log` | All app logging, incl. every drop / latency warning. Rotates at 5 MB, kept 14 days. Configured in [`main.py`](../main.py). |
| **Stream-health log** (per run) | `~/.photogrammetry/logs/stream_health_<timestamp>.jsonl` | One JSON object per event (`connected`, `drop`, `high_latency`, `open_failed`, `reconnecting`, `fatal`, `summary`). Machine-readable for analysis. |

Example `stream_health_*.jsonl` lines:

```json
{"ts": 1719500000.12, "event": "connected", "reconnect": false}
{"ts": 1719500037.41, "event": "high_latency", "gap_ms": 2310.5}
{"ts": 1719500052.88, "event": "drop", "reason": "read_failed", "uptime_s": 52.7}
{"ts": 1719500061.02, "event": "summary", "frames_total": 1583, "drops": 1, "reconnects": 1, "stalls": 3, ...}
```

A run's reliability is then a one-liner over the summary event (drops, stalls,
uptime/downtime, worst latency) — that's the performance-metrics record for the
test report.

---

## Configuration

In `~/.photogrammetry/config.json` (see [`app/config.py`](../app/config.py)):

| Key | Default | Effect |
|---|---|---|
| `stream_latency_warn_ms` | `1500.0` | Inter-frame gap that counts as a high-latency stall. |
| `stream_health_log` | `true` | Write the per-run JSONL health log. |
| `stream_reconnect_delay` | `2.0` | Seconds to wait between reconnect attempts. |
| `stream_buffer_size` | `1` | OpenCV capture buffer; keep at 1 for low latency. |

---

## Verifying it

- **Drop:** stop the RTSP source (or pull the camera) mid-session → expect a
  `drop` warning, the status dot turning amber/red, then `reconnecting` and a
  `connected (reconnect)` once the source returns.
- **Latency:** throttle the network or feed a stuttering source → gaps over the
  threshold log `high_latency` and bump the `stalls` counter.
- The monitor's counting logic is covered by a standalone simulation test
  (connect → frames → stall → drop → reconnect → summary).

---

## On the ROV (later)

The same instrumentation applies unchanged when the source is the ROV's camera
over the tether instead of a desk IP camera — drops and latency on the tether
will surface in exactly these logs and metrics, which is what makes this useful
for diagnosing a real dive.
