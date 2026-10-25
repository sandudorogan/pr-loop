public struct GateConfig: Codable, Hashable, Sendable {
    public var name: String
    public var kind: GateKind
    public var when: [String]
    public var run: String
    public var cwd: String?
    public var prelude: String?
    public var requires: String?
    public var needs: [String]?
    public var targets: GateTargets?
    public var setup: GateSetup?
    public var timeout: Int?
    public var usesSlot: Bool?
    public var protect: [String]?
    public var note: String?
    public var unknown: JSONObject

    enum CodingKeys: String, CodingKey, CaseIterable {
        case name, kind, when, run, cwd, prelude, requires, needs, targets, setup, protect, note
        case timeout = "timeout_s"
        case usesSlot = "slot"
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(name, forKey: .name)
        try container.encode(kind, forKey: .kind)
        try container.encode(when, forKey: .when)
        try container.encode(run, forKey: .run)
        try container.encodeIfPresent(cwd, forKey: .cwd)
        try container.encodeIfPresent(prelude, forKey: .prelude)
        try container.encodeIfPresent(requires, forKey: .requires)
        try container.encodeIfPresent(needs, forKey: .needs)
        try container.encodeIfPresent(targets, forKey: .targets)
        try container.encodeIfPresent(setup, forKey: .setup)
        try container.encodeIfPresent(timeout, forKey: .timeout)
        try container.encodeIfPresent(usesSlot, forKey: .usesSlot)
        try container.encodeIfPresent(protect, forKey: .protect)
        try container.encodeIfPresent(note, forKey: .note)
        try encoder.encode(unknownKeys: unknown)
    }
}

extension GateConfig {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decode(String.self, forKey: .name)
        kind = try container.decode(GateKind.self, forKey: .kind)
        when = try container.decode([String].self, forKey: .when)
        run = try container.decode(String.self, forKey: .run)
        cwd = try container.decodeIfPresent(String.self, forKey: .cwd)
        prelude = try container.decodeIfPresent(String.self, forKey: .prelude)
        requires = try container.decodeIfPresent(String.self, forKey: .requires)
        needs = try container.decodeIfPresent([String].self, forKey: .needs)
        targets = try container.decodeIfPresent(GateTargets.self, forKey: .targets)
        setup = try container.decodeIfPresent(GateSetup.self, forKey: .setup)
        timeout = try container.decodeIfPresent(Int.self, forKey: .timeout)
        usesSlot = try container.decodeIfPresent(Bool.self, forKey: .usesSlot)
        protect = try container.decodeIfPresent([String].self, forKey: .protect)
        note = try container.decodeIfPresent(String.self, forKey: .note)
        unknown = try decoder.unknownKeys(besides: CodingKeys.self)
    }
}
