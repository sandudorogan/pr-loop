import Foundation

public struct ReviewerProgress: Codable, Hashable, Identifiable, Sendable {
    public let id: String
    public let state: ReviewerState
    public let attempt: Int
    public let since: Date
}
