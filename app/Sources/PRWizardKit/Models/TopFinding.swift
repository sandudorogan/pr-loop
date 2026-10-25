import Foundation

public struct TopFinding: Codable, Hashable, Sendable {
    public let severity: Severity
    public let title: String
    public let file: String
    public let line: Int
    public let reviewer: String?
    public let url: URL?
}
