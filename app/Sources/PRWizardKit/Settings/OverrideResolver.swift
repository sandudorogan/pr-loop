/// Resolves a key over defaults → project on a config tree, the draft, so unsaved edits show at once.
public struct OverrideResolver: Sendable {
    public enum Source: Hashable, Sendable {
        case defaults
        case project(String)
    }

    public struct Resolved: Hashable, Sendable {
        public let value: JSONValue
        public let source: Source
    }

    public let config: JSONValue

    public init(config: JSONValue) {
        self.config = config
    }

    public func resolve(_ key: String, in scope: SettingsScope) -> Resolved {
        let path = Self.path(key)
        let base = config[path] ?? .null
        guard case .project(let repo) = scope, let override = config[scope.root + path] else {
            return Resolved(value: base, source: .defaults)
        }
        return Resolved(value: .merged(base, override), source: .project(repo))
    }

    public func isOverridden(_ key: String, in scope: SettingsScope) -> Bool {
        resolve(key, in: scope).source != .defaults
    }

    public func overrideCount(in repo: String) -> Int {
        guard case .object(let override) = config[SettingsScope.project(repo).root] else { return 0 }
        return override.values.reduce(0) { count, lane in
            if case .object(let keys) = lane { count + keys.count } else { count + 1 }
        }
    }

    func setting(_ key: String, to value: JSONValue, in scope: SettingsScope) -> OverrideResolver {
        OverrideResolver(config: config.setting(value, at: scope.root + Self.path(key)))
    }

    /// Drops the key from the project override and every object it leaves empty, the override included.
    func usingDefault(_ key: String, in scope: SettingsScope) -> OverrideResolver {
        let path = scope.root + Self.path(key)
        var tree = config.setting(nil, at: path)
        for parent in (2..<path.count).reversed().map({ Array(path.prefix($0)) }) where tree[parent] == .object([:]) {
            tree = tree.setting(nil, at: parent)
        }
        return OverrideResolver(config: tree)
    }

    static func path(_ key: String) -> [String] {
        key.split(separator: ".").map(String.init)
    }
}
