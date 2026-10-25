/// The `details` of a 422 `invalid_config`, looked up by scope and key.
public struct FieldErrors: Hashable, Sendable {
    public let problems: [APIErrorBody.Problem]

    public init(_ problems: [APIErrorBody.Problem] = []) {
        self.problems = problems
    }

    public var isEmpty: Bool { problems.isEmpty }

    public func messages(at key: String, in scope: SettingsScope) -> [String] {
        problems.filter { $0.path == scope.path(of: key) }.map(\.message)
    }

    public func contains(_ scope: SettingsScope) -> Bool {
        problems.contains { SettingsScope.split($0.path).scope == scope }
    }

    /// Problems in the scope that none of the shown keys, or the fields inside them, claim: the pane banner.
    public func unclaimed(in scope: SettingsScope, by keys: [String]) -> [APIErrorBody.Problem] {
        problems.filter { problem in
            let (owner, key) = SettingsScope.split(problem.path)
            return owner == scope && !keys.contains { key == $0 || key.hasPrefix("\($0).") || key.hasPrefix("\($0)[") }
        }
    }
}

extension FieldErrors {
    /// Messages at the key itself or at an element of it (`review.trivial[2]`).
    public func messages(within key: String, in scope: SettingsScope) -> [String] {
        let path = scope.path(of: key)
        return problems.filter { $0.path == path || $0.path.hasPrefix("\(path)[") }.map(\.message)
    }
}
