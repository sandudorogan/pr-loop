/// Where a PR's effective value comes from: the `layers` of its config, then its labels on top.
public struct PRMarkers: Hashable, Sendable {
    public enum Source: Hashable, Sendable {
        case `default`
        case project(String)
        case pr
        case label(String)
    }

    public static let labels = ["review.enabled": "no-auto-review", "fix.enabled": "no-auto-fix"]

    public let repo: String
    public let config: PRConfig

    public init(repo: String, config: PRConfig) {
        self.repo = repo
        self.config = config
    }

    public var overridden: [String] { config.layers.pr }

    /// The strongest source among the paths: a list or a section is marked once for everything under it.
    public func source(of path: String) -> Source {
        source(of: [path])
    }

    public func source(of paths: [String]) -> Source {
        if let label = paths.compactMap({ Self.labels[$0] }).first(where: config.labels.contains) {
            return .label(label)
        }
        if paths.contains(where: { Self.sets(config.layers.pr, $0) }) { return .pr }
        if paths.contains(where: { Self.sets(config.layers.project, $0) }) { return .project(repo) }
        return .default
    }

    public func overridden(within paths: [String]) -> [String] {
        overridden.filter { leaf in paths.contains { Self.sets([leaf], $0) } }
    }

    private static func sets(_ leaves: [String], _ path: String) -> Bool {
        leaves.contains { $0 == path || $0.hasPrefix("\(path).") }
    }
}
