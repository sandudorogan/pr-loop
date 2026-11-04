import PRLoopKit
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
                bar
                Divider()
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

    private var bar: some View {
        HStack {
            Text(tab == .status ? "Status" : "PR Settings").font(.headline)
            Spacer()
            switch tab {
            case .status: Button("PR Settings", systemImage: "gearshape") { tab = .settings }.help("PR settings")
            case .settings: Button("Close", systemImage: "xmark") { tab = .status }.help("Back to the status")
            }
        }
        .labelStyle(.iconOnly)
        .buttonStyle(.borderless)
        .padding(.horizontal, 12)
        .frame(height: 36)
    }

    private func status(_ model: InspectorModel) -> some View {
        let item = model.item
        return Form {
            Section {
                InspectorHeader(model: model)
                Menu("Actions") {
                    PullRequestMenu(
                        rows: [.open(item)], store: store, peek: PeekFocus(model: peek, id: item.id),
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
