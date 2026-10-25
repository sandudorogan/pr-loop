import Foundation

extension JSONValue {
    public init(encoding value: some Encodable) throws {
        self = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
    }

    public func decoded<Value: Decodable>(_ type: Value.Type) throws -> Value {
        try JSONDecoder().decode(type, from: JSONEncoder().encode(self))
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
        var object = if case .object(let object) = self { object } else { [String: JSONValue]() }
        object[key] =
            path.count == 1 ? value : (object[key] ?? .object([:])).setting(value, at: Array(path.dropFirst()))
        return .object(object)
    }
}
