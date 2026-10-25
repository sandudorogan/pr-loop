import PRWizardKit
import SwiftUI

struct FixSection: View {
    let model: InspectorModel

    var body: some View {
        Section {
            if let fix = model.item.fix {
                LabeledContent("Status") {
                    HStack {
                        StatusBadge(status: fix.status)
                        if fix.isParked {
                            Label("Parked", systemImage: "parkingsign").foregroundStyle(Tone.attention.color)
                        }
                    }
                }
                if !fix.note.isEmpty { LabeledContent("Note", value: fix.note) }
                LabeledContent("Errors", value: model.fixErrors ?? "")
                LabeledContent("Fixed") {
                    Text(
                        verbatim: "\(model.fixedHead ?? "") · \(fix.at.formatted(.dateTime.weekday().hour().minute()))")
                }
            } else {
                Text("No fix pass yet").foregroundStyle(.secondary)
            }
        } header: {
            SectionTitle(title: "Fix", symbol: "hammer", tint: .purple)
        }
    }
}
