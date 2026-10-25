import Foundation

public struct ActiveRun: Codable, Hashable, Sendable {
    public let lane: Lane
    public let since: Date
    public let reviewers: [ReviewerProgress]?
}
