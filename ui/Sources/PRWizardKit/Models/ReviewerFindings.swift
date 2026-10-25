import Foundation

public struct ReviewerFindings: Codable, Hashable, Identifiable, Sendable {
    public let id: String
    public let label: String
    public let result: ReviewerResult
    public let engine: String
    public let counts: SeverityCounts
    public let atFloor: Int
    public let top: [TopFinding]
    public let url: URL?
    public let at: Date

    enum CodingKeys: String, CodingKey {
        case id, label, result, engine, counts, top, url, at
        case atFloor = "at_floor"
    }
}
