public struct PRRef: Codable, Hashable, Identifiable, Sendable {
    public let repo: String
    public let number: Int

    public init(repo: String, number: Int) {
        self.repo = repo
        self.number = number
    }

    public var id: String { "\(repo)#\(number)" }
}
