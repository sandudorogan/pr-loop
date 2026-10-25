extension ReviewerResult {
    public var label: String {
        switch self {
        case .posted: "Findings"
        case .notesOnly: "Notes only"
        case .clean: "Clean"
        case .skipped: "Skipped: no conventions"
        case .failed: "Failed"
        case .limited: "Usage limit"
        case .unknown(let value): value
        }
    }
}
