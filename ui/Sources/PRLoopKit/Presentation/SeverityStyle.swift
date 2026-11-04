public struct SeverityStyle: Hashable, Sendable {
    public let symbol: String
    public let tone: Tone
    public let label: String

    public init(_ severity: Severity) {
        (symbol, tone) =
            switch severity {
            case .critical: ("exclamationmark.octagon.fill", .bad)
            case .high: ("exclamationmark.triangle.fill", .attention)
            case .medium: ("exclamationmark.circle.fill", .caution)
            case .low: ("info.circle", .neutral)
            case .unknown: ("questionmark.circle", .neutral)
            }
        label = severity.rawValue
    }
}
