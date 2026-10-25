public struct APIErrorBody: Codable, Hashable, Sendable {
    public struct Problem: Codable, Hashable, Sendable {
        public let path: String
        public let message: String
    }

    public struct Detail: Codable, Hashable, Sendable {
        public let code: String
        public let message: String
        public let details: [Problem]?
    }

    public let error: Detail
}
