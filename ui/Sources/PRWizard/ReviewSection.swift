import PRWizardKit
import SwiftUI

struct ReviewSection: View {
    let model: InspectorModel

    var body: some View {
        Section {
            if let review = model.item.review {
                LabeledContent("Status") { StatusBadge(status: review.status) }
                if let verdict = model.verdict { LabeledContent("Verdict", value: verdict) }
                LabeledContent("Rounds with findings") { Text(verbatim: "\(review.rounds)") }
                LabeledContent("Hold", value: review.isHeld ? "Held until a review request" : "No")
                if !review.note.isEmpty { LabeledContent("Note", value: review.note) }
                LabeledContent("Reviewed") {
                    Text(
                        verbatim:
                            "\(model.reviewedHead ?? "") · \(review.at.formatted(.dateTime.weekday().hour().minute()))")
                }
            } else {
                Text("Not reviewed yet").foregroundStyle(.secondary)
            }
        } header: {
            SectionTitle(title: "Review", symbol: "eye", tint: .blue)
        }
    }
}
