public struct ConfigStatus: Codable, Hashable, Sendable {
    public let path: String
    public let realPath: String
    public let rev: String
    public let error: String?

    enum CodingKeys: String, CodingKey {
        case path, rev, error
        case realPath = "real_path"
    }
}
