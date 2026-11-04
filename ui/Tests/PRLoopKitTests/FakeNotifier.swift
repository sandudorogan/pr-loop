import PRLoopKit

actor FakeNotifier: Notifier {
    struct Failure: Error {}

    private var status: NotificationAuthorization
    private let granted: NotificationAuthorization
    private let cursor: MemoryCursor?
    private var failingIDs: Set<String> = []
    private(set) var requests = 0
    private(set) var posts: [ReadyNotification] = []
    private(set) var cursorsAtPost: [String?] = []
    private(set) var removes: [String] = []

    init(
        _ status: NotificationAuthorization = .authorized, granted: NotificationAuthorization = .authorized,
        cursor: MemoryCursor? = nil
    ) {
        self.status = status
        self.granted = granted
        self.cursor = cursor
    }

    func fail(_ id: String) {
        failingIDs.insert(id)
    }

    func authorization() -> NotificationAuthorization { status }

    func requestAuthorization() -> NotificationAuthorization {
        requests += 1
        status = granted
        return status
    }

    func post(_ notification: ReadyNotification) throws {
        if failingIDs.remove(notification.id) != nil { throw Failure() }
        posts.append(notification)
        cursorsAtPost.append(cursor?.lastSeen())
    }

    func removeDelivered(key: String) {
        removes.append(key)
    }
}
