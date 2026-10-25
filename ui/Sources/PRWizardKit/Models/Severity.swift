public enum Severity: OpenEnum {
    case critical, high, medium, low
    case unknown(String)

    public static let known: [Self] = [.critical, .high, .medium, .low]

    public var rawValue: String {
        switch self {
        case .critical: "critical"
        case .high: "high"
        case .medium: "medium"
        case .low: "low"
        case .unknown(let value): value
        }
    }
}
