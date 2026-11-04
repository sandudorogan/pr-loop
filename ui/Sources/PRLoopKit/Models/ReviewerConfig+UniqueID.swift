extension ReviewerConfig {
    static let maxIDLength = 32

    /// `<id>-2`, `<id>-3`, … : the first free one, cut to the daemon's 32 characters.
    static func uniqueID(from id: String, among ids: Set<String>) -> String {
        let candidate = { (n: Int) in String(id.prefix(maxIDLength - "-\(n)".count)) + "-\(n)" }
        var n = 2
        while ids.contains(candidate(n)) { n += 1 }
        return candidate(n)
    }
}
