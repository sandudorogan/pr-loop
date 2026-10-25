import AppKit
import PRWizardKit
import SwiftUI

struct PullRequestMenu: View {
    let items: [QueueItem]
    let store: QueueStore
    let peek: PeekFocus?

    var body: some View {
        let projects = store.snapshot?.projects ?? []
        Button("Open on GitHub") { for item in items { NSWorkspace.shared.open(item.url) } }
            .keyboardShortcut("o")
            .disabled(items.isEmpty)
        Button("Copy Link") { copy(items.map(\.url.absoluteString)) }
            .keyboardShortcut("c", modifiers: [.command, .shift])
            .disabled(items.isEmpty)
        Divider()
        action("Move to Front", items.map(ActionAvailability.moveToFront), PendingAction.moveToFront, "]") {
            await store.moveToFront(items.map(\.ref))
        }
        action("Review Now", items.map { .review($0, in: projects) }, PendingAction.review, "r", [.command, .shift]) {
            for item in items { await store.review(item.ref) }
        }
        action("Retry Fix", items.map { .fix($0, in: projects) }, PendingAction.fix, "f", [.command, .shift]) {
            for item in items { await store.fix(item.ref) }
        }
        Divider()
        Button("Show Findings") { peek?.toggle() }
            .keyboardShortcut(.space, modifiers: [])
            .disabled(peek?.id == nil)
        Button("Copy Head SHA") { copy(items.map(\.head)) }
            .disabled(items.isEmpty)
    }

    private func action(
        _ title: String, _ availabilities: [ActionAvailability], _ pending: (PRRef) -> PendingAction,
        _ key: KeyEquivalent, _ modifiers: EventModifiers = .command, perform: @escaping () async -> Void
    ) -> some View {
        let availability = ActionAvailability.all(availabilities)
        let isPending = items.contains { store.pendingActions.contains(pending($0.ref)) }
        return Button(title) { Task { await perform() } }
            .keyboardShortcut(key, modifiers: modifiers)
            .disabled(items.isEmpty || !availability.isAvailable || isPending)
            .help(availability.reason ?? "")
    }

    private func copy(_ lines: [String]) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(lines.joined(separator: "\n"), forType: .string)
    }
}
