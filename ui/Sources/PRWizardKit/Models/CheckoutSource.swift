public enum CheckoutSource: OpenEnum {
    case detected, config
    case unknown(String)

    public static let known: [Self] = [.detected, .config]

    public var rawValue: String {
        switch self {
        case .detected: "detected"
        case .config: "config"
        case .unknown(let value): value
        }
    }
}
