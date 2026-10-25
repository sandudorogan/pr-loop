public protocol OpenEnum: Codable, Hashable, Sendable {
    static var known: [Self] { get }
    static func unknown(_ rawValue: String) -> Self
    var rawValue: String { get }
}

extension OpenEnum {
    public init(rawValue: String) {
        self = Self.known.first { $0.rawValue == rawValue } ?? .unknown(rawValue)
    }

    public init(from decoder: any Decoder) throws {
        try self.init(rawValue: decoder.singleValueContainer().decode(String.self))
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}
