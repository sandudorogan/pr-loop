public enum GateKind: OpenEnum {
    case format, test
    case unknown(String)

    public static let known: [Self] = [.format, .test]

    public var rawValue: String {
        switch self {
        case .format: "format"
        case .test: "test"
        case .unknown(let value): value
        }
    }
}
