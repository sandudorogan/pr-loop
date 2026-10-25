import PRWizardKit
import SwiftUI

struct QueueFocus {
    let items: [QueueItem]
    let sidebar: Binding<SidebarSelection>
    let showsInspector: Binding<Bool>
    let showSettings: () -> Void
}
