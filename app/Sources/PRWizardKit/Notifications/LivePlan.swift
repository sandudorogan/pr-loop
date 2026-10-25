public enum LivePlan {
    public static func plan(_ page: EventPage) -> [NotificationOp] {
        plan(page) { _ in true }
    }

    static func plan(_ page: EventPage, postingIf isPostable: (DaemonEvent) -> Bool) -> [NotificationOp] {
        Dictionary(grouping: page.events.filter { EventType.known.contains($0.type) }, by: \.key).values
            .compactMap { $0.max { $0.seq < $1.seq } }
            .sorted { $0.seq < $1.seq }
            .compactMap { event in
                switch event.type {
                case .readyForApproval where isPostable(event): .post(ReadyNotification(event))
                case .readyWithdrawn: .remove(key: event.key)
                default: nil
                }
            }
    }
}
