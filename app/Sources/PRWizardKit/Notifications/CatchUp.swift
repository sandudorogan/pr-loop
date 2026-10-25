public enum CatchUp {
    public static func plan(_ page: EventPage, in snapshot: QueueSnapshot) -> [NotificationOp] {
        let ready = Dictionary(
            snapshot.items.filter { $0.group == .ready }.map { ($0.key, $0.head) }, uniquingKeysWith: { $1 })
        return LivePlan.plan(page) { ready[$0.key] == $0.head }
    }
}
