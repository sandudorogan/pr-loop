public struct GateTargets: Codable, Hashable, Sendable {
    public var map: [[String]]?
    public var keep: String?
    public var exists: Bool?
    /// Applied in order, as `gates.items` does: a later pair sees the result of an earlier one.
    public var item: [StringPair]?
    public var valid: String?
    public var unknown: JSONObject

    enum CodingKeys: String, CodingKey, CaseIterable {
        case map, keep, exists, item, valid
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(map, forKey: .map)
        try container.encodeIfPresent(keep, forKey: .keep)
        try container.encodeIfPresent(exists, forKey: .exists)
        try container.encodeIfPresent(
            item.map { JSONObject($0.map { ($0.from, JSONValue.string($0.to)) }) }, forKey: .item)
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
        item = try container.decodeIfPresent(JSONObject.self, forKey: .item).map {
            $0.compactMap { pair in pair.value.string.map { StringPair(from: pair.key, to: $0) } }
        }
        valid = try container.decodeIfPresent(String.self, forKey: .valid)
        unknown = try decoder.unknownKeys(besides: CodingKeys.self)
    }
}
