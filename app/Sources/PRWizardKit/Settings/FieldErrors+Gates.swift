extension FieldErrors {
    public struct GateProblem: Hashable, Sendable {
        public let index: Int?
        public let field: String
        public let message: String
    }

    /// The 422 problems under `fix.gates` in one scope, split into the gate's index and the field inside it.
    public func gates(in scope: SettingsScope) -> [GateProblem] {
        problems.compactMap { problem in
            let (owner, key) = SettingsScope.split(problem.path)
            guard owner == scope, key.hasPrefix("fix.gates") else { return nil }
            let rest = key.dropFirst("fix.gates".count)
            guard rest.hasPrefix("["), let end = rest.firstIndex(of: "]") else {
                return GateProblem(index: nil, field: "", message: problem.message)
            }
            return GateProblem(
                index: Int(rest[rest.index(after: rest.startIndex)..<end]),
                field: String(rest[rest.index(after: end)...].drop { $0 == "." }), message: problem.message)
        }
    }
}
