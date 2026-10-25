import AppKit
import PRWizardKit
import ServiceManagement
import SwiftUI

struct LoginItemToggle: View {
    @State private var loginItem = LoginItemStore(service: SMAppService.mainApp)

    var body: some View {
        Toggle(isOn: Binding(get: { loginItem.state.isOn }, set: { loginItem.setOn($0) })) {
            Text("Open at login")
            if let caption = loginItem.caption { Text(caption) }
        }
        .task {
            for await _ in NotificationCenter.default.notifications(named: NSApplication.didBecomeActiveNotification) {
                loginItem.refresh()
            }
        }
        if loginItem.state.needsApproval {
            HStack {
                Spacer()
                Button("Open Login Items…") { SMAppService.openSystemSettingsLoginItems() }
            }
        }
    }
}
