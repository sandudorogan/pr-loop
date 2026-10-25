/// A JSON object that keeps its keys in source order, so a config edit rewrites only what changed.
///
/// Equality ignores the order, as JSON and Python's `dict ==` do.
public struct JSONObject: Sendable {
    public typealias Element = (key: String, value: JSONValue)

    private var entries: [Element] = []

    public init() {}

    /// Later duplicates replace the value and keep the first position, as `json.loads` does.
    public init(_ pairs: some Sequence<(String, JSONValue)>) {
        for (key, value) in pairs { self[key] = value }
    }

    public var count: Int { entries.count }
    public var isEmpty: Bool { entries.isEmpty }
    public var keys: [String] { entries.map(\.key) }
    public var values: [JSONValue] { entries.map(\.value) }

    public subscript(key: String) -> JSONValue? {
        get { entries.first { $0.key == key }?.value }
        set {
            let index = entries.firstIndex { $0.key == key }
            switch (index, newValue) {
            case (let index?, let value?): entries[index].value = value
            case (let index?, nil): entries.remove(at: index)
            case (nil, let value?): entries.append((key, value))
            case (nil, nil): break
            }
        }
    }

    /// Keys of `self` keep their place, new keys of `other` follow in their order.
    public func merging(_ other: JSONObject, uniquingKeysWith combine: (JSONValue, JSONValue) -> JSONValue)
        -> JSONObject
    {
        var out = self
        for (key, value) in other { out[key] = out[key].map { combine($0, value) } ?? value }
        return out
    }
}

extension JSONObject: Sequence {
    public func makeIterator() -> IndexingIterator<[Element]> { entries.makeIterator() }
}

extension JSONObject: Hashable {
    public static func == (lhs: JSONObject, rhs: JSONObject) -> Bool {
        lhs.entries.count == rhs.entries.count && lhs.entries.allSatisfy { rhs[$0.key] == $0.value }
    }

    public func hash(into hasher: inout Hasher) {
        for (key, value) in entries.sorted(by: { $0.key < $1.key }) {
            hasher.combine(key)
            hasher.combine(value)
        }
    }
}

extension JSONObject: ExpressibleByDictionaryLiteral {
    public init(dictionaryLiteral elements: (String, JSONValue)...) { self.init(elements) }
}

extension JSONObject: Codable {
    /// Under `JSONDecoder` and `JSONEncoder` the key order is lost: use `JSONValue(parsing:)`, `data` and
    /// `JSONValue.decoded(_:)`, which carry it.
    public init(from decoder: any Decoder) throws {
        if case .object(let source)? = decoder.sourceValue {
            self = source
            return
        }
        let container = try decoder.container(keyedBy: AnyKey.self)
        self.init(try container.allKeys.map { ($0.stringValue, try container.decode(JSONValue.self, forKey: $0)) })
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: AnyKey.self)
        for (key, value) in self { try container.encode(value, forKey: AnyKey(stringValue: key)) }
    }
}
