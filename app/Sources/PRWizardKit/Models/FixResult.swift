import Foundation

public struct FixResult: Codable, Hashable, Sendable {
    public let sha: String
    public let isCurrent: Bool
    public let status: String
    public let note: String
    public let errors: Int
    public let isParked: Bool
    public let at: Date

    enum CodingKeys: String, CodingKey {
        case sha, status, note, errors, at
        case isCurrent = "current"
        case isParked = "parked"
    }
}
