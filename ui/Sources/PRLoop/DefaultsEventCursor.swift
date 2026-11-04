import Foundation
import PRLoopKit

nonisolated struct DefaultsEventCursor: EventCursor {
    func lastSeen() -> String? {
        UserDefaults.standard.string(forKey: AppStorageKey.eventCursor)
    }

    func save(_ cursor: String) {
        UserDefaults.standard.set(cursor, forKey: AppStorageKey.eventCursor)
    }
}
