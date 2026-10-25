import AppKit
import PRWizardKit
import SwiftUI

struct LanesPane: View {
    static let keys = [
        "review.enabled", "fix.enabled", "review.workers", "fix.workers", "review.rounds", "review.max_added",
        "review.trivial", "review.timeout_s", "lanes.separate", "detect.roots", "refresh",
    ]

    var body: some View {
        ScopedPane(width: 600, keys: Self.keys) { scope in
            LanesContent(scope: scope)
        }
    }
}

private struct LanesContent: View {
    let scope: SettingsScope
    @Environment(QueueStore.self) private var queue
    @Environment(SettingsStore.self) private var settings
    @State private var editsRoots = false
    @State private var editsTrivial = false

    var body: some View {
        let projects = queue.projects.map(\.project)
        let layout = settings.lanesLayout(in: scope, projects: projects)
        if layout.isGlobal {
            WorkersSection(scope: scope, layout: layout, totals: settings.workerTotals(projects: projects))
            lanes(layout)
        } else {
            checkout(projects.first { SettingsScope.project($0.repo) == scope })
            lanes(layout)
            WorkersSection(scope: scope, layout: layout, totals: settings.workerTotals(projects: projects))
        }
        gates
        if layout.isGlobal {
            Section("Checkouts") {
                SettingRow(key: "detect.roots", scope: scope) {
                    listRow("Find checkouts in", "detect.roots", $editsRoots)
                }
            }
            .sheet(isPresented: $editsRoots) { RootsSheet() }
            Section("Refresh") {
                IntSettingRow(
                    title: "Fetch the queue every", key: "refresh.interval_s", scope: scope, style: .field(unit: "min"),
                    per: 60)
                IntSettingRow(
                    title: "… while a reviewer idles", key: "refresh.idle_s", scope: scope, style: .field(unit: "s"))
            }
        }
    }

    private func lanes(_ layout: LanesLayout) -> some View {
        Section {
            SettingRow(key: "review.enabled", scope: scope) {
                Toggle("Review lane", isOn: settings.isOn("review.enabled", in: scope))
            }
            SettingRow(key: "fix.enabled", scope: scope) {
                Toggle("Fix lane", isOn: settings.isOn("fix.enabled", in: scope))
            }
        } header: {
            Text("Lanes")
        } footer: {
            if layout.isGlobal { Text("Every repo inherits these unless it overrides them.") }
        }
    }

    private var gates: some View {
        Section("Review gates") {
            IntSettingRow(
                title: "Rounds before a human looks", key: "review.rounds", scope: scope, style: .stepper(1...50))
            IntSettingRow(
                title: "Skip PRs that add more than", key: "review.max_added", scope: scope,
                style: .field(unit: "lines"))
            SettingRow(key: "review.trivial", scope: scope) {
                listRow("Trivial files", "review.trivial", $editsTrivial)
            }
            IntSettingRow(
                title: "Timeout per reviewer call", key: "review.timeout_s", scope: scope, style: .field(unit: "min"),
                per: 60)
        }
        .sheet(isPresented: $editsTrivial) { TrivialFilesSheet(scope: scope) }
    }

    private func listRow(_ title: String, _ key: String, _ isEditing: Binding<Bool>) -> some View {
        LabeledContent(title) {
            HStack {
                Text(verbatim: ListSummary.line(settings.strings(key, in: scope))).lineLimit(1).foregroundStyle(
                    .secondary)
                Button("Edit…") { isEditing.wrappedValue = true }
            }
        }
    }

    @ViewBuilder private func checkout(_ project: Project?) -> some View {
        Section {
            LabeledContent("Checkout") {
                if let checkout = project?.checkout {
                    HStack {
                        Text(verbatim: (checkout.path as NSString).abbreviatingWithTildeInPath).lineLimit(1)
                        Text(verbatim: checkout.source.rawValue).font(.caption).foregroundStyle(.secondary)
                        Button("Reveal") {
                            NSWorkspace.shared.activateFileViewerSelecting([URL(filePath: checkout.path)])
                        }
                    }
                } else {
                    Text("none").foregroundStyle(.secondary)
                }
            }
        }
    }
}
