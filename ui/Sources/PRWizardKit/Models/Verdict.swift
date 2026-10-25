public enum Verdict: OpenEnum {
    case clean, qualityOnly, posted
    case unknown(String)

    public static let known: [Self] = [.clean, .qualityOnly, .posted]

    public var rawValue: String {
        switch self {
        case .clean: "clean"
        case .qualityOnly: "quality-only"
        case .posted: "posted"
        case .unknown(let value): value
        }
    }
}
