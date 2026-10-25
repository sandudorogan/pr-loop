/// An optional that encodes `nil` as an explicit JSON `null`, so a decoded document re-encodes to the same tree.
@propertyWrapper
public struct Nullable<Value: Codable & Hashable & Sendable>: Codable, Hashable, Sendable {
    public var wrappedValue: Value?

    public init(wrappedValue: Value?) {
        self.wrappedValue = wrappedValue
    }

    public init(from decoder: any Decoder) throws {
        wrappedValue = try decoder.singleValueContainer().decode(Value?.self)
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(wrappedValue)
    }
}

extension KeyedDecodingContainer {
    func decode<Value>(_ type: Nullable<Value>.Type, forKey key: Key) throws -> Nullable<Value> {
        try decodeIfPresent(type, forKey: key) ?? Nullable(wrappedValue: nil)
    }
}
