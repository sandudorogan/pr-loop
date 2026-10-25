import SwiftUI

extension FocusedValues {
    private struct QueueFocusKey: FocusedValueKey {
        typealias Value = QueueFocus
    }

    var queueFocus: QueueFocus? {
        get { self[QueueFocusKey.self] }
        set { self[QueueFocusKey.self] = newValue }
    }
}
