public enum ActionAvailability: Hashable, Sendable {
    case available
    case unavailable(String)

    public var isAvailable: Bool { self == .available }

    public var reason: String? {
        guard case .unavailable(let reason) = self else { return nil }
        return reason
    }

    public static func all(_ availabilities: [Self]) -> Self {
        availabilities.first { !$0.isAvailable } ?? .available
    }

    public static func moveToFront(_ item: QueueItem) -> Self {
        if item.active != nil { return .unavailable("In a live run") }
        return [.queued, .idle].contains(item.group) ? .available : .unavailable("Only queued or waiting PRs move")
    }

    public static func review(_ item: QueueItem, in projects: [Project]) -> Self {
        let project = projects.first { $0.repo == item.repo }
        if item.active != nil { return .unavailable("In a live run") }
        if project?.isAvailable != true { return .unavailable("No usable checkout of \(item.repo)") }
        if project?.isReviewEnabled != true { return .unavailable("The review lane is off for \(item.repo)") }
        return .available
    }

    public static func fix(_ item: QueueItem, in projects: [Project]) -> Self {
        let project = projects.first { $0.repo == item.repo }
        if item.active != nil { return .unavailable("In a live run") }
        if !item.isMine { return .unavailable("Only your own PRs get fixes") }
        if item.labels.contains("no-auto-fix") { return .unavailable("Labeled no-auto-fix") }
        if project?.isAvailable != true { return .unavailable("No usable checkout of \(item.repo)") }
        if project?.isFixEnabled != true { return .unavailable("The fix lane is off for \(item.repo)") }
        return .available
    }
}
