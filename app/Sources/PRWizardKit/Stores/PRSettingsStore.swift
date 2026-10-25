import Observation

/// One PR's override, edited live: every change is one `PATCH` against the last response's `rev`.
@MainActor @Observable public final class PRSettingsStore {
    public private(set) var pr: PRRef?
    public private(set) var config: PRConfig?
    public private(set) var isGone = false
    public private(set) var isWriting = false
    public private(set) var wasReloaded = false
    public private(set) var problems: [APIErrorBody.Problem] = []
    public private(set) var failure: (any Error)?

    private let daemon: any DaemonAPI

    public init(daemon: any DaemonAPI) {
        self.daemon = daemon
    }

    public var markers: PRMarkers? {
        guard let pr, let config else { return nil }
        return PRMarkers(repo: pr.repo, config: config)
    }

    public func show(_ pr: PRRef) async {
        if pr != self.pr {
            self.pr = pr
            config = nil
            isGone = false
            wasReloaded = false
            problems = []
        }
        await load(pr)
    }

    public func set(_ path: String, to value: JSONValue) async {
        await patch([path: value])
    }

    public func setReviewers(_ reviewers: [ReviewerConfig]) async {
        guard let list = try? JSONValue(encoding: reviewers) else { return }
        await set("review.reviewers", to: list)
    }

    /// Merge-patch deletes: the paths fall back to the project or the defaults.
    public func useDefault(_ paths: [String]) async {
        await patch(Dictionary(uniqueKeysWithValues: paths.map { ($0, JSONValue.null) }))
    }

    public func useDefaults() async {
        guard let pr else { return }
        await write(pr) { try await self.daemon.deletePRConfig(pr) }
    }

    public func messages(at path: String) -> [String] {
        problems.filter { $0.path == path || $0.path.hasPrefix("\(path).") || $0.path.hasPrefix("\(path)[") }
            .map(\.message)
    }

    private func patch(_ values: [String: JSONValue]) async {
        guard let pr, let rev = config?.rev else { return }
        let patch = values.sorted { $0.key < $1.key }.reduce(JSONValue.null) {
            $0.setting($1.value, at: OverrideResolver.path($1.key))
        }
        await write(pr) { try await self.daemon.patchPRConfig(pr, patch, baseRev: rev) }
    }

    private func write(_ pr: PRRef, _ request: () async throws -> PRConfig) async {
        guard !isWriting else { return }
        isWriting = true
        defer { isWriting = false }
        wasReloaded = false
        do {
            accept(try await request(), for: pr)
        } catch APIError.http(_, "stale_config", _, _) {
            await load(pr)
            wasReloaded = true
        } catch APIError.http(_, "invalid_config", _, let details) {
            problems = details
        } catch {
            fail(error, for: pr)
        }
    }

    private func load(_ pr: PRRef) async {
        do {
            accept(try await daemon.prConfig(pr), for: pr)
        } catch {
            fail(error, for: pr)
        }
    }

    private func accept(_ config: PRConfig, for pr: PRRef) {
        guard pr == self.pr else { return }
        self.config = config
        problems = []
        failure = nil
    }

    private func fail(_ error: any Error, for pr: PRRef) {
        guard pr == self.pr, !(error is CancellationError) else { return }
        switch error {
        case APIError.http(404, "not_in_queue", _, _), APIError.http(404, "unknown_repo", _, _):
            isGone = true
            config = nil
        default:
            failure = error
        }
    }
}
