import AppKit
import SwiftUI

/// Edits a list of globs or paths as tokens. A space or comma ends a token, and the draft follows every keystroke.
struct GlobTokenField: NSViewRepresentable {
    let title: String
    var prompt = ""
    @Binding var tokens: [String]

    func makeNSView(context: Context) -> NSTokenField {
        let field = NSTokenField()
        field.tokenizingCharacterSet = CharacterSet(charactersIn: ", ")
        field.placeholderString = prompt
        field.setAccessibilityLabel(title)
        field.delegate = context.coordinator
        return field
    }

    func updateNSView(_ field: NSTokenField, context: Context) {
        context.coordinator.tokens = $tokens
        if field.currentEditor() == nil, field.objectValue as? [String] != tokens { field.objectValue = tokens }
    }

    func makeCoordinator() -> Coordinator { Coordinator(tokens: $tokens) }

    final class Coordinator: NSObject, NSTokenFieldDelegate {
        var tokens: Binding<[String]>

        init(tokens: Binding<[String]>) { self.tokens = tokens }

        func controlTextDidChange(_ notification: Notification) {
            if let field = notification.object as? NSTokenField {
                tokens.wrappedValue = field.objectValue as? [String] ?? []
            }
        }
    }
}
