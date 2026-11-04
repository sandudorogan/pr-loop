public struct Prompt: Codable, Hashable, Sendable {
    public let name: String
    public let path: String
    public let placeholders: [String]
    public let text: String
}
