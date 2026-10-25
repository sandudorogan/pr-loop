import SwiftUI

extension FocusedValues {
    private struct PeekFocusKey: FocusedValueKey {
        typealias Value = PeekFocus
    }

    var peekFocus: PeekFocus? {
        get { self[PeekFocusKey.self] }
        set { self[PeekFocusKey.self] = newValue }
    }
}
