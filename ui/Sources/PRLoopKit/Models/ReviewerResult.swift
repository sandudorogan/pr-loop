public enum ReviewerResult: OpenEnum {
    case posted, notesOnly, clean, skipped, failed, limited
    case unknown(String)

    public static let known: [Self] = [.posted, .notesOnly, .clean, .skipped, .failed, .limited]

    public var rawValue: String {
        switch self {
        case .posted: "posted"
        case .notesOnly: "notes-only"
        case .clean: "clean"
        case .skipped: "skipped"
        case .failed: "failed"
        case .limited: "limited"
        case .unknown(let value): value
        }
    }
}
