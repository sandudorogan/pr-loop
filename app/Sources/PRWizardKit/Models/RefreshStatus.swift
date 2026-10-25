import Foundation

public struct RefreshStatus: Codable, Hashable, Sendable {
    public let interval: Int?
    public let idle: Int?
    public let lastAt: Date?
    public let lastError: String?

    enum CodingKeys: String, CodingKey {
        case interval = "interval_s"
        case idle = "idle_s"
        case lastAt = "last_at"
        case lastError = "last_error"
    }
}
