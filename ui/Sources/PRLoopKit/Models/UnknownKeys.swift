struct AnyKey: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }

    init(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}

extension CodingUserInfoKey {
    static let sourceTree: CodingUserInfoKey = {
        guard let key = CodingUserInfoKey(rawValue: "sourceTree") else { fatalError("a non-empty raw value is a key") }
        return key
    }()
}

extension Decoder {
    /// The part of the source tree this decoder reads, when `JSONValue.decoded(_:)` started from one.
    ///
    /// `JSONDecoder` hands out object keys in no order, so a type that must keep the order reads it here.
    var sourceValue: JSONValue? {
        guard var node = userInfo[.sourceTree] as? JSONValue else { return nil }
        for key in codingPath {
            switch node {
            case .object(let object):
                guard let next = object[key.stringValue] else { return nil }
                node = next
            case .array(let array):
                guard let index = key.intValue, array.indices.contains(index) else { return nil }
                node = array[index]
            default:
                return nil
            }
        }
        return node
    }

    /// The keys of the current object that `Key` does not name, so a newer daemon's knobs survive an edit.
    func unknownKeys<Key: CodingKey & CaseIterable>(besides _: Key.Type) throws -> JSONObject {
        let known = Set(Key.allCases.map(\.stringValue))
        return JSONObject(try singleValueContainer().decode(JSONObject.self).filter { !known.contains($0.key) })
    }
}

extension Encoder {
    func encode(unknownKeys: JSONObject) throws {
        var container = self.container(keyedBy: AnyKey.self)
        for (key, value) in unknownKeys { try container.encode(value, forKey: AnyKey(stringValue: key)) }
    }
}
