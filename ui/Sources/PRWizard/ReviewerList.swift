import PRWizardKit
import SwiftUI

struct ReviewerList: View {
    let scope: SettingsScope
    let project: Project?
    let isLocked: Bool
    @Binding var selection: Int?
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        let reviewers = settings.reviewers(in: scope)
        VStack(spacing: 0) {
            List(selection: $selection) {
                ForEach(Array(reviewers.enumerated()), id: \.offset) { index, reviewer in
                    row(index, reviewer).tag(index)
                }
                .onMove { selection = settings.moveReviewers(fromOffsets: $0, toOffset: $1, in: scope) }
                .moveDisabled(isLocked)
            }
            .listStyle(.bordered)
            .alternatingRowBackgrounds(.disabled)
            bar(reviewers)
        }
        .frame(width: 250, height: 340)
    }

    private func row(_ index: Int, _ reviewer: ReviewerConfig) -> some View {
        let summary = ReviewerSummary(reviewer, project: project)
        return HStack(alignment: .firstTextBaseline) {
            Toggle(
                reviewer.label,
                isOn: Binding {
                    reviewer.isEnabled
                } set: { isOn in
                    settings.updateReviewer(at: index, in: scope) { $0.isEnabled = isOn }
                }
            )
            .labelsHidden()
            .disabled(isLocked)
            VStack(alignment: .leading, spacing: 1) {
                Text(verbatim: reviewer.label).lineLimit(1).truncationMode(.tail)
                Group {
                    Text(verbatim: summary.engine)
                    if let traits = summary.traits { Text(verbatim: traits) }
                    if summary.isSkipped {
                        Label("skipped here: no conventions", systemImage: "minus.circle")
                    }
                }
                .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    private func bar(_ reviewers: [ReviewerConfig]) -> some View {
        let index = selection.flatMap { reviewers.indices.contains($0) ? $0 : nil }
        return HStack(spacing: 2) {
            Button("Add Reviewer", systemImage: "plus") {
                selection = settings.addReviewer(copying: index ?? reviewers.count - 1, in: scope)
            }
            .disabled(!settings.canAddReviewer(in: scope))
            Button("Remove Reviewer", systemImage: "minus") {
                index.map { settings.removeReviewer(at: $0, in: scope) }
                selection = index.map { min($0, reviewers.count - 2) }
            }
            .disabled(index.map { !settings.canRemoveReviewer(at: $0, in: scope) } ?? true)
            Button("Duplicate Reviewer", systemImage: "plus.square.on.square") {
                selection = index.map { settings.duplicateReviewer(at: $0, in: scope) }
            }
            .disabled(index == nil || !settings.canAddReviewer(in: scope))
            Spacer()
        }
        .labelStyle(.iconOnly)
        .buttonStyle(.borderless)
        .padding(6)
        .disabled(isLocked)
    }
}
