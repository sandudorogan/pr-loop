public enum Engine: OpenEnum {
    case claude, codex
    case unknown(String)

    public static let known: [Self] = [.claude, .codex]

    public var rawValue: String {
        switch self {
        case .claude: "claude"
        case .codex: "codex"
        case .unknown(let value): value
        }
    }
}
