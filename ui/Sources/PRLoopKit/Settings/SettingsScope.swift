import Foundation

public enum SettingsScope: Hashable, Sendable {
    case allRepos
    case project(String)

    var root: [String] {
        switch self {
        case .allRepos: []
        case .project(let repo): ["projects", repo]
        }
    }

    /// The path the daemon names in a 422 detail: `review.workers`, `projects["owner/name"].review.workers`.
    public func path(of key: String) -> String {
        switch self {
        case .allRepos: key
        case .project(let repo): "projects[\"\(repo)\"].\(key)"
        }
    }

    static func split(_ path: String) -> (scope: SettingsScope, key: String) {
        let prefix = "projects[\""
        guard path.hasPrefix(prefix), let end = path.range(of: "\"].") else { return (.allRepos, path) }
        return (
            .project(String(path[path.index(path.startIndex, offsetBy: prefix.count)..<end.lowerBound])),
            String(path[end.upperBound...])
        )
    }
}

extension SettingsScope: RawRepresentable {
    public init(rawValue: String) {
        self = rawValue.isEmpty ? .allRepos : .project(rawValue)
    }

    public var rawValue: String {
        switch self {
        case .allRepos: ""
        case .project(let repo): repo
        }
    }
}
