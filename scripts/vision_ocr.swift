import Foundation
import Vision
import ImageIO

// Page pixels stay on this machine. No model or document is sent to a service.
guard CommandLine.arguments.count == 2 else {
    fputs("Usage: vision-ocr page.png\n", stderr)
    exit(2)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
request.usesLanguageCorrection = true
let handler = VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1]))
do {
    try handler.perform([request])
    let observations = request.results ?? []
    let lines: [[String: Any]] = observations.compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return ["text": candidate.string, "confidence": candidate.confidence,
                "bbox": [b.minX, b.minY, b.width, b.height]]
    }
    let result: [String: Any] = ["text": lines.compactMap { $0["text"] as? String }.joined(separator: "\n"), "lines": lines]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch {
    fputs("Local text recognition failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
