import PRWizardKit
import Synchronization

final class MemoryCursor: EventCursor {
    private let saved: Mutex<[String]>
    private let initial: String?

    init(_ initial: String? = nil) {
        self.initial = initial
        saved = Mutex([])
    }

    var saves: [String] { saved.withLock { $0 } }

    func lastSeen() -> String? { saves.last ?? initial }

    func save(_ cursor: String) {
        saved.withLock { $0.append(cursor) }
    }
}
