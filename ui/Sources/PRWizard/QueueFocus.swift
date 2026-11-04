import PRWizardKit
import SwiftUI

struct QueueFocus {
    let rows: [TodoRow]
    let sidebar: Binding<SidebarSelection>
    let showsInspector: Binding<Bool>
    let showSettings: () -> Void
    let focusFilter: () -> Void
}
