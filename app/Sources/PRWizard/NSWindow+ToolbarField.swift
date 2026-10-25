import AppKit

extension NSWindow {
    /// Focuses the first text field in the toolbar. A `@FocusState` does not reach a toolbar item.
    func focusToolbarField() {
        guard let field = toolbar?.items.lazy.compactMap({ $0.view?.firstTextField }).first else { return }
        makeFirstResponder(field)
    }
}

extension NSView {
    fileprivate var firstTextField: NSTextField? {
        (self as? NSTextField).flatMap { $0.isEditable ? $0 : nil } ?? subviews.lazy.compactMap(\.firstTextField).first
    }
}
