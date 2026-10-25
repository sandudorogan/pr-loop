public struct ConventionsLine: Hashable, Sendable {
    public struct Row: Hashable, Sendable {
        public enum Kind: String, Sendable {
            case files = "Follows"
            case skills = "Skills"
        }

        public let kind: Kind
        public let shown: [String]
        public let hidden: [String]

        public var title: String { kind.rawValue }

        init(_ kind: Kind, _ items: [String], limit: Int) {
            self.kind = kind
            shown = Array(items.prefix(limit))
            hidden = Array(items.dropFirst(limit))
        }
    }

    public let rows: [Row]
    public let ref: String?
    public let sentence: String?

    public init?(_ scope: SettingsScope, project: Project?, skipped: [String] = [], limit: Int = 3) {
        guard case .project = scope else {
            self.init(
                rows: [], ref: nil,
                sentence: "Each repo's own AGENTS.md, CLAUDE.md, contributing docs and formatter configs, "
                    + "read at the PR head.")
            return
        }
        guard let conventions = project?.conventions else { return nil }
        guard !conventions.files.isEmpty else {
            let sentence = (["Follows nothing documented."] + Self.skips(skipped)).joined(separator: " ")
            self.init(rows: [], ref: nil, sentence: sentence)
            return
        }
        let rows = [Row(.files, conventions.files, limit: limit), Row(.skills, conventions.skills, limit: limit)]
        self.init(rows: rows.filter { !$0.shown.isEmpty }, ref: conventions.ref, sentence: nil)
    }

    private init(rows: [Row], ref: String?, sentence: String?) {
        self.rows = rows
        self.ref = ref
        self.sentence = sentence
    }

    private static func skips(_ ids: [String]) -> [String] {
        guard let last = ids.last else { return [] }
        let names = ids.count == 1 ? last : "\(ids.dropLast().joined(separator: ", ")) and \(last)"
        return ["The \(names) reviewer\(ids.count == 1 ? " is" : "s are") skipped here (no-conventions)."]
    }
}
