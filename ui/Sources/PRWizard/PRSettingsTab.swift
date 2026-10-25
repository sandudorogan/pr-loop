import PRWizardKit
import SwiftUI

struct PRSettingsTab: View {
    private struct Reload: Hashable {
        let pr: PRRef
        let labels: [String]
        let override: [String]
    }

    private static let fixerKeys = [
        "fix.model", "fix.effort", "fix.prompt", "fix.merge_prompt", "fix.gates", "fix.test_retries",
        "fix.ci_tries", "fix.max_errors", "fix.turn_timeout_s", "fix.pass_timeout_s",
    ]

    let item: QueueItem
    @Environment(PRSettingsStore.self) private var store
    @Environment(SettingsStore.self) private var settings
    @State private var editsReviewers = false
    @State private var confirmsReset = false
    @SceneStorage("prFixerShown") private var showsFixer = false

    var body: some View {
        content
            .task(id: Reload(pr: item.ref, labels: item.labels, override: item.override)) {
                await store.show(item.ref)
            }
            .task { await settings.load() }
    }

    @ViewBuilder private var content: some View {
        if store.pr == item.ref, store.isGone {
            ContentUnavailableView("This PR is no longer in the queue", systemImage: "tray")
        } else if store.pr == item.ref, let config = store.config, let markers = store.markers,
            let choices = settings.original?.choices
        {
            form(config.effective, markers, choices)
        } else if let failure = store.failure ?? settings.failure {
            ContentUnavailableView(
                "No PR Settings", systemImage: "exclamationmark.triangle",
                description: Text(verbatim: ActionFailure(pr: item.ref, error: failure).message))
        } else {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func form(_ effective: EffectiveConfig, _ markers: PRMarkers, _ choices: Choices) -> some View {
        let count = markers.overridden.count
        return Form {
            Section {
                LabeledContent(
                    count == 1 ? "1 setting overridden on this PR" : "\(count) settings overridden on this PR"
                ) {
                    Button("Use Default") { if count > 1 { confirmsReset = true } else { reset() } }
                        .disabled(count == 0)
                }
                if store.wasReloaded {
                    Label("Changed elsewhere, reloaded", systemImage: "arrow.clockwise").font(.caption)
                        .foregroundStyle(Tone.attention.color)
                }
            } header: {
                Text(verbatim: "\(ProjectSummary.shortName(of: item.repo)) #\(item.number) · \(item.title)")
                    .lineLimit(1)
            }
            Section("Lanes") {
                lane("Review this PR", "review.enabled", effective.review.isEnabled, markers)
                lane("Fix this PR", "fix.enabled", effective.fix.isEnabled, markers)
            }
            Section {
                ForEach(Array(effective.review.reviewers.enumerated()), id: \.element.id) { index, reviewer in
                    PRReviewerRow(reviewer: reviewer, choices: choices) { changed in
                        var list = effective.review.reviewers
                        list[index] = changed
                        Task { await store.setReviewers(list) }
                    }
                }
                FieldError(messages: store.messages(at: "review.reviewers"))
                Button("Edit all reviewer fields…") { editsReviewers = true }
            } header: {
                HStack {
                    Text("Reviewers")
                    Spacer()
                    marker(["review.reviewers"], markers)
                }
            }
            Section {
                DisclosureGroup(isExpanded: $showsFixer) {
                    PRFixerFields(
                        effective: effective.fix, projectGates: projectGates, choices: choices, markers: markers)
                } label: {
                    HStack {
                        Text("Fixer")
                        Spacer()
                        marker(Self.fixerKeys, markers)
                    }
                }
            } footer: {
                Text("Kept across pushes. Cleared when the PR merges or closes.").font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .disabled(store.isWriting)
        .sheet(isPresented: $editsReviewers) {
            PRReviewersSheet(initial: effective.review.reviewers, choices: choices) { list in
                Task { await store.setReviewers(list) }
            }
        }
        .confirmationDialog(
            "Use the default settings for this PR?", isPresented: $confirmsReset, titleVisibility: .visible
        ) {
            Button("Use Default", role: .destructive, action: reset)
        } message: {
            Text("\(count) settings go back to the project and the defaults.")
        }
    }

    private var projectGates: [GateConfig]? {
        settings.original?.effective[item.repo]?.fix.gates
    }

    private func lane(_ title: String, _ path: String, _ isOn: Bool, _ markers: PRMarkers) -> some View {
        let source = markers.source(of: path)
        return VStack(alignment: .leading, spacing: 2) {
            HStack {
                Toggle(
                    title,
                    isOn: Binding {
                        isOn
                    } set: { on in
                        Task { await store.set(path, to: .bool(on)) }
                    }
                )
                .disabled(source.isLabel)
                .accessibilityHint(Text(verbatim: source.caption))
                Spacer()
                marker([path], markers)
            }
            FieldError(messages: store.messages(at: path))
        }
    }

    private func marker(_ paths: [String], _ markers: PRMarkers) -> OverrideMarker {
        OverrideMarker(kind: markers.source(of: paths).kind) {
            Task { await store.useDefault(markers.overridden(within: paths)) }
        }
    }

    private func reset() {
        Task { await store.useDefaults() }
    }
}
