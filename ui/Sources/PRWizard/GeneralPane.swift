import AppKit
import PRWizardKit
import SwiftUI

struct GeneralPane: View {
    @AppStorage(AppStorageKey.showsMenuBarExtra) private var showsMenuBarExtra = true
    @AppStorage(AppStorageKey.notifiesReady) private var notifiesReady = true
    @Environment(QueueStore.self) private var store
    @Environment(ReadyNotifications.self) private var notifications

    var body: some View {
        Form {
            Section("App") {
                Toggle("Show in menu bar", isOn: $showsMenuBarExtra)
                LoginItemToggle()
            }
            Section("Notifications") {
                Toggle("Notify when a colleague's PR is ready for your approval", isOn: $notifiesReady)
                    .onChange(of: notifiesReady) { Task { await notifications.authorize() } }
                if notifications.authorization == .denied {
                    LabeledContent {
                        Button("Open…") { openNotificationSettings() }
                    } label: {
                        Label("Notifications are off for PR Wizard in System Settings.", systemImage: "flag.fill")
                    }
                } else if notifications.authorization == .temporary {
                    LabeledContent {
                        Button("Open…") { openNotificationSettings() }
                    } label: {
                        Label(
                            "Ready alerts go away on their own. Set PR Wizard to Persistent in System Settings.",
                            systemImage: "flag.fill")
                    }
                }
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

    private func openNotificationSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension") {
            NSWorkspace.shared.open(url)
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
