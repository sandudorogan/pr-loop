import Foundation

/// A JSON parser and writer that keep object keys in order: `JSONDecoder` and `JSONEncoder` do not.
extension JSONValue {
    public init(parsing data: Data) throws {
        var parser = JSONParser(Array(data))
        self = try parser.document()
    }

    public var data: Data {
        var out = [UInt8]()
        write(to: &out)
        return Data(out)
    }

    private func write(to out: inout [UInt8]) {
        switch self {
        case .null: out += Array("null".utf8)
        case .bool(let value): out += Array((value ? "true" : "false").utf8)
        case .number(let value):
            let whole = value.rounded() == value && abs(value) < 1e15
            out += Array((whole ? String(Int(value)) : "\(value)").utf8)
        case .string(let value): Self.write(value, to: &out)
        case .array(let values):
            out.append(UInt8(ascii: "["))
            for (index, value) in values.enumerated() {
                if index > 0 { out.append(UInt8(ascii: ",")) }
                value.write(to: &out)
            }
            out.append(UInt8(ascii: "]"))
        case .object(let object):
            out.append(UInt8(ascii: "{"))
            for (index, (key, value)) in object.enumerated() {
                if index > 0 { out.append(UInt8(ascii: ",")) }
                Self.write(key, to: &out)
                out.append(UInt8(ascii: ":"))
                value.write(to: &out)
            }
            out.append(UInt8(ascii: "}"))
        }
    }

    private static let escapes: [UInt8: String] = [
        UInt8(ascii: "\""): "\\\"", UInt8(ascii: "\\"): "\\\\", 10: "\\n", 13: "\\r", 9: "\\t",
    ]

    private static func write(_ string: String, to out: inout [UInt8]) {
        out.append(UInt8(ascii: "\""))
        for byte in string.utf8 {
            if let escape = escapes[byte] {
                out += Array(escape.utf8)
            } else if byte < 0x20 {
                out += Array(String(format: "\\u%04x", byte).utf8)
            } else {
                out.append(byte)
            }
        }
        out.append(UInt8(ascii: "\""))
    }
}

private struct JSONParser {
    private let bytes: [UInt8]
    private var index = 0

    init(_ bytes: [UInt8]) { self.bytes = bytes }

    mutating func document() throws -> JSONValue {
        let value = try value()
        skipSpace()
        guard index == bytes.count else { throw failure("trailing text") }
        return value
    }

    private func failure(_ reason: String) -> DecodingError {
        .dataCorrupted(.init(codingPath: [], debugDescription: "\(reason) at byte \(index)"))
    }

    private mutating func skipSpace() {
        while index < bytes.count, [0x20, 0x09, 0x0a, 0x0d].contains(bytes[index]) { index += 1 }
    }

    private mutating func take(_ char: Character) throws {
        skipSpace()
        guard index < bytes.count, bytes[index] == char.asciiValue else { throw failure("expected \(char)") }
        index += 1
    }

    private mutating func consume(_ char: Character) -> Bool {
        skipSpace()
        guard index < bytes.count, bytes[index] == char.asciiValue else { return false }
        index += 1
        return true
    }

    private mutating func value() throws -> JSONValue {
        skipSpace()
        guard let byte = bytes[safe: index] else { throw failure("unexpected end") }
        switch byte {
        case UInt8(ascii: "{"): return try object()
        case UInt8(ascii: "["): return try array()
        case UInt8(ascii: "\""): return .string(try string())
        case UInt8(ascii: "t"): return try word("true", .bool(true))
        case UInt8(ascii: "f"): return try word("false", .bool(false))
        case UInt8(ascii: "n"): return try word("null", .null)
        default: return try number()
        }
    }

    private mutating func word(_ word: String, _ value: JSONValue) throws -> JSONValue {
        guard bytes[index...].starts(with: Array(word.utf8)) else { throw failure("unexpected word") }
        index += word.utf8.count
        return value
    }

    private mutating func number() throws -> JSONValue {
        let start = index
        while index < bytes.count, "+-0123456789.eE".utf8.contains(bytes[index]) { index += 1 }
        guard let number = Double(String(decoding: bytes[start..<index], as: UTF8.self)) else {
            throw failure("unexpected character")
        }
        return .number(number)
    }

    private mutating func array() throws -> JSONValue {
        try take("[")
        var values = [JSONValue]()
        if consume("]") { return .array(values) }
        repeat { values.append(try value()) } while consume(",")
        try take("]")
        return .array(values)
    }

    private mutating func object() throws -> JSONValue {
        try take("{")
        var object = JSONObject()
        if consume("}") { return .object(object) }
        repeat {
            skipSpace()
            let key = try string()
            try take(":")
            object[key] = try value()
        } while consume(",")
        try take("}")
        return .object(object)
    }

    private mutating func string() throws -> String {
        guard bytes[safe: index] == UInt8(ascii: "\"") else { throw failure("expected a string") }
        index += 1
        var out = [UInt8]()
        while let byte = bytes[safe: index] {
            index += 1
            switch byte {
            case UInt8(ascii: "\""): return String(decoding: out, as: UTF8.self)
            case UInt8(ascii: "\\"): out += try escape()
            default: out.append(byte)
            }
        }
        throw failure("unterminated string")
    }

    private mutating func escape() throws -> [UInt8] {
        guard let byte = bytes[safe: index] else { throw failure("unterminated string") }
        index += 1
        switch byte {
        case UInt8(ascii: "n"): return [10]
        case UInt8(ascii: "t"): return [9]
        case UInt8(ascii: "r"): return [13]
        case UInt8(ascii: "b"): return [8]
        case UInt8(ascii: "f"): return [12]
        case UInt8(ascii: "u"): return Array(String(decoding: try units(), as: UTF16.self).utf8)
        default: return [byte]
        }
    }

    private mutating func units() throws -> [UInt16] {
        let first = try unit()
        guard (0xD800..<0xDC00).contains(first), bytes[safe: index] == UInt8(ascii: "\\"),
            bytes[safe: index + 1] == UInt8(ascii: "u")
        else { return [first] }
        index += 2
        return [first, try unit()]
    }

    private mutating func unit() throws -> UInt16 {
        guard index + 4 <= bytes.count,
            let unit = UInt16(String(decoding: bytes[index..<index + 4], as: UTF8.self), radix: 16)
        else { throw failure("bad \\u escape") }
        index += 4
        return unit
    }
}

extension Array {
    fileprivate subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}
