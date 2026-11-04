import PRLoopKit
import SwiftUI

struct WorkersSection: View {
    let scope: SettingsScope
    let layout: LanesLayout
    let totals: WorkerTotals
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        Section("Workers") {
            if layout.isGlobal { separateToggle }
            row("Reviews", lane: "review", title: layout.reviewTitle, kind: layout.review)
            row("Fix passes", lane: "fix", title: layout.fixTitle, kind: layout.fix)
            if let note = layout.sharedNote { caption(note) }
            if layout.showsTotals {
                Label {
                    Text(verbatim: totals.summary)
                } icon: {
                    Image(systemName: totals.isOverLimit ? "exclamationmark.triangle.fill" : "info.circle")
                }
                .font(.caption).foregroundStyle(totals.isOverLimit ? Tone.attention.color : Color.secondary)
            }
        }
    }

    private var separateToggle: some View {
        VStack(alignment: .leading, spacing: 4) {
            Toggle("Separate lanes per project", isOn: settings.isOn("lanes.separate", in: .allRepos))
            caption(
                settings.isSeparate
                    ? "Each repo gets its own pools. Still one daemon process."
                    : "One review pool and one fix pool serve every repo.")
            FieldError(messages: settings.errors.messages(at: "lanes.separate", in: .allRepos))
        }
    }

    @ViewBuilder private func row(_ name: String, lane: String, title: String, kind: LanesLayout.Workers) -> some View {
        switch kind {
        case .stepper:
            IntSettingRow(title: title, key: "\(lane).workers", scope: scope, style: .stepper(1...8))
        case .laneOff:
            LabeledContent(name) { Text("\(lane) lane off").foregroundStyle(.secondary) }
        case .unavailable:
            LabeledContent(name) { Text("no checkout, no pool").foregroundStyle(.secondary) }
        case .sharedPool:
            EmptyView()
        }
    }

    private func caption(_ text: String) -> some View {
        Text(verbatim: text).font(.caption).foregroundStyle(.secondary)
    }
}
