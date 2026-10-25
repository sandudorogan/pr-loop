import PRWizardKit
import SwiftUI

struct PRInspector: View {
    enum Tab: String {
        case status, settings
    }

    let items: [QueueItem]
    @Environment(QueueStore.self) private var store
    @SceneStorage("inspectorTab") private var tab = Tab.status

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
                case .settings:
                    ContentUnavailableView(
                        "PR Settings", systemImage: "slider.horizontal.3",
                        description: Text("Per-PR overrides are not available yet."))
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
                Text(item.title).font(.headline)
                LabeledContent("Project", value: item.repo)
                LabeledContent("Head") { Text(model.head).monospaced() }
                LabeledContent("Base", value: item.base)
                LabeledContent("Lines") { Text(model.lines).monospacedDigit() }
                LabeledContent("Labels", value: model.labels)
                Menu("Actions") { PullRequestMenu(items: [item], store: store) }
            } header: {
                Text(model.title)
            }
            if let active = item.active { LiveSection(model: model, active: active) }
            ReviewSection(model: model)
            Section("Findings") {
                if let findings = item.findings {
                    FindingsView(findings: findings)
                    Text(findings.conventionsLine).font(.caption).foregroundStyle(.secondary)
                } else {
                    Text(item.detail).foregroundStyle(.secondary)
                }
            }
            FixSection(model: model)
        }
        .formStyle(.grouped)
    }
}

private struct LiveSection: View {
    let model: InspectorModel
    let active: ActiveRun

    var body: some View {
        Section("Live run") {
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
        }
    }
}
