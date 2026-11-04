import AppKit
import PRLoopKit
import SwiftUI

struct ApplyBar: View {
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        HStack {
            status
            Spacer()
            Button("Revert") { settings.revert() }.disabled(!settings.isDirty)
            Button("Apply") { Task { await settings.apply() } }
                .keyboardShortcut(.defaultAction)
                .disabled(!settings.isDirty || settings.isStale || settings.isApplying)
        }
        .padding(12)
        .overlay(alignment: .top) { Divider() }
    }

    @ViewBuilder private var status: some View {
        if settings.isStale {
            note("The config changed outside this window.", "exclamationmark.triangle.fill", .attention)
            Button("Reload") { Task { await settings.reload() } }
        } else if let savedTo = settings.savedTo, let original = settings.original {
            note(
                savedTo == original.path ? "Saved." : "Saved to the chezmoi source. Commit your dotfiles to keep it.",
                "checkmark.circle.fill", .good)
            Button("Reveal") { NSWorkspace.shared.activateFileViewerSelecting([URL(filePath: savedTo)]) }
        } else if let failure = settings.failure {
            note(ActionFailure(pr: nil, error: failure).message, "exclamationmark.triangle.fill", .bad)
        }
    }

    private func note(_ text: String, _ symbol: String, _ tone: Tone) -> some View {
        Label {
            Text(verbatim: text)
        } icon: {
            Image(systemName: symbol).foregroundStyle(tone.color)
        }
        .font(.callout)
    }
}
