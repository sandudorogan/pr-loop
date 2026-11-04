import AppKit
import PRLoopKit
import SwiftUI

/// A Settings pane that edits one scope: the dropdown, its banners, the content, and the shared Apply bar.
struct ScopedPane<Content: View>: View {
    let width: CGFloat
    let keys: [String]
    @ViewBuilder let content: (SettingsScope) -> Content
    @AppStorage(AppStorageKey.settingsScope) private var stored = SettingsScope.allRepos
    @Environment(QueueStore.self) private var queue
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        let options = settings.scopeOptions(for: queue.projects)
        let scope = options.contains { $0.scope == stored } ? stored : .allRepos
        VStack(spacing: 0) {
            Form {
                ScopePicker(
                    scope: Binding {
                        scope
                    } set: {
                        stored = $0
                    }, options: options)
                if let original = settings.original {
                    banners(original, options.first { $0.scope == scope })
                    content(scope)
                } else if settings.failure != nil {
                    ContentUnavailableView {
                        Label("PR Loop is not running", systemImage: "bolt.horizontal.circle")
                    } actions: {
                        Button("Retry") { Task { await settings.reload() } }
                    }
                } else {
                    ProgressView("Loading the config…").frame(maxWidth: .infinity)
                }
            }
            .formStyle(.grouped)
            .scrollDisabled(true)
            ApplyBar()
        }
        .frame(width: width)
        .fixedSize()
        .task { await settings.load() }
    }

    @ViewBuilder private func banners(_ original: ConfigEnvelope, _ option: ScopeOption?) -> some View {
        let problems = settings.errors.unclaimed(in: option?.scope ?? .allRepos, by: keys)
        if original.error != nil || option?.problem != nil || !problems.isEmpty {
            Section {
                if let error = original.error {
                    banner("The config file is invalid. The daemon runs on defaults: \(error)")
                    Button("Reveal Config") {
                        NSWorkspace.shared.activateFileViewerSelecting([URL(filePath: original.realPath)])
                    }
                }
                if let problem = option?.problem { banner(problem) }
                ForEach(problems, id: \.self) { banner("\($0.path): \($0.message)") }
            }
        }
    }

    private func banner(_ text: String) -> some View {
        Label {
            Text(verbatim: text)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Tone.attention.color)
        }
    }
}
