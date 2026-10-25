extension JSONValue: ExpressibleByBooleanLiteral, ExpressibleByIntegerLiteral, ExpressibleByStringLiteral {
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(integerLiteral value: Int) { self = .number(Double(value)) }
    public init(stringLiteral value: String) { self = .string(value) }
}

extension JSONValue: ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral {
    public init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
    public init(dictionaryLiteral elements: (String, JSONValue)...) {
        self = .object(JSONObject(elements))
    }
}
