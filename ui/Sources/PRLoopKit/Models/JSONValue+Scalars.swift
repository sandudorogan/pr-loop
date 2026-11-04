extension JSONValue {
    public var int: Int? {
        if case .number(let value) = self { Int(exactly: value) } else { nil }
    }

    public var string: String? {
        if case .string(let value) = self { value } else { nil }
    }

    public var strings: [String] {
        if case .array(let values) = self { values.compactMap(\.string) } else { [] }
    }
}
