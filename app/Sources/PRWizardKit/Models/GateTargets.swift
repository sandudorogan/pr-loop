public struct GateTargets: Codable, Hashable, Sendable {
    public var map: [[String]]?
    public var keep: String?
    public var exists: Bool?
    public var item: [String: String]?
    public var valid: String?
    public var unknown: [String: JSONValue]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case map, keep, exists, item, valid
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(map, forKey: .map)
        try container.encodeIfPresent(keep, forKey: .keep)
        try container.encodeIfPresent(exists, forKey: .exists)
        try container.encodeIfPresent(item, forKey: .item)
        try container.encodeIfPresent(valid, forKey: .valid)
        try encoder.encode(unknownKeys: unknown)
    }
}

extension GateTargets {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        map = try container.decodeIfPresent([[String]].self, forKey: .map)
        keep = try container.decodeIfPresent(String.self, forKey: .keep)
        exists = try container.decodeIfPresent(Bool.self, forKey: .exists)
        item = try container.decodeIfPresent([String: String].self, forKey: .item)
        valid = try container.decodeIfPresent(String.self, forKey: .valid)
        unknown = try decoder.unknownKeys(besides: CodingKeys.self)
    }
}
