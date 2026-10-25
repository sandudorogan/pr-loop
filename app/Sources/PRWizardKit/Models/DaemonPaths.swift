public struct DaemonPaths: Codable, Hashable, Sendable {
    public let socket: String
    public let state: String
    public let db: String
    public let log: String
}
