struct AnyKey: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }

    init(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}

extension Decoder {
    /// The keys of the current object that `Key` does not name, so a newer daemon's knobs survive an edit.
    func unknownKeys<Key: CodingKey & CaseIterable>(besides _: Key.Type) throws -> [String: JSONValue] {
        let known = Set(Key.allCases.map(\.stringValue))
        return try singleValueContainer().decode([String: JSONValue].self).filter { !known.contains($0.key) }
    }
}

extension Encoder {
    func encode(unknownKeys: [String: JSONValue]) throws {
        var container = self.container(keyedBy: AnyKey.self)
        for (key, value) in unknownKeys { try container.encode(value, forKey: AnyKey(stringValue: key)) }
    }
}
