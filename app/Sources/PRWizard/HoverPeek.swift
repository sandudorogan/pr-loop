import AppKit
import PRWizardKit
import SwiftUI

struct HoverPeek: ViewModifier {
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
                .contentShape(.rect)
                .onHover(perform: hover)
                .accessibilityCustomContent(AccessibilityCustomContentKey("Findings"), speech.map { Text($0.findings) })
                .accessibilityCustomContent(
                    AccessibilityCustomContentKey("At fix floor"), speech.map { Text($0.atFloor) }
                )
                .accessibilityCustomContent(
                    AccessibilityCustomContentKey("Top finding"), speech.flatMap(\.topFinding).map { Text($0) }
                )
                .popover(isPresented: isAnchor ? isShown : .constant(false), arrowEdge: .trailing) {
                    popover
                        .onHover(perform: hover)
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

    private func hover(_ isInside: Bool) {
        isInside ? peek.enter(id) : peek.exit(id)
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
    func hoverPeek(_ id: String, _ popover: FindingsPopover?, isAnchor: Bool = false, peek: PeekModel) -> some View {
        modifier(HoverPeek(id: id, popover: popover, isAnchor: isAnchor, peek: peek))
    }
}
