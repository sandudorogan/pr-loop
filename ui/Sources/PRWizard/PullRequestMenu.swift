import AppKit
import PRWizardKit
import SwiftUI

struct PullRequestMenu: View {
    let rows: [TodoRow]
    let store: QueueStore
    let peek: PeekFocus?
    var showSettings: (() -> Void)?

    private var items: [QueueItem] { rows.compactMap(\.item) }

    var body: some View {
        let projects = store.snapshot?.projects ?? []
        Button("Open on GitHub") { for row in rows { NSWorkspace.shared.open(row.url) } }
            .keyboardShortcut("o")
            .disabled(rows.isEmpty)
        Button("Copy Link") { copy(rows.map(\.url.absoluteString)) }
            .keyboardShortcut("c", modifiers: [.command, .shift])
            .disabled(rows.isEmpty)
        Divider()
        DoneButton(rows: rows, store: store).keyboardShortcut("d", modifiers: [.command, .shift])
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
        action(items.resumes ? "Resume" : "Pause", [], PendingAction.pause, "p", [.command, .shift]) {
            await store.setPaused(items.map(\.ref), !items.resumes)
        }
        Divider()
        Button("Show Findings") { peek?.toggle() }
            .keyboardShortcut("y")
            .disabled(peek?.id == nil)
        Button("PR Settings…") { showSettings?() }
            .keyboardShortcut(",", modifiers: [.command, .shift])
            .disabled(items.count != 1 || showSettings == nil)
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

/// Mark Done, or Move to To-Do when every selected row is done.
struct DoneButton: View {
    let rows: [TodoRow]
    let store: QueueStore

    var body: some View {
        let back = rows.movesBack
        let refs = rows.doneRefs
        Button {
            Task { await store.setDone(refs, !back) }
        } label: {
            Label(back ? "Move to To-Do" : "Mark Done", systemImage: back ? "arrow.uturn.backward" : "checkmark.circle")
        }
        .disabled(refs.isEmpty || refs.contains { store.pendingActions.contains(.done($0)) })
        .help(
            refs.isEmpty
                ? (back ? "A merged or closed PR stays done" : "Select a PR to mark done")
                : back ? "Move the PR back to the to-do list" : "Mark the PR done: no new review or fix")
    }
}
