import PRWizardKit
import SwiftUI

struct PRInspector: View {
    enum Tab: String {
        case status, settings
    }

    let items: [QueueItem]
    @Binding var tab: Tab
    @Environment(QueueStore.self) private var store
    @Environment(PeekModel.self) private var peek

    var body: some View {
        if items.count == 1, let item = items.first {
            VStack(spacing: 0) {
                Picker("Inspector", selection: $tab) {
                    Text("Status").tag(Tab.status)
                    Text("Settings").tag(Tab.settings)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .padding(8)
                switch tab {
                case .status: status(InspectorModel(item))
                case .settings: PRSettingsTab(item: item)
                }
            }
        } else {
            ContentUnavailableView(
                items.isEmpty ? "No Selection" : "Multiple Selection", systemImage: "sidebar.trailing")
        }
    }

    private func status(_ model: InspectorModel) -> some View {
        let item = model.item
        return Form {
            Section {
                InspectorHeader(model: model)
                Menu("Actions") {
                    PullRequestMenu(
                        items: [item], store: store, peek: PeekFocus(model: peek, id: item.id),
                        showSettings: { tab = .settings })
                }
            }
            if let active = item.active { LiveSection(model: model, active: active) }
            ReviewSection(model: model)
            Section {
                if let findings = item.findings {
                    FindingsView(findings: findings)
                    Text(findings.conventionsLine).font(.caption).foregroundStyle(.secondary)
                } else {
                    Text(item.detail).foregroundStyle(.secondary)
                }
            } header: {
                SectionTitle(title: "Findings", symbol: "exclamationmark.bubble", tint: .orange)
            }
            FixSection(model: model)
        }
        .formStyle(.grouped)
        .labeledContentStyle(InspectorRowStyle())
    }
}

private struct LiveSection: View {
    let model: InspectorModel
    let active: ActiveRun

    var body: some View {
        Section {
            LabeledContent("Lane", value: model.lane ?? "")
            LabeledContent("Running for") { Text(active.since, style: .timer).monospacedDigit() }
            ForEach(active.reviewers ?? []) { progress in
                LabeledContent(model.reviewerLabel(progress.id)) {
                    HStack(spacing: 6) {
                        if progress.state == .running { ProgressView().controlSize(.small) }
                        Text(InspectorModel.state(progress))
                    }
                }
            }
        } header: {
            SectionTitle(title: "Live run", symbol: "play.circle.fill", tint: Tone.working.color)
        }
    }
}
