extension SettingsStore {
    public func scopeOptions(for projects: [ProjectSummary]) -> [ScopeOption] {
        let roots = original?.config.detect.roots ?? []
        return [.allRepos] + projects.map { ScopeOption($0, overrides: draft.overrideCount(in: $0.id), roots: roots) }
    }
}
