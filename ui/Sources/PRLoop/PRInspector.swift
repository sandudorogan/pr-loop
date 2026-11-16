import PRLoopKit
import SwiftUI

/// Most important first: the PR, what runs on it now, its scope, its findings. The last passes sit at the bottom, and
/// shas, base and notes live in tooltips.
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
            let model = InspectorModel(item)
            VStack(spacing: 0) {
                bar(model)
                Divider()
                switch tab {
                case .status: status(model)
                case .settings: PRSettingsTab(item: item)
                }
            }
        } else {
            ContentUnavailableView(
                items.isEmpty ? "No Selection" : "Multiple Selection", systemImage: "sidebar.trailing")
        }
    }

    private func bar(_ model: InspectorModel) -> some View {
        HStack {
            Text(tab == .status ? model.title : "PR Settings").font(.headline)
            Spacer()
            switch tab {
            case .status:
                Menu {
                    PullRequestMenu(
                        rows: [.open(model.item)], store: store, peek: PeekFocus(model: peek, id: model.item.id),
                        showSettings: { tab = .settings })
                } label: {
                    Label("Actions", systemImage: "ellipsis.circle")
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help("Actions")
                Button("PR Settings", systemImage: "gearshape") { tab = .settings }.help("PR settings")
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
            Section { InspectorHeader(model: model) }
            if let active = item.active { LiveSection(model: model, active: active) }
            if let scope = item.scope { ScopeSection(scope: scope) }
            if let findings = item.findings {
                Section {
                    FindingsView(findings: findings)
                } header: {
                    SectionTitle(title: "Findings", symbol: "exclamationmark.bubble", tint: .orange)
                        .help(findings.conventionsLine)
                }
            }
            if item.review != nil || item.fix != nil { PassesSection(model: model) }
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
            LabeledContent(model.lane ?? "") { Text(active.since, style: .timer).monospacedDigit() }
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
