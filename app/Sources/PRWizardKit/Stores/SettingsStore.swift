import Observation

@MainActor @Observable public final class SettingsStore {
    public private(set) var original: ConfigEnvelope?
    public private(set) var draft = OverrideResolver(config: .null)
    public private(set) var errors = FieldErrors()
    public private(set) var isStale = false
    public private(set) var isApplying = false
    public private(set) var savedTo: String?
    public private(set) var failure: (any Error)?

    private let daemon: any DaemonAPI
    private var base = JSONValue.null

    public init(daemon: any DaemonAPI) {
        self.daemon = daemon
    }

    public var patch: JSONValue? { ConfigPatch.diff(base, draft.config) }
    public var isDirty: Bool { patch != nil }

    public func hasEdits(in scope: SettingsScope) -> Bool {
        guard case .object(let patch) = patch else { return false }
        return switch scope {
        case .allRepos: patch.keys.contains { $0 != "projects" }
        case .project: self.patch?[scope.root] != nil
        }
    }

    public func resolve(_ key: String, in scope: SettingsScope) -> OverrideResolver.Resolved {
        draft.resolve(key, in: scope)
    }

    public func load() async {
        guard original == nil else { return }
        await reload()
    }

    public func reload() async {
        do {
            try accept(await daemon.config())
            savedTo = nil
        } catch {
            failure = error
        }
    }

    public func set(_ key: String, to value: JSONValue, in scope: SettingsScope) {
        edit(draft.setting(key, to: value, in: scope))
    }

    /// Back to the default: the key leaves the project override, and the patch sends it as `null`.
    public func useDefault(_ key: String, in scope: SettingsScope) {
        edit(draft.usingDefault(key, in: scope))
    }

    /// Lists override whole, so leaving the default copies it into the override, and the copy is then edited.
    public func setUsesDefault(_ usesDefault: Bool, for key: String, in scope: SettingsScope) {
        if usesDefault {
            useDefault(key, in: scope)
        } else {
            set(key, to: resolve(key, in: .allRepos).value, in: scope)
        }
    }

    public func revert() {
        draft = OverrideResolver(config: base)
        errors = FieldErrors()
    }

    public func apply() async {
        guard let original, let patch, !isApplying else { return }
        isApplying = true
        defer { isApplying = false }
        do {
            try accept(await daemon.patchConfig(patch, baseRev: original.rev))
            savedTo = self.original?.realPath
        } catch APIError.http(_, "stale_config", _, _) {
            isStale = true
        } catch APIError.http(_, "invalid_config", _, let details) {
            errors = FieldErrors(details)
        } catch {
            failure = error
        }
    }

    private func accept(_ envelope: ConfigEnvelope) throws {
        base = try JSONValue(encoding: envelope.config)
        original = envelope
        draft = OverrideResolver(config: base)
        errors = FieldErrors()
        isStale = false
        failure = nil
    }

    private func edit(_ next: OverrideResolver) {
        draft = next
        savedTo = nil
    }
}
