import Foundation

extension FixProgress {
    /// The Fixing badge's tooltip: the step, then one line per piece of feedback.
    public var help: String {
        let count = items.count + (isConflict ? 1 : 0)
        let header = count == 0 ? step.label : "\(step.label) · \(count) \(count == 1 ? "item" : "items")"
        let conflict = isConflict ? ["• Merge conflict with the base"] : []
        return ([header] + conflict + items.map { "• \($0.help)" }).joined(separator: "\n")
    }
}

extension FixStep {
    public var label: String {
        switch self {
        case .collecting: "Reading the feedback"
        case .merging: "Merging the base"
        case .fixing: "Codex is fixing"
        case .testing: "Running the gates"
        case .pushing: "Pushing and replying"
        case .unknown(let value): value
        }
    }
}

extension FixItem {
    var help: String {
        let file = path.map { URL(fileURLWithPath: $0).lastPathComponent + (line.map { ":\($0)" } ?? "") }
        let source = [author, file].compactMap(\.self).joined(separator: ", ")
        let what = kind == .ci ? "CI job \(title) failed" : title
        return source.isEmpty ? what : "\(what) (\(source))"
    }
}
