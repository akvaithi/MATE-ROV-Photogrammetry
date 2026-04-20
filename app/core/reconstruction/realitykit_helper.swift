// realitykit_helper.swift
// Wraps RealityKit's PhotogrammetrySession (Apple Object Capture) as a CLI,
// emitting one JSON status line per progress/event so the parent Python
// process can track the run.
//
// Usage: realitykit_helper <input_dir> <output.usdz> [detail]
//   detail: preview | reduced | medium | full | raw  (default: medium)

import Foundation
import RealityKit

func emit(_ obj: [String: Any]) {
    guard
        let data = try? JSONSerialization.data(withJSONObject: obj, options: []),
        let s = String(data: data, encoding: .utf8)
    else { return }
    print(s)
    fflush(stdout)
}

func parseDetail(_ s: String) -> PhotogrammetrySession.Request.Detail {
    switch s.lowercased() {
    case "preview": return .preview
    case "reduced": return .reduced
    case "medium":  return .medium
    case "full":    return .full
    case "raw":     return .raw
    default:        return .medium
    }
}

let args = CommandLine.arguments
guard args.count >= 3 else {
    FileHandle.standardError.write(
        "usage: realitykit_helper <input_dir> <output.usdz> [detail]\n"
            .data(using: .utf8)!
    )
    exit(2)
}

let inputDir  = URL(fileURLWithPath: args[1])
let outputURL = URL(fileURLWithPath: args[2])
let detail    = parseDetail(args.count >= 4 ? args[3] : "medium")

let sem = DispatchSemaphore(value: 0)
var finalExit: Int32 = 0

Task {
    do {
        var config = PhotogrammetrySession.Configuration()
        config.featureSensitivity = .high
        config.sampleOrdering = .unordered

        let session = try PhotogrammetrySession(input: inputDir, configuration: config)
        let request = PhotogrammetrySession.Request.modelFile(url: outputURL, detail: detail)
        try session.process(requests: [request])

        for try await event in session.outputs {
            switch event {
            case .processingComplete:
                emit(["type": "complete"])
                finalExit = 0
                sem.signal()
                return

            case .requestProgress(_, fractionComplete: let f):
                emit(["type": "progress", "fraction": f])

            case .requestComplete(_, _):
                emit(["type": "request_complete"])

            case .requestError(_, let err):
                emit(["type": "error", "message": "\(err)"])
                finalExit = 3
                sem.signal()
                return

            case .processingCancelled:
                emit(["type": "cancelled"])
                finalExit = 4
                sem.signal()
                return

            case .invalidSample(id: _, reason: let r):
                emit(["type": "warn", "message": "invalid sample: \(r)"])

            case .skippedSample(id: _):
                emit(["type": "warn", "message": "skipped sample"])

            case .inputComplete:
                emit(["type": "info", "message": "input complete"])

            case .automaticDownsampling:
                emit(["type": "warn", "message": "automatic downsampling"])

            case .stitchingIncomplete:
                emit(["type": "warn", "message": "stitching incomplete"])

            default:
                // Covers OS-specific cases (e.g. .requestProgressInfo on
                // macOS 14+) without failing to compile on older SDKs.
                break
            }
        }
        sem.signal()
    } catch {
        emit(["type": "error", "message": "\(error)"])
        finalExit = 5
        sem.signal()
    }
}

sem.wait()
exit(finalExit)
