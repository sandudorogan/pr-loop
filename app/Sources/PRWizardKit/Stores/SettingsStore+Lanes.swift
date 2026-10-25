extension SettingsStore {
    public var isSeparate: Bool { resolve("lanes.separate", in: .allRepos).value == .bool(true) }

    public func lanesLayout(in scope: SettingsScope, projects: [Project]) -> LanesLayout {
        LanesLayout(
            scope: scope, isSeparate: isSeparate, project: projects.first { SettingsScope.project($0.repo) == scope },
            isReviewOn: resolve("review.enabled", in: scope).value == .bool(true),
            isFixOn: resolve("fix.enabled", in: scope).value == .bool(true))
    }

    public func workerTotals(projects: [Project]) -> WorkerTotals {
        WorkerTotals(draft: draft, projects: projects)
    }

    /// A number setting shown in another unit: `per` 60 reads seconds as minutes.
    public func int(_ key: String, in scope: SettingsScope, per unit: Int = 1) -> Int {
        (resolve(key, in: scope).value.int ?? 0) / unit
    }

    public func setInt(_ key: String, to value: Int, in scope: SettingsScope, per unit: Int = 1) {
        set(key, to: .number(Double(value * unit)), in: scope)
    }

    public func strings(_ key: String, in scope: SettingsScope) -> [String] {
        resolve(key, in: scope).value.strings
    }

    public func setStrings(_ key: String, to value: [String], in scope: SettingsScope) {
        set(key, to: .array(value.map { .string($0) }), in: scope)
    }
}
