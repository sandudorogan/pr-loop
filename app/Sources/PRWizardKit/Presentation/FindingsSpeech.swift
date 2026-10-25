public struct FindingsSpeech: Hashable, Sendable {
    public let findings: String
    public let atFloor: String
    public let topFinding: String?

    public init(_ digest: Findings) {
        findings = digest.reviewers.isEmpty ? "None" : digest.reviewers.map(Self.line).joined(separator: "; ")
        let count = digest.atFloor == 0 ? "None" : "\(digest.atFloor)"
        atFloor = digest.isCurrent ? count : "\(count), from an older head"
        topFinding = digest.top.first.map { "\($0.severity.rawValue), \($0.title), \($0.location)" }
    }

    private static func line(_ reviewer: ReviewerFindings) -> String {
        let counts = reviewer.counts.nonZero.map { "\($0.count) \($0.severity.rawValue)" }
        let head = "\(reviewer.label), \(reviewer.result.label)"
        return counts.isEmpty ? head : "\(head): " + counts.joined(separator: ", ")
    }
}
