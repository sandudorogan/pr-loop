public struct InspectorModel: Hashable, Sendable {
    public let item: QueueItem

    public init(_ item: QueueItem) {
        self.item = item
    }

    public var title: String { "\(ProjectSummary.shortName(of: item.repo)) #\(item.number)" }
    public var head: String { Self.short(item.head) }

    /// The review's most specific word: its verdict when it has one, else its status.
    public var reviewStatus: String? { item.review.map { $0.verdict?.rawValue ?? $0.status } }
    public var reviewedHead: String? { item.review.map { Self.headLine($0.sha, isCurrent: $0.isCurrent) } }
    public var fixedHead: String? { item.fix.map { Self.headLine($0.sha, isCurrent: $0.isCurrent) } }

    public var fixErrors: String? {
        item.fix.map { fix in
            switch fix.errors {
            case 0: "None"
            case 1: "1 failed pass"
            default: "\(fix.errors) failed passes in a row"
            }
        }
    }

    public var reviewLine: String? {
        item.review.map { review in
            let rounds = "\(review.rounds) round\(review.rounds == 1 ? "" : "s") with findings"
            return Self.line(
                reviewedHead, review.rounds > 0 ? rounds : nil, review.isHeld ? "held until a review request" : nil)
        }
    }

    public var fixLine: String? {
        item.fix.map { fix in Self.line(fixedHead, fix.errors > 0 ? fixErrors : nil, fix.isParked ? "parked" : nil) }
    }

    public var lane: String? {
        item.active.map { active in
            switch active.lane {
            case .review: "Review"
            case .fix: "Fix"
            case .unknown(let value): value
            }
        }
    }

    public func reviewerLabel(_ id: String) -> String {
        item.findings?.reviewers.first { $0.id == id }?.label ?? id
    }

    public static func state(_ progress: ReviewerProgress) -> String {
        let state =
            switch progress.state {
            case .running: "Running"
            case .waiting: "Waiting"
            case .posted: "Posted"
            case .clean: "Clean"
            case .failed: "Failed"
            case .limited: "Usage limit"
            case .unknown(let value): value
            }
        return progress.attempt > 1 ? "\(state) · attempt \(progress.attempt)" : state
    }

    public static func short(_ sha: String) -> String { String(sha.prefix(12)) }

    private static func line(_ parts: String?...) -> String {
        parts.compactMap(\.self).joined(separator: " · ")
    }

    private static func headLine(_ sha: String, isCurrent: Bool) -> String {
        isCurrent ? "This head" : "Older head \(short(sha))"
    }
}
