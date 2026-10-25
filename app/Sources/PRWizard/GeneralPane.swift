import AppKit
import PRWizardKit
import SwiftUI

struct GeneralPane: View {
    @AppStorage(AppStorageKey.showsMenuBarExtra) private var showsMenuBarExtra = true
    @Environment(QueueStore.self) private var store

    var body: some View {
        Form {
            Section("App") {
                Toggle("Show in menu bar", isOn: $showsMenuBarExtra)
                LoginItemToggle()
            }
            Section("Daemon") {
                daemon
            }
        }
        .formStyle(.grouped)
        .scrollDisabled(true)
        .frame(width: 560)
        .fixedSize()
    }

    @ViewBuilder private var daemon: some View {
        if let info = store.info, case .live(let snapshot) = store.phase {
            LabeledContent {
                Text(verbatim: DaemonSummary(info, snapshot).line).foregroundStyle(.secondary)
            } label: {
                state(snapshot.isPaused ? "Paused" : "Running", .good)
            }
            HStack {
                Spacer()
                Button("Reveal Config") {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(filePath: info.config.realPath)])
                }
                Button("Open Log") { NSWorkspace.shared.open(URL(filePath: info.paths.log)) }
                Button(snapshot.isPaused ? "Resume" : "Pause") { Task { await store.setPaused(!snapshot.isPaused) } }
                    .disabled(store.pendingActions.contains(.setPaused(!snapshot.isPaused)))
            }
        } else if store.phase.isDisconnected {
            LabeledContent {
                Button("Start") { Task { await store.startDaemon(with: ProcessDaemonLauncher()) } }
                    .disabled(store.pendingActions.contains(.startDaemon))
            } label: {
                state("Not running", .neutral, filled: false)
            }
        } else if case .incompatible(let api) = store.phase {
            state("The daemon speaks API v\(api). This app speaks v1.", .bad)
        } else {
            state("Connecting…", .neutral)
        }
    }

    private func state(_ title: String, _ tone: Tone, filled: Bool = true) -> some View {
        Label {
            Text(verbatim: title)
        } icon: {
            Image(systemName: filled ? "circle.fill" : "circle").font(.caption2).foregroundStyle(tone.color)
        }
    }
}
