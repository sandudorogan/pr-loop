import AppKit
import PRWizardKit
import SwiftUI

/// The findings popover of a row, toggled by Space or ⌘Y, plus the VoiceOver findings of the cell.
struct FindingsPeek: ViewModifier {
    let id: String
    let popover: FindingsPopover?
    let isAnchor: Bool
    let peek: PeekModel
    @State private var scrollMonitor: Any?

    func body(content: Content) -> some View {
        if let popover {
            let speech = popover.findings.map(FindingsSpeech.init)
            content
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityCustomContent(AccessibilityCustomContentKey("Findings"), speech.map { Text($0.findings) })
                .accessibilityCustomContent(
                    AccessibilityCustomContentKey("At fix floor"), speech.map { Text($0.atFloor) }
                )
                .accessibilityCustomContent(
                    AccessibilityCustomContentKey("Top finding"), speech.flatMap(\.topFinding).map { Text($0) }
                )
                .popover(isPresented: isAnchor ? isShown : .constant(false), arrowEdge: .trailing) {
                    popover
                        .onAppear {
                            scrollMonitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [peek] in
                                peek.dismiss()
                                return $0
                            }
                        }
                        .onDisappear { scrollMonitor.map(NSEvent.removeMonitor) }
                }
        } else {
            content
        }
    }

    private var isShown: Binding<Bool> {
        Binding {
            peek.shownID == id
        } set: {
            if !$0, peek.shownID == id { peek.dismiss() }
        }
    }
}

extension View {
    func findingsPeek(_ id: String, _ popover: FindingsPopover?, isAnchor: Bool = false, peek: PeekModel) -> some View {
        modifier(FindingsPeek(id: id, popover: popover, isAnchor: isAnchor, peek: peek))
    }
}
