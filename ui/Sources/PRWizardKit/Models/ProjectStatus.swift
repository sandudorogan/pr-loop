public enum ProjectStatus: OpenEnum {
    case active, off, noCheckout, error
    case unknown(String)

    public static let known: [Self] = [.active, .off, .noCheckout, .error]

    public var rawValue: String {
        switch self {
        case .active: "active"
        case .off: "off"
        case .noCheckout: "no-checkout"
        case .error: "error"
        case .unknown(let value): value
        }
    }
}
