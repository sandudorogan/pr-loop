public struct ScopeStyle: Hashable, Sendable {
    public let symbol: String
    public let tone: Tone
    public let label: String

    public init(_ verdict: ScopeVerdict) {
        (symbol, tone, label) =
            switch verdict {
            case .focused: ("circle.fill", .good, "Focused")
            case .someCreep: ("circle.lefthalf.filled", .attention, "Some creep")
            case .sprawling: ("xmark.circle.fill", .bad, "Sprawling")
            case .unknown(let value): ("questionmark.circle", .neutral, value)
            }
    }
}

extension Scope {
    public var style: ScopeStyle? { verdict.map(ScopeStyle.init) }

    public var outOfScope: [ScopeChange] { changes.filter { !$0.isInScope } }

    /// Why the verdict shown is not a fresh one for this head, or nil when it is.
    public var note: String? {
        switch status {
        case .running: verdict == nil ? "Summarizing the diff…" : "Updating for the new head…"
        case .failed: "Summary failed"
        case .limited: "Codex is at its usage limit, retrying"
        case .ready, .unknown: isCurrent ? nil : "Summary of an older head"
        }
    }

    /// The list badge's tooltip.
    public var help: String { [reason, note, error].compactMap(\.self).joined(separator: "\n") }
}

extension ScopeChange {
    public var mark: String {
        switch kind {
        case "added": "+"
        case "modified": "~"
        case "removed": "−"
        default: "·"
        }
    }

    public var help: String { ([area] + files).joined(separator: "\n") }
}

extension ScopeTouch {
    public var help: String { ([what] + files).joined(separator: "\n") }
}
