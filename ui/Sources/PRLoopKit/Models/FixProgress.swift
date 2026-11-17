import Foundation

/// A live fix pass (api.md §3.2 `active.fix`): its step and the feedback it works on.
public struct FixProgress: Codable, Hashable, Sendable {
    public let step: FixStep
    public let since: Date
    public let isConflict: Bool
    public let items: [FixItem]

    enum CodingKeys: String, CodingKey {
        case step, since, items
        case isConflict = "conflict"
    }
}

public struct FixItem: Codable, Hashable, Sendable {
    public let kind: FixItemKind
    public let title: String
    public let author: String?
    public let path: String?
    public let line: Int?
}

public enum FixStep: OpenEnum {
    case collecting, merging, fixing, testing, pushing
    case unknown(String)

    public static let known: [Self] = [.collecting, .merging, .fixing, .testing, .pushing]

    public var rawValue: String {
        switch self {
        case .collecting: "collecting"
        case .merging: "merging"
        case .fixing: "fixing"
        case .testing: "testing"
        case .pushing: "pushing"
        case .unknown(let value): value
        }
    }
}

public enum FixItemKind: OpenEnum {
    case thread, review, comment, ci
    case unknown(String)

    public static let known: [Self] = [.thread, .review, .comment, .ci]

    public var rawValue: String {
        switch self {
        case .thread: "thread"
        case .review: "review"
        case .comment: "comment"
        case .ci: "ci"
        case .unknown(let value): value
        }
    }
}
