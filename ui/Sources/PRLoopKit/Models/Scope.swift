import Foundation

/// The scope lane's result (api.md §3.2 `scope`): what the PR changes, told blind to its text, and the judge's verdict.
public struct Scope: Codable, Hashable, Sendable {
    public let status: ScopeStatus
    public let head: String?
    public let isCurrent: Bool
    public let error: String?
    public let at: Date
    public let verdict: ScopeVerdict?
    public let reason: String?
    public let intent: String?
    public let stated: String?
    public let changes: [ScopeChange]
    public let touches: [ScopeTouch]

    enum CodingKeys: String, CodingKey {
        case status, head, error, at, verdict, reason, intent, stated, changes, touches
        case isCurrent = "current"
    }
}

public struct ScopeChange: Codable, Hashable, Sendable {
    public let kind: String
    public let area: String
    public let what: String
    public let files: [String]
    public let isInScope: Bool
    public let note: String

    enum CodingKeys: String, CodingKey {
        case kind, area, what, files, note
        case isInScope = "in_scope"
    }
}

public struct ScopeTouch: Codable, Hashable, Sendable {
    public let kind: String
    public let what: String
    public let files: [String]
}

public enum ScopeVerdict: OpenEnum {
    case focused, someCreep, sprawling
    case unknown(String)

    public static let known: [Self] = [.focused, .someCreep, .sprawling]

    public var rawValue: String {
        switch self {
        case .focused: "focused"
        case .someCreep: "some-creep"
        case .sprawling: "sprawling"
        case .unknown(let value): value
        }
    }
}

public enum ScopeStatus: OpenEnum {
    case running, ready, failed, limited
    case unknown(String)

    public static let known: [Self] = [.running, .ready, .failed, .limited]

    public var rawValue: String {
        switch self {
        case .running: "running"
        case .ready: "ready"
        case .failed: "failed"
        case .limited: "limited"
        case .unknown(let value): value
        }
    }
}
