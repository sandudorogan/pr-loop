import PRWizardKit
import SwiftUI

struct ProjectRow: View {
    let summary: ProjectSummary

    var body: some View {
        Label {
            VStack(alignment: .leading) {
                Text(summary.project.repo).lineLimit(1).truncationMode(.middle)
                Text(summary.laneLine).font(.caption).foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: "folder")
        }
        .badge(badge)
        .help(summary.needsAttention ? summary.project.error ?? "No local checkout under detect.roots" : "")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "\(summary.project.repo), \(summary.readyCount) ready, \(summary.laneLine.replacing(" · ", with: " and "))")
    }

    private var badge: Text? {
        if summary.needsAttention {
            return Text(Image(systemName: "exclamationmark.triangle")).foregroundStyle(Tone.attention.color)
        }
        return summary.readyCount > 0 ? Text("\(summary.readyCount)") : nil
    }
}
