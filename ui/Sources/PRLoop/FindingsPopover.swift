import PRLoopKit
import SwiftUI

struct FindingsPopover: View {
    let findings: Findings?
    let detail: String
    let live: [ReviewerProgress]
    let url: URL

    init?(item: QueueItem) {
        guard item.findings != nil || item.active?.reviewers?.isEmpty == false else { return nil }
        findings = item.findings
        detail = item.detail
        live = item.active?.reviewers ?? []
        url = item.url
    }

    init(findings: Findings, url: URL) {
        self.findings = findings
        detail = ""
        live = []
        self.url = url
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let findings {
                FindingsView(findings: findings)
            } else {
                Text(detail).foregroundStyle(.secondary)
            }
            if !live.isEmpty {
                Divider()
                ForEach(live) { LiveRow(progress: $0, label: label(of: $0.id)) }
            }
            if let findings {
                Text(findings.conventionsFooter).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            HStack {
                Spacer()
                Link(destination: url) { Label("Open on GitHub", systemImage: "arrow.up.right") }
                    .labelStyle(.titleAndIcon)
            }
        }
        .padding(14)
        .frame(width: 380, alignment: .leading)
    }

    private func label(of id: String) -> String {
        findings?.reviewers.first { $0.id == id }?.label ?? id
    }
}

private struct LiveRow: View {
    let progress: ReviewerProgress
    let label: String

    var body: some View {
        HStack {
            Text(label).lineLimit(1)
            Spacer()
            if progress.state == .running { ProgressView().controlSize(.mini) }
            Text(InspectorModel.state(progress)).foregroundStyle(.secondary)
        }
        .font(.callout)
    }
}
