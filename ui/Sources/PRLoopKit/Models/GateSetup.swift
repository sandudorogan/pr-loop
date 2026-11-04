public struct GateSetup: Codable, Hashable, Sendable {
    public var name: String
    public var run: String
    public var unknown: JSONObject

    enum CodingKeys: String, CodingKey, CaseIterable {
        case name, run
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(name, forKey: .name)
        try container.encode(run, forKey: .run)
        try encoder.encode(unknownKeys: unknown)
    }
}

extension GateSetup {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        run = try container.decode(String.self, forKey: .run)
        unknown = try decoder.unknownKeys(besides: CodingKeys.self)
    }
}
