/// Builds a `JSONValue` from an `Encodable`, keeping the order the type writes its keys in.
final class EncodingNode {
    enum Shape {
        case leaf(JSONValue)
        case object, array
    }

    var shape = Shape.leaf(.null)
    private var children: [(key: String, node: EncodingNode)] = []

    var value: JSONValue {
        switch shape {
        case .leaf(let value): value
        case .object: .object(JSONObject(children.map { ($0.key, $0.node.value) }))
        case .array: .array(children.map(\.node.value))
        }
    }

    func child(_ key: String = "") -> EncodingNode {
        let node = EncodingNode()
        children.append((key, node))
        return node
    }
}

struct ValueEncoder: Encoder {
    let node: EncodingNode
    var codingPath: [any CodingKey] { [] }
    var userInfo: [CodingUserInfoKey: Any] { [:] }

    func container<Key: CodingKey>(keyedBy _: Key.Type) -> KeyedEncodingContainer<Key> {
        if case .object = node.shape {} else { node.shape = .object }
        return KeyedEncodingContainer(KeyedSink<Key>(node: node))
    }

    func unkeyedContainer() -> any UnkeyedEncodingContainer {
        node.shape = .array
        return UnkeyedSink(node: node)
    }

    func singleValueContainer() -> any SingleValueEncodingContainer { SingleSink(node: node) }
}

extension EncodingNode {
    fileprivate func put(_ value: JSONValue) { shape = .leaf(value) }
}

private struct KeyedSink<Key: CodingKey>: KeyedEncodingContainerProtocol {
    let node: EncodingNode
    var codingPath: [any CodingKey] { [] }

    private func put(_ value: JSONValue, _ key: Key) { node.child(key.stringValue).put(value) }

    mutating func encodeNil(forKey key: Key) throws { put(.null, key) }
    mutating func encode(_ value: Bool, forKey key: Key) throws { put(.bool(value), key) }
    mutating func encode(_ value: String, forKey key: Key) throws { put(.string(value), key) }
    mutating func encode(_ value: Double, forKey key: Key) throws { put(.number(value), key) }
    mutating func encode(_ value: Float, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: Int, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: Int8, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: Int16, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: Int32, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: Int64, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: UInt, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: UInt8, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: UInt16, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: UInt32, forKey key: Key) throws { put(.number(Double(value)), key) }
    mutating func encode(_ value: UInt64, forKey key: Key) throws { put(.number(Double(value)), key) }

    mutating func encode<Value: Encodable>(_ value: Value, forKey key: Key) throws {
        try value.encode(to: ValueEncoder(node: node.child(key.stringValue)))
    }

    mutating func nestedContainer<Nested: CodingKey>(keyedBy type: Nested.Type, forKey key: Key)
        -> KeyedEncodingContainer<Nested>
    { ValueEncoder(node: node.child(key.stringValue)).container(keyedBy: type) }

    mutating func nestedUnkeyedContainer(forKey key: Key) -> any UnkeyedEncodingContainer {
        ValueEncoder(node: node.child(key.stringValue)).unkeyedContainer()
    }

    mutating func superEncoder() -> any Encoder { ValueEncoder(node: node.child("super")) }
    mutating func superEncoder(forKey key: Key) -> any Encoder { ValueEncoder(node: node.child(key.stringValue)) }
}

private struct UnkeyedSink: UnkeyedEncodingContainer {
    let node: EncodingNode
    var codingPath: [any CodingKey] { [] }
    var count = 0

    init(node: EncodingNode) { self.node = node }

    private mutating func put(_ value: JSONValue) {
        node.child().put(value)
        count += 1
    }

    mutating func encodeNil() throws { put(.null) }
    mutating func encode(_ value: Bool) throws { put(.bool(value)) }
    mutating func encode(_ value: String) throws { put(.string(value)) }
    mutating func encode(_ value: Double) throws { put(.number(value)) }
    mutating func encode(_ value: Float) throws { put(.number(Double(value))) }
    mutating func encode(_ value: Int) throws { put(.number(Double(value))) }
    mutating func encode(_ value: Int8) throws { put(.number(Double(value))) }
    mutating func encode(_ value: Int16) throws { put(.number(Double(value))) }
    mutating func encode(_ value: Int32) throws { put(.number(Double(value))) }
    mutating func encode(_ value: Int64) throws { put(.number(Double(value))) }
    mutating func encode(_ value: UInt) throws { put(.number(Double(value))) }
    mutating func encode(_ value: UInt8) throws { put(.number(Double(value))) }
    mutating func encode(_ value: UInt16) throws { put(.number(Double(value))) }
    mutating func encode(_ value: UInt32) throws { put(.number(Double(value))) }
    mutating func encode(_ value: UInt64) throws { put(.number(Double(value))) }

    mutating func encode<Value: Encodable>(_ value: Value) throws {
        try value.encode(to: ValueEncoder(node: node.child()))
        count += 1
    }

    mutating func nestedContainer<Nested: CodingKey>(keyedBy type: Nested.Type) -> KeyedEncodingContainer<Nested> {
        count += 1
        return ValueEncoder(node: node.child()).container(keyedBy: type)
    }

    mutating func nestedUnkeyedContainer() -> any UnkeyedEncodingContainer {
        count += 1
        return ValueEncoder(node: node.child()).unkeyedContainer()
    }

    mutating func superEncoder() -> any Encoder { ValueEncoder(node: node.child()) }
}

private struct SingleSink: SingleValueEncodingContainer {
    let node: EncodingNode
    var codingPath: [any CodingKey] { [] }

    mutating func encodeNil() throws { node.put(.null) }
    mutating func encode(_ value: Bool) throws { node.put(.bool(value)) }
    mutating func encode(_ value: String) throws { node.put(.string(value)) }
    mutating func encode(_ value: Double) throws { node.put(.number(value)) }
    mutating func encode(_ value: Float) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: Int) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: Int8) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: Int16) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: Int32) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: Int64) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: UInt) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: UInt8) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: UInt16) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: UInt32) throws { node.put(.number(Double(value))) }
    mutating func encode(_ value: UInt64) throws { node.put(.number(Double(value))) }
    mutating func encode<Value: Encodable>(_ value: Value) throws { try value.encode(to: ValueEncoder(node: node)) }
}
