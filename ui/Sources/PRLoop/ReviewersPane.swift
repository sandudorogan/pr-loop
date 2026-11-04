import PRLoopKit
import SwiftUI

struct ReviewersPane: View {
    @Environment(QueueStore.self) private var queue
    @Environment(SettingsStore.self) private var settings
    @State private var selection: Int? = 0

    var body: some View {
        ScopedPane(width: 720, keys: ["review.reviewers[\(selection ?? 0)]"]) { scope in
            if let choices = settings.original?.choices {
                let project = queue.projects.first { $0.id == scope.rawValue }?.project
                let reviewers = settings.reviewers(in: scope)
                let isLocked = scope != .allRepos && !settings.draft.isOverridden("review.reviewers", in: scope)
                let skipped = reviewers.filter { ReviewerSummary($0, project: project).isSkipped }.map(\.id)
                if let line = PRLoopKit.ConventionsLine(scope, project: project, skipped: skipped) {
                    Section { ConventionsLine(line: line, checkout: project?.checkout?.path) }
                }
                Section {
                    if scope != .allRepos { usesDefault(isLocked, scope) }
                    HStack(alignment: .top, spacing: 12) {
                        ReviewerList(scope: scope, project: project, isLocked: isLocked, selection: $selection)
                        if let index = selection, reviewers.indices.contains(index) {
                            form(index, choices, scope).disabled(isLocked)
                        } else {
                            ContentUnavailableView("No Reviewer Selected", systemImage: "person.3")
                        }
                    }
                }
                .onChange(of: scope) { selection = 0 }
            }
        }
    }

    private func usesDefault(_ isLocked: Bool, _ scope: SettingsScope) -> some View {
        HStack {
            Toggle(
                "Use the default reviewers",
                isOn: Binding {
                    isLocked
                } set: {
                    settings.setUsesDefault($0, for: "review.reviewers", in: scope)
                })
            Spacer()
            OverrideMarker(kind: isLocked ? .inherited : .overridden) {
                settings.useDefault("review.reviewers", in: scope)
            }
        }
    }

    private func form(_ index: Int, _ choices: Choices, _ scope: SettingsScope) -> some View {
        ReviewerForm(
            reviewer: Binding {
                settings.reviewers(in: scope)[index]
            } set: { reviewer in
                settings.updateReviewer(at: index, in: scope) { $0 = reviewer }
            },
            choices: choices,
            errors: { settings.errors.messages(at: "review.reviewers[\(index)].\($0)", in: scope) })
    }
}
