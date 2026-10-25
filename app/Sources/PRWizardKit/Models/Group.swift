public enum Group: OpenEnum {
    case active, queued, ready, idle
    case unknown(String)

    public static let known: [Self] = [.active, .queued, .ready, .idle]

    public var rawValue: String {
        switch self {
        case .active: "active"
        case .queued: "queued"
        case .ready: "ready"
        case .idle: "idle"
        case .unknown(let value): value
        }
    }
}
