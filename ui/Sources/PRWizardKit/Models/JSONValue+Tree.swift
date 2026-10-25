import Foundation

extension JSONValue {
    /// The tree of `value`, its keys in the order `encode(to:)` writes them.
    public init(encoding value: some Encodable) throws {
        let node = EncodingNode()
        try value.encode(to: ValueEncoder(node: node))
        self = node.value
    }

    /// Decodes `self` into `type`. Types that keep an object's key order read it from the source tree.
    public func decoded<Value: Decodable>(_ type: Value.Type, using decoder: JSONDecoder = JSONDecoder()) throws
        -> Value
    {
        decoder.userInfo[.sourceTree] = self
        return try decoder.decode(type, from: data)
    }

    public subscript(path: [String]) -> JSONValue? {
        guard let key = path.first else { return self }
        guard case .object(let object) = self else { return nil }
        return object[key]?[Array(path.dropFirst())]
    }

    /// Objects merge, everything else replaces: `pr_wizard.config.merge`.
    public static func merged(_ base: JSONValue, _ over: JSONValue) -> JSONValue {
        guard case .object(let base) = base, case .object(let over) = over else { return over }
        return .object(base.merging(over) { merged($0, $1) })
    }

    var nullPaths: [[String]] {
        switch self {
        case .null: [[]]
        case .object(let object): object.flatMap { key, value in value.nullPaths.map { [key] + $0 } }
        default: []
        }
    }

    func setting(_ value: JSONValue?, at path: [String]) -> JSONValue {
        guard let key = path.first else { return value ?? .null }
        var object = if case .object(let object) = self { object } else { JSONObject() }
        object[key] =
            path.count == 1 ? value : (object[key] ?? .object([:])).setting(value, at: Array(path.dropFirst()))
        return .object(object)
    }
}
