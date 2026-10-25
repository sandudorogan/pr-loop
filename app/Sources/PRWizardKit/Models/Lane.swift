public enum Lane: OpenEnum {
    case review, fix
    case unknown(String)

    public static let known: [Self] = [.review, .fix]

    public var rawValue: String {
        switch self {
        case .review: "review"
        case .fix: "fix"
        case .unknown(let value): value
        }
    }
}
